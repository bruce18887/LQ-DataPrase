"""SFTP 单文件下载 SSE 流（download_file_stream）后端测试。

覆盖：
1. ``download_file_events`` 生成器：progress → done 事件序列、下载即注册；
2. 超时：deadline 超限 → error 事件 + 半截文件清理；
3. 传输异常：socket 错误 → error 事件 + 半截文件清理；
4. API 契约：非 CSV 400 / 未连接 400 / SSE 响应可迭代；
5. ``clamp_timeout`` 钳位。
"""

import os
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings

from rest_framework.test import APITestCase

from apps.datafiles.models import DataFile
from apps.datafiles.utils import resolve_file_path
from apps.sftp import downloads as dl
from apps.sftp.views import SftpViewSet

User = get_user_model()


class FakeRemoteFile:
    """模拟 paramiko SFTPFile：按序返回预设 chunk，耗尽后返回 b''。"""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.closed = False

    def read(self, n):
        if not self._chunks:
            return b''
        return self._chunks.pop(0)

    def close(self):
        self.closed = True


class FakeSftp:
    """最小 SFTPClient 替身：stat + open（download_file_events 只用到这两个）。"""

    def __init__(self, content, size=None):
        self._content = content
        self._size = size if size is not None else len(content)
        self.opened = False

    def stat(self, remote_path):
        attr = mock.MagicMock()
        attr.st_size = self._size
        return attr

    def open(self, remote_path, mode='rb'):
        self.opened = True
        # 256KB 分块读取，模拟真实传输
        chunk = self._content[:dl.DOWNLOAD_CHUNK_SIZE]
        rest = self._content[dl.DOWNLOAD_CHUNK_SIZE:]
        return FakeRemoteFile([chunk, rest] if rest else [chunk])

    def get_channel(self):
        ch = mock.MagicMock()
        ch.gettimeout.return_value = None
        return ch


class ClampTimeoutTests(APITestCase):
    def test_default_when_missing(self):
        self.assertEqual(dl.clamp_timeout(None), dl.DEFAULT_TIMEOUT_SEC)

    def test_default_when_non_numeric(self):
        self.assertEqual(dl.clamp_timeout('abc'), dl.DEFAULT_TIMEOUT_SEC)

    def test_clamped_to_min(self):
        self.assertEqual(dl.clamp_timeout(1), dl.MIN_TIMEOUT_SEC)

    def test_clamped_to_max(self):
        self.assertEqual(dl.clamp_timeout(99999), dl.MAX_TIMEOUT_SEC)

    def test_in_range_passthrough(self):
        self.assertEqual(dl.clamp_timeout(900), 900)


class DownloadFileEventsTests(APITestCase):
    """download_file_events 生成器（绕过 HTTP 层，直接驱动）。"""

    def setUp(self):
        self.user = User.objects.create_user(username='dl_stream', password='pw')
        self._tmp = tempfile.mkdtemp(prefix='sftp_stream_test_')
        self.addCleanup(lambda: shutil.rmtree(self._tmp, ignore_errors=True))
        self._media_override = override_settings(
            MEDIA_ROOT=os.path.join(self._tmp, 'media')
        )
        self._media_override.enable()
        self.addCleanup(self._media_override.disable)

    def _file_path(self, name):
        return os.path.join(
            self._tmp, 'media', 'data', self.user.username, 'single', name)

    def test_success_emits_progress_then_done_and_registers(self):
        sftp = FakeSftp(b'a,b\n1,2\n')
        file_path = self._file_path('prod_123.csv')
        events = list(dl.download_file_events(
            sftp, self.user, '/data/prod_123.csv', file_path, 600))

        self.assertEqual([e['event'] for e in events], ['progress', 'done'])
        prog, done = events
        self.assertEqual(prog['percent'], 100)
        self.assertEqual(prog['bytes_done'], 8)
        self.assertEqual(prog['total_bytes'], 8)
        self.assertIn('speed', prog)
        self.assertEqual(done['filename'], 'prod_123.csv')
        self.assertEqual(done['size'], 8)
        self.assertTrue(done.get('datafile_id'))
        self.assertTrue(os.path.exists(file_path))

        df = DataFile.objects.get(pk=done['datafile_id'])
        self.assertEqual(df.owner, self.user)
        self.assertEqual(df.file_type, 'single')
        self.assertTrue(os.path.exists(resolve_file_path(df.file_path)))

    def test_timeout_emits_error_and_removes_partial(self):
        fake_now = [0.0]

        class SlowRemote(FakeRemoteFile):
            def read(self, n):
                fake_now[0] += 31  # 读取后时间越过 deadline，下一轮循环触发超时
                return super().read(n)

        class SlowSftp(FakeSftp):
            def open(self, remote_path, mode='rb'):
                self.opened = True
                return SlowRemote([b'a,b\n1,2\n'])

        sftp = SlowSftp(b'a,b\n1,2\n', size=8)
        file_path = self._file_path('slow.csv')
        with mock.patch('apps.sftp.downloads.time.time',
                        side_effect=lambda: fake_now[0]):
            events = list(dl.download_file_events(
                sftp, self.user, '/data/slow.csv', file_path, 30))

        self.assertEqual([e['event'] for e in events],
                         ['progress', 'error'])
        self.assertIn('超时', events[1]['message'])
        # 半截文件被清理，未注册
        self.assertFalse(os.path.exists(file_path))
        self.assertEqual(DataFile.objects.count(), 0)

    def test_transfer_error_emits_error_and_removes_partial(self):
        class BrokenRemote(FakeRemoteFile):
            def read(self, n):
                raise OSError('connection reset by peer')

        class BrokenSftp(FakeSftp):
            def open(self, remote_path, mode='rb'):
                return BrokenRemote([])

        sftp = BrokenSftp(b'')
        file_path = self._file_path('broken.csv')
        events = list(dl.download_file_events(
            sftp, self.user, '/data/broken.csv', file_path, 600))

        self.assertEqual([e['event'] for e in events], ['error'])
        self.assertIn('connection reset', events[0]['message'])
        self.assertFalse(os.path.exists(file_path))
        self.assertEqual(DataFile.objects.count(), 0)

    def test_generator_exit_cleans_partial(self):
        sftp = FakeSftp(b'a,b\n1,2\n')
        file_path = self._file_path('cancel.csv')
        gen = dl.download_file_events(
            sftp, self.user, '/data/cancel.csv', file_path, 600)
        next(gen)  # 拿到第一个 progress 事件
        with self.assertRaises(GeneratorExit):
            gen.throw(GeneratorExit)
        self.assertFalse(os.path.exists(file_path))
        self.assertEqual(DataFile.objects.count(), 0)


class DownloadFileStreamApiTests(APITestCase):
    """POST /api/v1/sftp/download_file_stream/ 契约。"""

    def setUp(self):
        self.user = User.objects.create_user(username='dl_api', password='pw')
        self.client.force_authenticate(self.user)
        self._tmp = tempfile.mkdtemp(prefix='sftp_stream_api_')
        self.addCleanup(lambda: shutil.rmtree(self._tmp, ignore_errors=True))
        self._media_override = override_settings(
            MEDIA_ROOT=os.path.join(self._tmp, 'media')
        )
        self._media_override.enable()
        self.addCleanup(self._media_override.disable)

    def _patch_sftp(self, sftp):
        return mock.patch.object(
            SftpViewSet, '_get_connection', return_value=sftp)

    def test_non_csv_returns_400(self):
        with self._patch_sftp(FakeSftp(b'x')):
            resp = self.client.post(
                '/api/v1/sftp/download_file_stream/',
                {'path': '/data/note.txt'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('仅支持 CSV', resp.data['error'])

    def test_not_connected_returns_400(self):
        with mock.patch.object(
                SftpViewSet, '_get_connection', return_value=None):
            resp = self.client.post(
                '/api/v1/sftp/download_file_stream/',
                {'path': '/data/a.csv'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['error'], 'not_connected')

    def test_streams_progress_and_done_events(self):
        with self._patch_sftp(FakeSftp(b'a,b\n1,2\n')):
            resp = self.client.post(
                '/api/v1/sftp/download_file_stream/',
                {'path': '/data/prod.csv', 'timeout': 60}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/event-stream')
        raw = b''.join(resp.streaming_content)
        self.assertIn(b'data: {"event": "progress"', raw)
        self.assertIn(b'"percent": 100', raw)
        self.assertIn(b'data: {"event": "done"', raw)
        self.assertIn(b'"datafile_id"', raw)
        # 下载即注册
        self.assertEqual(
            DataFile.objects.filter(owner=self.user, file_type='single').count(), 1)
