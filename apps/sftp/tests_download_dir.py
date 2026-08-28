"""SFTP 目录批量下载 SSE 生成器（download_dir_events）测试。

覆盖：
1. 进度按**总下载字节数**计算：percent = 累计字节 / 远端总字节（分块实时）；
2. 大文件下载期间发出中间进度事件（不再卡在低百分比）；
3. 单文件失败：清理半截文件 + error 事件 + 继续下一文件；
4. 整体超时（DirDownloadTimeout）：中止流 + 清理半截文件 + invalidate；
5. 客户端断开（GeneratorExit）：清理半截文件 + invalidate；
6. API 契约：SSE 响应 / 未连接 400 / 空目录 400 / 下载即注册。
"""

import os
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings

from rest_framework.test import APITestCase

from apps.datafiles.models import DataFile
from apps.sftp import downloads as dl
from apps.sftp.views import SftpViewSet

User = get_user_model()


class FakeRemoteFile:
    """按 chunk_size 分块返回内容，耗尽后返回 b''。"""

    def __init__(self, content, chunk_size):
        self._content = content
        self._chunk_size = chunk_size
        self.closed = False

    def read(self, n):
        if not self._content:
            return b''
        part = self._content[:self._chunk_size]
        self._content = self._content[self._chunk_size:]
        return part

    def close(self):
        self.closed = True


class FailAfterRemote(FakeRemoteFile):
    """读取 ``fail_after`` 次后抛出传输错误（模拟传输中断）。"""

    def __init__(self, content, chunk_size, fail_after):
        super().__init__(content, chunk_size)
        self._fail_after = fail_after
        self._calls = 0

    def read(self, n):
        self._calls += 1
        if self._calls > self._fail_after:
            raise OSError('connection reset by peer')
        return super().read(n)


class FakeSftp:
    """最小 SFTPClient 替身：open（分块读取）+ get_channel（channel_timeout 用）。"""

    def __init__(self, files, chunk_size=None, fail_after=None, broken=None):
        self._files = files                  # remote_path -> bytes
        self._chunk_size = chunk_size or dl.DOWNLOAD_CHUNK_SIZE
        self._fail_after = fail_after or {}  # remote_path -> 读取次数上限
        self._broken = broken or {}          # remote_path -> open 时抛出的异常

    def open(self, remote_path, mode='rb'):
        if remote_path in self._broken:
            raise self._broken[remote_path]
        content = self._files[remote_path]
        fail_after = self._fail_after.get(remote_path)
        if fail_after:
            return FailAfterRemote(content, self._chunk_size, fail_after)
        return FakeRemoteFile(content, self._chunk_size)

    def get_channel(self):
        ch = mock.MagicMock()
        ch.gettimeout.return_value = None
        return ch


def advancing(step):
    """返回每次调用递增 step 的假 time.time（控制节流与 deadline）。"""
    state = [0.0]

    def fake_time():
        state[0] += step
        return state[0]

    return fake_time


class DownloadDirEventsTests(APITestCase):
    """download_dir_events 生成器（绕过 HTTP 层直接驱动）。"""

    def setUp(self):
        self.user = User.objects.create_user(username='dl_dir', password='pw')
        self._tmp = tempfile.mkdtemp(prefix='sftp_dir_test_')
        self.addCleanup(lambda: shutil.rmtree(self._tmp, ignore_errors=True))
        self._media_override = override_settings(
            MEDIA_ROOT=os.path.join(self._tmp, 'media')
        )
        self._media_override.enable()
        self.addCleanup(self._media_override.disable)
        self.local_dir = os.path.join(
            self._tmp, 'media', 'data', self.user.username, 'batch', 'bat')

    def _fl(self, entries):
        """构造 file_list：(remote_path, rel_path, size, mtime)。"""
        return [(r, rel, size, 0) for r, rel, size in entries]

    def test_progress_percent_by_total_bytes(self):
        sftp = FakeSftp({
            '/r/a.csv': b'0' * 10,
            '/r/b.csv': b'1' * 20,
            '/r/c.csv': b'2' * 30,
        })
        fl = self._fl([
            ('/r/a.csv', 'a.csv', 10),
            ('/r/b.csv', 'b.csv', 20),
            ('/r/c.csv', 'c.csv', 30),
        ])
        events = list(dl.download_dir_events(
            sftp, self.user, fl, self.local_dir, 'bat', 600))

        progs = [e for e in events if e['event'] == 'progress']
        # 每个文件至少一个事件；percent = 累计字节 / 总字节（60）
        self.assertEqual([p['percent'] for p in progs], [17, 50, 100])
        self.assertEqual([p['bytes_done'] for p in progs], [10, 30, 60])
        self.assertTrue(all(p['total_bytes'] == 60 for p in progs))
        self.assertEqual(progs[-1]['current'], 3)
        self.assertEqual(progs[-1]['total'], 3)
        self.assertEqual(progs[-1]['filename'], 'c.csv')

        done = events[-1]
        self.assertEqual(done['event'], 'done')
        self.assertEqual(done['file_count'], 3)
        self.assertEqual(done['total'], 3)
        self.assertEqual(done['saved_dir'], self.local_dir)
        self.assertEqual(len([e for e in events if e['event'] == 'error']), 0)

        # 全部写出 + 下载即注册（batch）
        for name in ('a.csv', 'b.csv', 'c.csv'):
            self.assertTrue(os.path.exists(os.path.join(self.local_dir, name)))
        self.assertEqual(
            DataFile.objects.filter(owner=self.user, file_type='batch').count(), 3)

    def test_large_file_emits_intermediate_progress(self):
        sftp = FakeSftp({'/r/big.csv': b'z' * 3000}, chunk_size=700)
        fl = self._fl([('/r/big.csv', 'big.csv', 3000)])
        with mock.patch('apps.sftp.downloads.time.time',
                        side_effect=advancing(0.25)):
            events = list(dl.download_dir_events(
                sftp, self.user, fl, self.local_dir, 'bat', 600))

        progs = [e for e in events if e['event'] == 'progress']
        # 大文件分块到达：发出多个中间进度事件，百分比单调上升
        self.assertGreater(len(progs), 1)
        percents = [p['percent'] for p in progs]
        self.assertEqual(percents, sorted(percents))
        self.assertLess(progs[0]['percent'], 100)
        self.assertEqual(progs[-1]['percent'], 100)
        self.assertEqual(progs[-1]['bytes_done'], 3000)
        self.assertEqual(events[-1]['event'], 'done')

    def test_file_error_continues_and_cleans_partial(self):
        sftp = FakeSftp(
            {'/r/a.csv': b'a' * 10, '/r/b.csv': b'b' * 100, '/r/c.csv': b'c' * 10},
            chunk_size=40,
            fail_after={'/r/b.csv': 1},  # 读 40 字节后传输中断
        )
        fl = self._fl([
            ('/r/a.csv', 'a.csv', 10),
            ('/r/b.csv', 'b.csv', 100),
            ('/r/c.csv', 'c.csv', 10),
        ])
        events = list(dl.download_dir_events(
            sftp, self.user, fl, self.local_dir, 'bat', 600))

        errors = [e for e in events if e['event'] == 'error']
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['filename'], 'b.csv')
        self.assertIn('connection reset', errors[0]['message'])
        self.assertEqual(events[-1]['event'], 'done')
        self.assertEqual(events[-1]['file_count'], 2)

        # b.csv 半截文件被清理（其余完整保留），未注册
        self.assertFalse(os.path.exists(os.path.join(self.local_dir, 'b.csv')))
        self.assertTrue(os.path.exists(os.path.join(self.local_dir, 'a.csv')))
        self.assertTrue(os.path.exists(os.path.join(self.local_dir, 'c.csv')))
        self.assertEqual(
            DataFile.objects.filter(owner=self.user, file_type='batch').count(), 2)

    def test_timeout_aborts_stream_and_cleans_partial(self):
        sftp = FakeSftp({'/r/a.csv': b'a' * 3000}, chunk_size=700)
        fl = self._fl([('/r/a.csv', 'a.csv', 3000)])
        with mock.patch('apps.sftp.downloads.time.time',
                        side_effect=advancing(600)), \
                mock.patch.object(dl.pool, 'invalidate') as invalidate:
            events = list(dl.download_dir_events(
                sftp, self.user, fl, self.local_dir, 'bat', 600))

        self.assertEqual([e['event'] for e in events], ['error'])
        self.assertIn('超时', events[0]['message'])
        # 半截文件被清理，未注册
        self.assertFalse(os.path.exists(os.path.join(self.local_dir, 'a.csv')))
        self.assertEqual(DataFile.objects.count(), 0)
        invalidate.assert_called_once_with(self.user.id)

    def test_generator_exit_cleans_partial(self):
        sftp = FakeSftp({'/r/a.csv': b'a' * 2000}, chunk_size=700)
        fl = self._fl([('/r/a.csv', 'a.csv', 2000)])
        with mock.patch('apps.sftp.downloads.time.time',
                        side_effect=advancing(0.2)), \
                mock.patch.object(dl.pool, 'invalidate') as invalidate:
            gen = dl.download_dir_events(
                sftp, self.user, fl, self.local_dir, 'bat', 600)
            next(gen)  # 拿到第一个中间 progress 事件（文件尚未读完）
            with self.assertRaises(GeneratorExit):
                gen.throw(GeneratorExit)

        self.assertFalse(os.path.exists(os.path.join(self.local_dir, 'a.csv')))
        self.assertEqual(DataFile.objects.count(), 0)
        invalidate.assert_called_once_with(self.user.id)


class DownloadDirApiTests(APITestCase):
    """POST /api/v1/sftp/download_dir/ 契约。"""

    def setUp(self):
        self.user = User.objects.create_user(username='dl_dir_api', password='pw')
        self.client.force_authenticate(self.user)
        self._tmp = tempfile.mkdtemp(prefix='sftp_dir_api_')
        self.addCleanup(lambda: shutil.rmtree(self._tmp, ignore_errors=True))
        self._media_override = override_settings(
            MEDIA_ROOT=os.path.join(self._tmp, 'media')
        )
        self._media_override.enable()
        self.addCleanup(self._media_override.disable)

    def test_streams_progress_with_bytes_and_done(self):
        sftp = FakeSftp({
            '/r/x.csv': b'x' * 10,
            '/r/y.csv': b'y' * 20,
        })
        file_list = [
            ('/r/x.csv', 'x.csv', 10, 0),
            ('/r/y.csv', 'y.csv', 20, 0),
        ]
        # 注意：patch 类方法后 MagicMock 不做描述符绑定，side_effect 只收到
        # 实例调用时的实参（self 不自动传入）——lambda 5 参而非 6 参
        with mock.patch.object(SftpViewSet, '_get_connection', return_value=sftp), \
                mock.patch.object(
                    SftpViewSet, '_collect_files',
                    side_effect=lambda _s, _p, result, _r, _o: result.extend(file_list)):
            resp = self.client.post(
                '/api/v1/sftp/download_dir/',
                {'path': '/r', 'timeout': 60}, format='json')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/event-stream')
        raw = b''.join(resp.streaming_content)
        self.assertIn(b'"event": "progress"', raw)
        self.assertIn(b'"bytes_done"', raw)
        self.assertIn(b'"total_bytes"', raw)
        self.assertIn(b'"event": "done"', raw)
        # 下载即注册（batch）
        self.assertEqual(
            DataFile.objects.filter(owner=self.user, file_type='batch').count(), 2)

    def test_not_connected_returns_400(self):
        with mock.patch.object(SftpViewSet, '_get_connection', return_value=None):
            resp = self.client.post(
                '/api/v1/sftp/download_dir/', {'path': '/r'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data['error'], 'not_connected')

    def test_empty_dir_returns_400(self):
        with mock.patch.object(SftpViewSet, '_get_connection',
                               return_value=FakeSftp({})), \
                mock.patch.object(
                    SftpViewSet, '_collect_files',
                    side_effect=lambda _s, _p, _r, _rp, _o: None):
            resp = self.client.post(
                '/api/v1/sftp/download_dir/', {'path': '/r'}, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('目录为空', resp.data['error'])
