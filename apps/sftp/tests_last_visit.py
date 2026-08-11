"""SFTP 断线续连（last_visit / auto_connect）后端测试。

记录模型：``UserSetting.sftp_last_*``（apps.accounts.models），由 SftpViewSet 直接
ORM 读写（不在 UserSettingSerializer 白名单内，settings 页不受影响）。

mock 模式与 tests.py 一致：connect/auto_connect 握手用
``mock.patch('apps.sftp.views.paramiko.Transport', ctor)``；list_files 用 pool
三段式 patch（Transport / SFTPClient / pool.get_session）。
"""

from unittest import mock

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.accounts.models import UserSetting
from apps.sftp import cache as sftp_cache
from apps.sftp import pool

User = get_user_model()


def _fake_sftp():
    sftp = mock.MagicMock(name='SFTPClient')
    sftp.listdir_attr.return_value = []
    return sftp


class LastVisitRecordTests(APITestCase):
    """list_files / connect 对 UserSetting 的记录行为。"""

    def setUp(self):
        self.user = User.objects.create_user(username='lastvisit', password='pw')
        self.client.force_authenticate(self.user)
        for uid in list(pool._pool.keys()):
            pool._pool.pop(uid, None)

    def tearDown(self):
        for uid in list(pool._pool.keys()):
            pool._pool.pop(uid, None)

    def _patch_pool(self):
        """Standard pool patch trio → (context manager, fake_sftp)."""
        sftp = _fake_sftp()
        transport = mock.MagicMock()
        transport.is_active.return_value = True
        ctor = mock.MagicMock(return_value=transport)
        session = {'host': 'h', 'port': 22, 'username': 'u', 'password': 'p'}
        cm = [
            mock.patch.object(pool.paramiko, 'Transport', ctor),
            mock.patch.object(pool.paramiko, 'SFTPClient'),
            mock.patch.object(pool, 'get_session', return_value=session),
        ]
        return cm, sftp

    def _record(self, **kwargs):
        """Directly set a UserSetting field (test precondition)."""
        s = UserSetting.objects.get_or_create(user=self.user)[0]
        for k, v in kwargs.items():
            setattr(s, k, v)
        s.save()
        return s

    def test_list_files_records_last_path(self):
        cm, sftp = self._patch_pool()
        with cm[0], cm[1] as sftp_cls, cm[2]:
            sftp_cls.from_transport.return_value = sftp
            r1 = self.client.get('/api/v1/sftp/list_files/?path=/sub')
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(UserSetting.objects.get(user=self.user).sftp_last_path, '/sub')

            r2 = self.client.get('/api/v1/sftp/list_files/?path=/sub/deep')
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(UserSetting.objects.get(user=self.user).sftp_last_path, '/sub/deep')

    def test_list_files_failure_does_not_record(self):
        self._record(sftp_last_path='/old')
        cm, sftp = self._patch_pool()
        sftp.listdir_attr.side_effect = Exception('boom')
        with cm[0], cm[1] as sftp_cls, cm[2]:
            sftp_cls.from_transport.return_value = sftp
            r = self.client.get('/api/v1/sftp/list_files/?path=/new')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(UserSetting.objects.get(user=self.user).sftp_last_path, '/old')

    def test_manual_connect_records_credentials_and_clears_config(self):
        self._record(sftp_last_config='stale-config')
        transport = mock.MagicMock()
        ctor = mock.MagicMock(return_value=transport)
        with mock.patch('apps.sftp.views.paramiko.Transport', ctor):
            r = self.client.post('/api/v1/sftp/connect/', {
                'host': '10.0.0.1', 'port': 2222, 'username': 'alice', 'password': 'secret',
            })
        self.assertEqual(r.status_code, 200)
        s = UserSetting.objects.get(user=self.user)
        self.assertEqual(s.sftp_last_host, '10.0.0.1')
        self.assertEqual(s.sftp_last_port, 2222)
        self.assertEqual(s.sftp_last_username, 'alice')
        self.assertEqual(s.sftp_last_config, '')
        self.assertEqual(s.sftp_last_path, '/')

    def test_config_connect_records_config_name(self):
        self.client.post('/api/v1/sftp/save_config/', {
            'name': 'prod', 'host': '10.0.0.1', 'port': 22,
            'username': 'alice', 'password': 'secret',
        })
        transport = mock.MagicMock()
        ctor = mock.MagicMock(return_value=transport)
        with mock.patch('apps.sftp.views.paramiko.Transport', ctor):
            r = self.client.post('/api/v1/sftp/connect/', {'config_name': 'prod'})
        self.assertEqual(r.status_code, 200)
        s = UserSetting.objects.get(user=self.user)
        self.assertEqual(s.sftp_last_config, 'prod')
        self.assertEqual(s.sftp_last_host, '10.0.0.1')
        self.assertEqual(s.sftp_last_username, 'alice')

    def _connect_via_config(self):
        """Precondition helper: save config 'prod' and connect through it."""
        self.client.post('/api/v1/sftp/save_config/', {
            'name': 'prod', 'host': '10.0.0.1', 'port': 22,
            'username': 'alice', 'password': 'secret',
        })
        transport = mock.MagicMock()
        ctor = mock.MagicMock(return_value=transport)
        with mock.patch('apps.sftp.views.paramiko.Transport', ctor):
            r = self.client.post('/api/v1/sftp/connect/', {'config_name': 'prod'})
        self.assertEqual(r.status_code, 200)


class LastVisitApiTests(APITestCase):
    """GET /sftp/last_visit/ 契约。"""

    def setUp(self):
        self.user = User.objects.create_user(username='lastvisitapi', password='pw')
        self.client.force_authenticate(self.user)

    def test_last_visit_new_user_defaults(self):
        r = self.client.get('/api/v1/sftp/last_visit/')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertFalse(d['can_auto_connect'])
        self.assertEqual(d['config_name'], '')
        self.assertEqual(d['host'], '')
        self.assertEqual(d['port'], 22)
        self.assertEqual(d['username'], '')
        self.assertEqual(d['last_path'], '/')

    def test_last_visit_auto_connectable_after_config_connect(self):
        LastVisitRecordTests._connect_via_config(self)
        r = self.client.get('/api/v1/sftp/last_visit/')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d['can_auto_connect'])
        self.assertEqual(d['config_name'], 'prod')
        self.assertEqual(d['host'], '10.0.0.1')

    def test_last_visit_config_deleted_falls_back_to_prefill(self):
        LastVisitRecordTests._connect_via_config(self)
        self.client.post('/api/v1/sftp/delete_config/', {'name': 'prod'})
        r = self.client.get('/api/v1/sftp/last_visit/')
        d = r.json()
        self.assertFalse(d['can_auto_connect'])
        # 凭据信息仍返回，供前端预填表单
        self.assertEqual(d['config_name'], 'prod')
        self.assertEqual(d['host'], '10.0.0.1')
        self.assertEqual(d['username'], 'alice')

    def test_last_visit_never_exposes_password(self):
        LastVisitRecordTests._connect_via_config(self)
        r = self.client.get('/api/v1/sftp/last_visit/')
        d = r.json()
        self.assertNotIn('password', d)
        self.assertNotIn('password_encrypted', d)

    def test_manual_connect_then_auto_connect_returns_400(self):
        transport = mock.MagicMock()
        ctor = mock.MagicMock(return_value=transport)
        with mock.patch('apps.sftp.views.paramiko.Transport', ctor):
            self.client.post('/api/v1/sftp/connect/', {
                'host': '10.0.0.1', 'port': 22, 'username': 'alice', 'password': 'secret',
            })
        r = self.client.post('/api/v1/sftp/auto_connect/', {})
        self.assertEqual(r.status_code, 400)
        self.assertIn('未保存配置', r.json()['message'])


class AutoConnectApiTests(APITestCase):
    """POST /sftp/auto_connect/ 契约。"""

    def setUp(self):
        self.user = User.objects.create_user(username='autoconnect', password='pw')
        self.client.force_authenticate(self.user)

    def test_auto_connect_restores_session(self):
        LastVisitRecordTests._connect_via_config(self)
        # 模拟重新登录：清掉会话缓存与连接池
        sftp_cache.delete_session(self.user.id)
        pool.close(self.user.id)
        self.assertIsNone(sftp_cache.get_session(self.user.id))

        transport = mock.MagicMock()
        ctor = mock.MagicMock(return_value=transport)
        with mock.patch('apps.sftp.views.paramiko.Transport', ctor):
            r = self.client.post('/api/v1/sftp/auto_connect/', {})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'connected')
        self.assertEqual(r.json()['host'], '10.0.0.1')

        sess = sftp_cache.get_session(self.user.id)
        self.assertIsNotNone(sess)
        self.assertEqual(sess['host'], '10.0.0.1')
        self.assertEqual(sess['username'], 'alice')
        self.assertEqual(sess['password'], 'secret')

    def test_auto_connect_config_deleted_returns_400(self):
        LastVisitRecordTests._connect_via_config(self)
        self.client.post('/api/v1/sftp/delete_config/', {'name': 'prod'})
        r = self.client.post('/api/v1/sftp/auto_connect/', {})
        self.assertEqual(r.status_code, 400)
        self.assertIn('配置', r.json()['message'])

    def test_auto_connect_handshake_failure_returns_400_no_session(self):
        LastVisitRecordTests._connect_via_config(self)
        # 模拟重新登录：清掉旧会话，验证握手失败不会重建会话
        sftp_cache.delete_session(self.user.id)
        pool.close(self.user.id)
        transport = mock.MagicMock()
        transport.connect.side_effect = Exception('auth failed')
        ctor = mock.MagicMock(return_value=transport)
        with mock.patch('apps.sftp.views.paramiko.Transport', ctor):
            r = self.client.post('/api/v1/sftp/auto_connect/', {})
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(sftp_cache.get_session(self.user.id))

    def test_auto_connect_with_explicit_config_name(self):
        LastVisitRecordTests._connect_via_config(self)
        self.client.post('/api/v1/sftp/save_config/', {
            'name': 'prod2', 'host': '10.0.0.2', 'port': 22,
            'username': 'bob', 'password': 'other',
        })
        transport = mock.MagicMock()
        ctor = mock.MagicMock(return_value=transport)
        with mock.patch('apps.sftp.views.paramiko.Transport', ctor):
            r = self.client.post('/api/v1/sftp/auto_connect/', {'config_name': 'prod2'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['host'], '10.0.0.2')
        sess = sftp_cache.get_session(self.user.id)
        self.assertEqual(sess['username'], 'bob')
