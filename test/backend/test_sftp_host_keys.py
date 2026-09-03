"""SFTP 主机密钥 TOFU 校验回归测试（缺陷 #13）。

``apps/sftp/views.py`` 与 ``apps/sftp/pool.py`` 原本都是
``paramiko.Transport((host, port))`` 之后直接 ``transport.connect(username=...,
password=...)`` —— 等价于无条件接受任意主机公钥，中间人可冒充服务器窃取明文凭据。

修复方案：TOFU（trust-on-first-use）——首次连接把主机公钥记入**用户数据目录**下的
``known_hosts`` 文件（``MEDIA_ROOT/sftp/known_hosts.json``，无需 model 迁移），
后续连接把已记录的公钥作为 ``hostkey`` 交给 paramiko：paramiko 的
``Transport.connect`` 在 ``auth_password`` **之前**比对公钥，不匹配即抛异常，
凭据不会发往可疑主机。

runner: ``manage.py test test.backend.test_sftp_host_keys``
"""

import os
import shutil
import tempfile
from unittest import mock

import paramiko
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from apps.sftp import cache as sftp_cache
from apps.sftp import host_keys
from apps.sftp import pool

User = get_user_model()


def _ed25519(fill_byte):
    """构造一把确定性的 Ed25519 公钥（免生成 RSA，测试快）。"""
    msg = paramiko.Message()
    msg.add_string('ssh-ed25519')
    msg.add_string(bytes([fill_byte]) * 32)
    return paramiko.Ed25519Key(data=msg.asbytes())


KEY_A = _ed25519(0x01)
KEY_B = _ed25519(0x02)


class FakeTransport:
    """模仿 paramiko.Transport.connect 的「先校验主机密钥、后认证」语义。"""

    def __init__(self, presented_key):
        self.presented = presented_key
        self.hostkey_arg = 'unset'
        self.authed = False
        self.closed = False

    def connect(self, hostkey=None, username='', password=None, pkey=None):
        self.hostkey_arg = hostkey
        if hostkey is not None and hostkey.asbytes() != self.presented.asbytes():
            raise paramiko.SSHException('Bad host key from server')
        self.authed = True

    def get_remote_server_key(self):
        return self.presented

    def close(self):
        self.closed = True


class _HostKeyBase(SimpleTestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='sftp_hostkey_')
        self.addCleanup(lambda: shutil.rmtree(self._tmp, ignore_errors=True))
        override = override_settings(MEDIA_ROOT=os.path.join(self._tmp, 'media'))
        override.enable()
        self.addCleanup(override.disable)

    def _patch_transport(self, presented_key):
        fake = FakeTransport(presented_key)
        ctor = mock.MagicMock(side_effect=lambda addr: fake)
        patcher = mock.patch.object(host_keys.paramiko, 'Transport', ctor)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake


class KnownHostsStoreTests(_HostKeyBase):
    def test_unknown_host_lookup_returns_none(self):
        self.assertIsNone(host_keys.lookup('nope.example', 22))
        self.assertIsNone(host_keys.lookup_fingerprint('nope.example', 22))

    def test_pin_writes_known_hosts_under_media_root(self):
        self.assertTrue(host_keys.pin('h1', 22, KEY_A))
        path = host_keys.known_hosts_path()
        self.assertTrue(path.startswith(self._tmp), f'必须落在用户数据目录: {path}')
        self.assertTrue(os.path.exists(path))
        self.assertEqual(host_keys.lookup_fingerprint('h1', 22),
                         host_keys.fingerprint(KEY_A))

    def test_lookup_reconstructs_equivalent_key(self):
        host_keys.pin('h2', 2222, KEY_A)
        pinned = host_keys.lookup('h2', 2222)
        self.assertIsNotNone(pinned)
        self.assertEqual(pinned.asbytes(), KEY_A.asbytes())
        self.assertEqual(pinned.get_name(), KEY_A.get_name())

    def test_ports_are_distinct_entries(self):
        host_keys.pin('h3', 22, KEY_A)
        host_keys.pin('h3', 2222, KEY_B)
        self.assertEqual(host_keys.lookup('h3', 22).asbytes(), KEY_A.asbytes())
        self.assertEqual(host_keys.lookup('h3', 2222).asbytes(), KEY_B.asbytes())

    def test_forget_removes_entry(self):
        host_keys.pin('h4', 22, KEY_A)
        self.assertTrue(host_keys.forget('h4', 22))
        self.assertIsNone(host_keys.lookup('h4', 22))
        self.assertFalse(host_keys.forget('h4', 22))

    def test_unpinnable_key_returns_false(self):
        """测试替身 / 异常公钥：无法计算指纹时不得写库、不得抛。"""
        self.assertFalse(host_keys.pin('h5', 22, mock.MagicMock()))
        self.assertIsNone(host_keys.lookup('h5', 22))


class OpenVerifiedTransportTests(_HostKeyBase):
    def test_first_use_connects_and_pins(self):
        fake = self._patch_transport(KEY_A)
        transport = host_keys.open_verified_transport('h', 22, 'u', 'p')
        self.assertIs(transport, fake)
        self.assertIsNone(fake.hostkey_arg, '首次连接没有可校验的记录')
        self.assertTrue(fake.authed)
        self.assertEqual(host_keys.lookup_fingerprint('h', 22),
                         host_keys.fingerprint(KEY_A))

    def test_second_use_passes_pinned_hostkey(self):
        host_keys.pin('h', 22, KEY_A)
        fake = self._patch_transport(KEY_A)
        host_keys.open_verified_transport('h', 22, 'u', 'p')
        self.assertIsNotNone(fake.hostkey_arg, '已记录的主机必须带 hostkey 校验')
        self.assertEqual(fake.hostkey_arg.asbytes(), KEY_A.asbytes())
        self.assertTrue(fake.authed)

    def test_mismatch_refuses_and_credentials_are_not_sent(self):
        """核心安全属性：公钥不匹配 → 拒绝连接且**未认证**（凭据不外泄）。"""
        host_keys.pin('h', 22, KEY_A)
        fake = self._patch_transport(KEY_B)
        with self.assertRaises(host_keys.HostKeyMismatchError) as ctx:
            host_keys.open_verified_transport('h', 22, 'u', 'p')
        self.assertFalse(fake.authed, '主机密钥不匹配时不得发送凭据')
        message = str(ctx.exception)
        self.assertIn('h', message)
        self.assertIn(host_keys.fingerprint(KEY_A), message,
                      '错误信息应给出已信任指纹，便于运维比对')

    def test_mismatch_does_not_overwrite_pinned_key(self):
        host_keys.pin('h', 22, KEY_A)
        self._patch_transport(KEY_B)
        with self.assertRaises(host_keys.HostKeyMismatchError):
            host_keys.open_verified_transport('h', 22, 'u', 'p')
        self.assertEqual(host_keys.lookup_fingerprint('h', 22),
                         host_keys.fingerprint(KEY_A))

    def test_auth_failure_is_not_reported_as_host_key_error(self):
        host_keys.pin('h', 22, KEY_A)
        fake = self._patch_transport(KEY_A)
        fake.connect = mock.Mock(
            side_effect=paramiko.AuthenticationException('Authentication failed.'))
        with self.assertRaises(paramiko.AuthenticationException):
            host_keys.open_verified_transport('h', 22, 'u', 'wrong')

    def test_unpinnable_key_does_not_block_connect(self):
        """替身/异常公钥（无法计算指纹）→ 保持既有连接流程可用。"""
        fake = self._patch_transport(mock.MagicMock())
        transport = host_keys.open_verified_transport('h', 22, 'u', 'p')
        self.assertIs(transport, fake)
        self.assertTrue(fake.authed)
        self.assertIsNone(host_keys.lookup('h', 22))

    def test_check_mode_off_skips_verification(self):
        """逃生开关：``SFTP_HOST_KEY_CHECK='off'`` 回到旧行为（不记录、不校验）。"""
        host_keys.pin('h', 22, KEY_A)
        fake = self._patch_transport(KEY_B)
        with override_settings(SFTP_HOST_KEY_CHECK='off'):
            transport = host_keys.open_verified_transport('h', 22, 'u', 'p')
        self.assertIs(transport, fake)
        self.assertIsNone(fake.hostkey_arg)
        self.assertTrue(fake.authed)


class PoolHostKeyTests(_HostKeyBase):
    def setUp(self):
        super().setUp()
        for uid in list(pool._pool.keys()):
            pool._pool.pop(uid, None)
        self.addCleanup(lambda: [pool._pool.pop(u, None) for u in list(pool._pool)])

    def test_pool_rebuild_raises_on_mismatch(self):
        host_keys.pin('h', 22, KEY_A)
        self._patch_transport(KEY_B)
        sftp_patcher = mock.patch.object(pool.paramiko, 'SFTPClient')
        sftp_patcher.start()
        self.addCleanup(sftp_patcher.stop)
        session = {'host': 'h', 'port': 22, 'username': 'u', 'password': 'p'}
        with mock.patch.object(pool, 'get_session', return_value=session):
            with self.assertRaises(pool.SftpPoolError) as ctx:
                pool.get_connection(1)
        self.assertIn('主机密钥', str(ctx.exception))

    def test_pool_rebuild_pins_on_first_use(self):
        fake = self._patch_transport(KEY_A)
        sftp_patcher = mock.patch.object(pool.paramiko, 'SFTPClient')
        sftp_cls = sftp_patcher.start()
        self.addCleanup(sftp_patcher.stop)
        session = {'host': 'poolh', 'port': 22, 'username': 'u', 'password': 'p'}
        with mock.patch.object(pool, 'get_session', return_value=session):
            pool.get_connection(7)
        self.assertTrue(fake.authed)
        self.assertEqual(host_keys.lookup_fingerprint('poolh', 22),
                         host_keys.fingerprint(KEY_A))


class ConnectEndpointHostKeyTests(APITestCase):
    """POST /sftp/connect/ 在主机密钥不匹配时给出可读 400，且不缓存会话。"""

    def setUp(self):
        self.user = User.objects.create_user(username='hk_user', password='pw')
        self.client.force_authenticate(self.user)
        self._tmp = tempfile.mkdtemp(prefix='sftp_hostkey_api_')
        self.addCleanup(lambda: shutil.rmtree(self._tmp, ignore_errors=True))
        override = override_settings(MEDIA_ROOT=os.path.join(self._tmp, 'media'))
        override.enable()
        self.addCleanup(override.disable)
        sftp_cache.delete_session(self.user.id)

    def test_connect_mismatch_returns_400_without_session(self):
        host_keys.pin('10.0.0.9', 22, KEY_A)
        fake = FakeTransport(KEY_B)
        ctor = mock.MagicMock(side_effect=lambda addr: fake)
        with mock.patch.object(host_keys.paramiko, 'Transport', ctor):
            resp = self.client.post('/api/v1/sftp/connect/', {
                'host': '10.0.0.9', 'port': 22,
                'username': 'alice', 'password': 'secret',
            }, format='json')
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp))
        self.assertIn('主机密钥', resp.json()['message'])
        self.assertFalse(fake.authed)
        self.assertIsNone(sftp_cache.get_session(self.user.id))

    def test_connect_first_use_still_succeeds(self):
        fake = FakeTransport(KEY_A)
        ctor = mock.MagicMock(side_effect=lambda addr: fake)
        with mock.patch.object(host_keys.paramiko, 'Transport', ctor):
            resp = self.client.post('/api/v1/sftp/connect/', {
                'host': '10.0.0.10', 'port': 22,
                'username': 'alice', 'password': 'secret',
            }, format='json')
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        self.assertEqual(resp.json()['status'], 'connected')
        self.assertIsNotNone(sftp_cache.get_session(self.user.id))
        self.assertIsNotNone(host_keys.lookup('10.0.0.10', 22))
