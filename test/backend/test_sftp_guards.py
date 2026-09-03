"""SFTP 视图守卫 / 半截文件清理 / 重名碰撞 / 静默吞异常 回归测试。

覆盖缺陷清单：
- #9 ``download`` / ``download_file_stream``（及同族的 ``download_dir``）先取
  ``request.data.get('path')``（可能是 None）再调 ``_is_csv``，
  ``os.path.splitext(None)`` → TypeError → 500；同文件的 ``download_and_parse``
  已有真值守卫，守卫不对齐。
- #10 ``sftp.get`` 失败时半截本地文件从不清理（SSE 路径 ``downloads.py`` 一律
  ``_remove_partial``），留下未注册孤儿文件。
- #11 ``_batch_download_parse`` 用裸 ``except:``（吞 KeyboardInterrupt）且无重名
  处理（其它下载端点都加时间戳后缀）→ 覆盖既有文件 + 注册重复 DB 行。
- #12 多处 ``except Exception: pass/continue`` 无日志。

runner: ``manage.py test test.backend.test_sftp_guards``
"""

import os
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.datafiles.models import DataFile
from apps.sftp.views import SftpViewSet

User = get_user_model()


def _ok_sftp(content='a,b\n1,2\n'):
    """sftp.get 正常落盘的替身。"""
    def fake_get(remote_path, local_path):
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, 'w', encoding='utf-8') as fh:
            fh.write(content)

    sftp = mock.MagicMock(name='SFTPClient')
    sftp.get.side_effect = fake_get
    sftp.listdir_attr.return_value = []
    return sftp


def _half_written_sftp(partial='a,b\n', error=None):
    """sftp.get 先写半截文件再抛异常（真实断流形态）。"""
    calls = []

    def fake_get(remote_path, local_path):
        calls.append(local_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, 'w', encoding='utf-8') as fh:
            fh.write(partial)
        raise (error or OSError('connection reset by peer'))

    sftp = mock.MagicMock(name='SFTPClient')
    sftp.get.side_effect = fake_get
    sftp.listdir_attr.return_value = []
    sftp._calls = calls
    return sftp


class _SftpApiBase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='sftp_guard', password='pw')
        self.client.force_authenticate(self.user)
        self._tmp = tempfile.mkdtemp(prefix='sftp_guard_test_')
        self.addCleanup(lambda: shutil.rmtree(self._tmp, ignore_errors=True))
        media = override_settings(MEDIA_ROOT=os.path.join(self._tmp, 'media'))
        media.enable()
        self.addCleanup(media.disable)

    def _with_connection(self, sftp):
        patcher = mock.patch.object(
            SftpViewSet, '_get_connection', return_value=sftp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _single_dir(self):
        return os.path.join(self._tmp, 'media', 'data', self.user.username, 'single')

    def _batch_dir(self, batch_name):
        return os.path.join(
            self._tmp, 'media', 'data', self.user.username, 'batch', batch_name)


class PathNoneGuardTests(_SftpApiBase):
    """缺陷 #9：path 为 None / 缺失时必须 400，不得 TypeError → 500。"""

    def test_download_path_none_returns_400(self):
        self._with_connection(_ok_sftp())
        resp = self.client.post('/api/v1/sftp/download/', {'path': None},
                                format='json')
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))
        self.assertIn('path', str(resp.data))

    def test_download_path_missing_returns_400(self):
        self._with_connection(_ok_sftp())
        resp = self.client.post('/api/v1/sftp/download/', {}, format='json')
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))

    def test_download_file_stream_path_none_returns_400(self):
        self._with_connection(_ok_sftp())
        resp = self.client.post('/api/v1/sftp/download_file_stream/',
                                {'path': None}, format='json')
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))
        self.assertIn('path', str(resp.data))

    def test_download_dir_path_none_returns_400(self):
        """同族端点：``None.rstrip('/')`` 也会 AttributeError → 500。"""
        self._with_connection(_ok_sftp())
        resp = self.client.post('/api/v1/sftp/download_dir/', {'path': None},
                                format='json')
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))

    def test_download_and_parse_already_guards(self):
        """对照：download_and_parse 早已用 ``elif remote_path:`` 做了真值守卫。"""
        self._with_connection(_ok_sftp())
        resp = self.client.post('/api/v1/sftp/download_and_parse/', {},
                                format='json')
        self.assertEqual(resp.status_code, 400)

    def test_download_non_csv_still_400(self):
        """正向对照：既有的「仅支持 CSV」语义不变。"""
        self._with_connection(_ok_sftp())
        resp = self.client.post('/api/v1/sftp/download/', {'path': '/r/a.txt'},
                                format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('CSV', str(resp.data))


class PartialFileCleanupTests(_SftpApiBase):
    """缺陷 #10：下载失败后不得留下未注册的半截文件。"""

    def test_download_failure_removes_partial(self):
        sftp = _half_written_sftp()
        self._with_connection(sftp)
        resp = self.client.post('/api/v1/sftp/download/', {'path': '/r/x.csv'},
                                format='json')
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))
        self.assertTrue(sftp._calls, '替身应已尝试落盘')
        for path in sftp._calls:
            self.assertFalse(os.path.exists(path), f'半截文件未清理: {path}')
        self.assertEqual(DataFile.objects.count(), 0)

    def test_download_and_parse_single_failure_removes_partial(self):
        sftp = _half_written_sftp()
        self._with_connection(sftp)
        resp = self.client.post('/api/v1/sftp/download_and_parse/',
                                {'path': '/r/x.csv'}, format='json')
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))
        for path in sftp._calls:
            self.assertFalse(os.path.exists(path), f'半截文件未清理: {path}')
        self.assertEqual(DataFile.objects.count(), 0)

    def test_download_batch_failure_removes_partial_only_for_failed(self):
        """批量：失败的那个文件清理，成功的保留并注册。"""
        sftp = _ok_sftp()
        real_get = sftp.get.side_effect

        def mixed_get(remote_path, local_path):
            if remote_path.endswith('bad.csv'):
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, 'w', encoding='utf-8') as fh:
                    fh.write('partial')
                sftp._calls.append(local_path)
                raise OSError('boom')
            real_get(remote_path, local_path)

        sftp._calls = []
        sftp.get.side_effect = mixed_get
        self._with_connection(sftp)

        resp = self.client.post('/api/v1/sftp/download_batch/',
                                {'paths': ['/r/bad.csv', '/r/good.csv']},
                                format='json')
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        self.assertEqual(resp.data['count'], 1)
        for path in sftp._calls:
            self.assertFalse(os.path.exists(path), f'半截文件未清理: {path}')
        self.assertEqual(
            list(DataFile.objects.values_list('filename', flat=True)),
            ['good.csv'])

    def test_batch_download_parse_failure_removes_partial(self):
        sftp = _half_written_sftp()
        self._with_connection(sftp)
        resp = self.client.post('/api/v1/sftp/download_and_parse/',
                                {'paths': ['/r/x.csv', '/r/y.csv']},
                                format='json')
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        self.assertEqual(resp.data['files'], [])
        for path in sftp._calls:
            self.assertFalse(os.path.exists(path), f'半截文件未清理: {path}')
        self.assertEqual(DataFile.objects.count(), 0)


class BatchParseCollisionTests(_SftpApiBase):
    """缺陷 #11：``_batch_download_parse`` 重名覆盖 + 裸 except。"""

    def test_same_basename_is_not_overwritten(self):
        sftp = _ok_sftp()
        self._with_connection(sftp)
        resp = self.client.post('/api/v1/sftp/download_and_parse/',
                                {'paths': ['/a/dup.csv', '/b/dup.csv']},
                                format='json')
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        rows = DataFile.objects.filter(owner=self.user).order_by('id')
        self.assertEqual(rows.count(), 2)
        paths = [r.file_path for r in rows]
        self.assertEqual(len(set(paths)), 2, f'两行不得指向同一路径: {paths}')
        names = [os.path.basename(p) for p in paths]
        self.assertEqual(len(set(names)), 2, f'重名文件不得互相覆盖: {names}')

    def test_keyboard_interrupt_is_not_swallowed(self):
        """裸 ``except:`` 会吞掉 KeyboardInterrupt/SystemExit。"""
        sftp = mock.MagicMock(name='SFTPClient')
        sftp.get.side_effect = KeyboardInterrupt()
        self._with_connection(sftp)
        with self.assertRaises(KeyboardInterrupt):
            self.client.post('/api/v1/sftp/download_and_parse/',
                             {'paths': ['/r/x.csv']}, format='json')

    def test_failure_is_logged(self):
        """缺陷 #12：单文件失败不得静默 continue（要有 warning 日志）。"""
        sftp = _half_written_sftp(error=OSError('disk on fire'))
        self._with_connection(sftp)
        with self.assertLogs('apps.sftp.views', level='WARNING') as cm:
            self.client.post('/api/v1/sftp/download_and_parse/',
                             {'paths': ['/r/x.csv']}, format='json')
        self.assertTrue(any('x.csv' in line for line in cm.output), cm.output)


class SilentExceptLoggingTests(_SftpApiBase):
    """缺陷 #12：``except Exception: pass`` 至少要留下 warning 日志。"""

    def test_record_last_visit_failure_is_logged(self):
        sftp = _ok_sftp()
        self._with_connection(sftp)
        patcher = mock.patch.object(
            SftpViewSet, '_record_last_visit',
            side_effect=RuntimeError('db down'))
        patcher.start()
        self.addCleanup(patcher.stop)

        with self.assertLogs('apps.sftp.views', level='WARNING') as cm:
            resp = self.client.get('/api/v1/sftp/list_files/?path=/sub')

        # 控制流不变：记录失败绝不影响浏览
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        self.assertTrue(cm.output)
