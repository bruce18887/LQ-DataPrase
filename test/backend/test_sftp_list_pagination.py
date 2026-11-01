"""B1：SFTP 目录列表的载荷封顶（limit/offset + total/truncated）。

判据只钉新契约，不复刻排序实现：**先排序再切片**是这页分页能用的前提，所以每页必须
是同一有序序列的连续片段（两页拼起来无重无漏），而不是「每页各自排序后取前 N」。

mock 口径与 ``apps/sftp/tests.py`` 的 list_files 用例一致：pool 三段式 patch。
runner: ``python -X utf8 manage.py test test.backend.test_sftp_list_pagination``
"""
from unittest import mock

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.sftp import pool

User = get_user_model()

URL = '/api/v1/sftp/list_files/'


def _entry(name, is_dir=False, size=0, mtime=0):
    entry = mock.MagicMock()
    entry.filename = name
    entry.st_mode = 0o40755 if is_dir else 0o100644
    entry.st_size = size
    entry.st_mtime = mtime
    return entry


class SftpListPaginationTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='pager', password='pw')
        self.client.force_authenticate(self.user)
        for uid in list(pool._pool.keys()):
            pool._pool.pop(uid, None)

    def tearDown(self):
        for uid in list(pool._pool.keys()):
            pool._pool.pop(uid, None)

    def _get(self, entries, query=''):
        sftp = mock.MagicMock(name='SFTPClient')
        sftp.listdir_attr.return_value = entries
        transport = mock.MagicMock()
        transport.is_active.return_value = True
        session = {'host': 'h', 'port': 22, 'username': 'u', 'password': 'p'}
        with mock.patch.object(pool.paramiko, 'Transport', mock.MagicMock(return_value=transport)), \
                mock.patch.object(pool.paramiko, 'SFTPClient') as sftp_cls, \
                mock.patch.object(pool, 'get_session', return_value=session):
            sftp_cls.from_transport.return_value = sftp
            return self.client.get(URL + query)

    def test_default_caps_at_500_and_flags_truncation(self):
        entries = [_entry(f'f{i:04d}.csv') for i in range(600)]
        resp = self._get(entries, '?path=/big')
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(len(body['items']), 500)
        self.assertEqual(body['total'], 600)
        self.assertIs(body['truncated'], True)
        self.assertEqual([it['name'] for it in body['items']],
                         [f'f{i:04d}.csv' for i in range(500)])

    def test_offset_returns_the_tail_and_clears_the_flag(self):
        entries = [_entry(f'f{i:04d}.csv') for i in range(600)]
        body = self._get(entries, '?path=/big&offset=500').json()
        self.assertEqual(len(body['items']), 100)
        self.assertEqual(body['total'], 600)
        self.assertIs(body['truncated'], False)
        self.assertEqual(body['items'][0]['name'], 'f0500.csv')

    def test_pages_are_contiguous_slices_of_one_sorted_sequence(self):
        """目录排在文件前、名字升序；offset=1 的那页必须从第 2 项接上，不是重新排序。"""
        entries = [_entry('b.csv'), _entry('a.csv'), _entry('zdir', is_dir=True)]
        first = self._get(entries, '?path=/&limit=2').json()
        second = self._get(entries, '?path=/&limit=2&offset=2').json()
        self.assertEqual([it['name'] for it in first['items']], ['zdir', 'a.csv'])
        self.assertEqual([it['name'] for it in second['items']], ['b.csv'])
        self.assertIs(first['truncated'], True)
        self.assertIs(second['truncated'], False)

    def test_explicit_limit_is_honoured(self):
        entries = [_entry(f'f{i:02d}.csv') for i in range(30)]
        body = self._get(entries, '?path=/&limit=10&offset=5').json()
        self.assertEqual([it['name'] for it in body['items']],
                         [f'f{i:02d}.csv' for i in range(5, 15)])
        self.assertEqual(body['total'], 30)
        self.assertIs(body['truncated'], True)

    def test_empty_directory_reports_totals_without_items(self):
        body = self._get([], '?path=/empty').json()
        self.assertEqual(body['items'], [])
        self.assertEqual(body['total'], 0)
        self.assertIs(body['truncated'], False)

    def test_bad_pagination_parameters_are_client_errors(self):
        entries = [_entry('a.csv')]
        for query in ('?path=/&limit=abc', '?path=/&limit=0', '?path=/&limit=-3',
                      '?path=/&offset=-1', '?path=/&offset=x'):
            with self.subTest(query=query):
                resp = self._get(entries, query)
                self.assertEqual(resp.status_code, 400, f'{query} 应判 400')
                self.assertIn('code', resp.json())

    def test_bad_pagination_does_not_open_a_connection_or_record_last_visit(self):
        """参数校验在握手之前：坏请求不该换来一次建连，也不该把上次路径写掉。"""
        from apps.accounts.models import UserSetting

        transport = mock.MagicMock()
        transport.is_active.return_value = True
        get_session = mock.MagicMock(
            return_value={'host': 'h', 'port': 22, 'username': 'u', 'password': 'p'})
        with mock.patch.object(pool.paramiko, 'Transport', mock.MagicMock(return_value=transport)), \
                mock.patch.object(pool.paramiko, 'SFTPClient'), \
                mock.patch.object(pool, 'get_session', get_session):
            resp = self.client.get(URL + '?path=/deep&limit=abc')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(get_session.call_count, 0, '坏参数也去建连了')
        setting = UserSetting.objects.filter(user=self.user).first()
        self.assertTrue(setting is None or setting.sftp_last_path == '',
                        '坏参数也写了 last_visit')
