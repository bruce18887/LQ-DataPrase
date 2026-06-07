from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache as django_cache
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.sftp import crypto
from apps.sftp import cache as sftp_cache
from apps.sftp.cache import (
    SftpSessionCacheError,
    delete_session,
    get_session,
    set_session,
)
from apps.sftp.models import SftpConfig

User = get_user_model()


def _reset_cache_module_state():
    """Reset module-level Redis singleton so each test starts clean."""
    sftp_cache._redis_client = None
    sftp_cache._redis_unavailable = False


class CryptoRoundTripTests(TestCase):
    def test_encrypt_decrypt_round_trip(self):
        plaintext = 's3cr3t-p@ss'
        token = crypto.encrypt(plaintext)
        self.assertNotEqual(token, plaintext)
        self.assertEqual(crypto.decrypt(token), plaintext)

    def test_empty_string_graceful(self):
        self.assertEqual(crypto.encrypt(''), '')
        self.assertEqual(crypto.decrypt(''), '')

    def test_two_encryptions_both_decrypt(self):
        plaintext = 'same-password'
        t1 = crypto.encrypt(plaintext)
        t2 = crypto.encrypt(plaintext)
        # Fernet embeds a random IV/timestamp, so tokens differ but both decode.
        self.assertNotEqual(t1, t2)
        self.assertEqual(crypto.decrypt(t1), plaintext)
        self.assertEqual(crypto.decrypt(t2), plaintext)


class SftpSessionCacheRedisTests(TestCase):
    """Tests for the Redis-backed session cache path."""

    def setUp(self):
        _reset_cache_module_state()
        # Replace the real redis client with an in-memory fake so we can
        # assert on the bytes that would be written.
        self.fake_redis = {}
        fake_client = mock.MagicMock()
        fake_client.get.side_effect = self.fake_redis.get
        fake_client.set.side_effect = self._fake_set
        fake_client.delete.side_effect = self._fake_delete
        fake_client.ping.return_value = True
        # Patch redis.Redis.from_url to return the fake.
        self._from_url_patch = mock.patch(
            'redis.Redis.from_url', return_value=fake_client
        )
        self._from_url_patch.start()
        self.fake_client = fake_client

    def tearDown(self):
        self._from_url_patch.stop()
        _reset_cache_module_state()

    def _fake_set(self, key, value, ex=None):
        self.fake_redis[key] = value
        return True

    def _fake_delete(self, key):
        self.fake_redis.pop(key, None)
        return True

    def test_password_is_encrypted_at_rest(self):
        set_session(42, 'host.example.com', 22, 'alice', 'plain-pw-123')
        raw = self.fake_redis['sftp:conn:42']
        # The stored value must NOT contain the plaintext password.
        self.assertNotIn('plain-pw-123', raw)
        # It should be a JSON blob with an encrypted ``password`` field.
        import json
        payload = json.loads(raw)
        self.assertEqual(payload['host'], 'host.example.com')
        self.assertEqual(payload['port'], 22)
        self.assertEqual(payload['username'], 'alice')
        # Round-trip back through the same Fernet key.
        self.assertEqual(crypto.decrypt(payload['password']), 'plain-pw-123')

    def test_get_session_decrypts_and_returns(self):
        set_session(7, 'h', 2222, 'bob', 'topsecret')
        sess = get_session(7)
        self.assertEqual(sess, {
            'host': 'h', 'port': 2222, 'username': 'bob', 'password': 'topsecret',
        })

    def test_missing_session_returns_none(self):
        self.assertIsNone(get_session(999))

    def test_delete_session(self):
        set_session(1, 'h', 22, 'u', 'pw')
        self.assertIn('sftp:conn:1', self.fake_redis)
        delete_session(1)
        self.assertNotIn('sftp:conn:1', self.fake_redis)
        # Deleting again is a no-op (no error).
        delete_session(1)

    def test_corrupt_payload_returns_none_and_clears(self):
        # A leftover entry from an older encryption key would fail to decrypt.
        self.fake_redis['sftp:conn:5'] = '{"host":"h","port":22,"username":"u","password":"garbage"}'
        self.assertIsNone(get_session(5))
        # Stale key should be dropped so the next call doesn't keep failing.
        self.assertNotIn('sftp:conn:5', self.fake_redis)


class SftpSessionCacheFallbackTests(TestCase):
    """When Redis is unavailable, the cache falls back to Django's default
    cache backend (LocMemCache in dev)."""

    def setUp(self):
        _reset_cache_module_state()
        # Force Redis to be unavailable (no URL configured).
        self._override = override_settings(
            SFTP_SESSION_REDIS_URL=None, REDIS_URL=None, CELERY_BROKER_URL=None,
        )
        self._override.enable()
        django_cache.clear()

    def tearDown(self):
        self._override.disable()
        _reset_cache_module_state()

    def test_set_and_get_via_django_cache(self):
        set_session(10, 'myhost', 22, 'user', 'secret')
        sess = get_session(10)
        self.assertEqual(sess, {
            'host': 'myhost', 'port': 22, 'username': 'user', 'password': 'secret',
        })

    def test_delete_via_django_cache(self):
        set_session(11, 'h', 22, 'u', 'pw')
        self.assertIsNotNone(get_session(11))
        delete_session(11)
        self.assertIsNone(get_session(11))

    def test_missing_session_returns_none(self):
        self.assertIsNone(get_session(9999))

    def test_password_encrypted_in_django_cache(self):
        set_session(12, 'h', 22, 'u', 'plaintext-pw')
        raw = django_cache.get(sftp_cache._django_key(12))
        self.assertIsNotNone(raw)
        self.assertNotIn('plaintext-pw', raw)


class SftpConfigAuthTests(APITestCase):
    def test_configs_requires_auth(self):
        resp = self.client.get('/api/v1/sftp/configs/')
        self.assertIn(resp.status_code, (401, 403))

    def test_save_config_requires_auth(self):
        resp = self.client.post('/api/v1/sftp/save_config/', {'name': 'x'}, format='json')
        self.assertIn(resp.status_code, (401, 403))


class SftpConfigSaveTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='cfg', password='pw')
        self.client.force_authenticate(self.user)

    def _save(self, **kwargs):
        body = {
            'name': 'prod',
            'host': 'sftp.example.com',
            'port': 2222,
            'username': 'alice',
            'password': 'topsecret',
        }
        body.update(kwargs)
        return self.client.post('/api/v1/sftp/save_config/', body, format='json')

    def test_password_stored_encrypted(self):
        resp = self._save()
        self.assertEqual(resp.status_code, 201)
        cfg = SftpConfig.objects.get(owner=self.user, name='prod')
        self.assertTrue(cfg.password_encrypted)
        self.assertNotEqual(cfg.password_encrypted, 'topsecret')
        self.assertEqual(crypto.decrypt(cfg.password_encrypted), 'topsecret')
        self.assertEqual(cfg.get_password(), 'topsecret')

    def test_response_never_exposes_password(self):
        resp = self._save()
        self.assertNotIn('password', resp.data)
        self.assertNotIn('password_encrypted', resp.data)
        self.assertTrue(resp.data['has_password'])

    def test_configs_list_hides_password(self):
        self._save()
        resp = self.client.get('/api/v1/sftp/configs/')
        self.assertEqual(resp.status_code, 200)
        configs = resp.data['configs']
        self.assertEqual(len(configs), 1)
        self.assertNotIn('password', configs[0])
        self.assertNotIn('password_encrypted', configs[0])
        self.assertTrue(configs[0]['has_password'])

    def test_update_in_place_no_duplicate(self):
        self._save()
        resp = self._save(host='new.example.com')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(SftpConfig.objects.filter(owner=self.user, name='prod').count(), 1)
        cfg = SftpConfig.objects.get(owner=self.user, name='prod')
        self.assertEqual(cfg.host, 'new.example.com')

    def test_update_without_password_keeps_old(self):
        self._save()
        # Update omitting password entirely.
        resp = self.client.post('/api/v1/sftp/save_config/', {
            'name': 'prod', 'host': 'h2', 'port': 22, 'username': 'alice',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        cfg = SftpConfig.objects.get(owner=self.user, name='prod')
        self.assertEqual(cfg.get_password(), 'topsecret')

    def test_port_too_high_rejected(self):
        resp = self._save(port=70000)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('port', resp.data)
        self.assertFalse(SftpConfig.objects.filter(owner=self.user, name='prod').exists())

    def test_port_too_low_rejected(self):
        resp = self._save(port=0)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('port', resp.data)
        self.assertFalse(SftpConfig.objects.filter(owner=self.user, name='prod').exists())

    def test_port_negative_rejected(self):
        resp = self._save(port=-1)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('port', resp.data)
        self.assertFalse(SftpConfig.objects.filter(owner=self.user, name='prod').exists())

    def test_valid_port_saved(self):
        resp = self._save(port=2222)
        self.assertEqual(resp.status_code, 201)
        cfg = SftpConfig.objects.get(owner=self.user, name='prod')
        self.assertEqual(cfg.port, 2222)

    def test_port_omitted_defaults_to_22(self):
        resp = self.client.post('/api/v1/sftp/save_config/', {
            'name': 'noport', 'host': 'h', 'username': 'u', 'password': 'pw',
        }, format='json')
        self.assertEqual(resp.status_code, 201)
        cfg = SftpConfig.objects.get(owner=self.user, name='noport')
        self.assertEqual(cfg.port, 22)

    def test_update_omitting_port_keeps_existing(self):
        self._save(port=2222)
        resp = self.client.post('/api/v1/sftp/save_config/', {
            'name': 'prod', 'host': 'h2', 'username': 'alice',
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        cfg = SftpConfig.objects.get(owner=self.user, name='prod')
        self.assertEqual(cfg.port, 2222)

    def test_delete_config(self):
        self._save()
        resp = self.client.post('/api/v1/sftp/delete_config/', {'name': 'prod'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['deleted'])
        self.assertFalse(SftpConfig.objects.filter(owner=self.user, name='prod').exists())

    def test_delete_missing_returns_404(self):
        resp = self.client.post('/api/v1/sftp/delete_config/', {'name': 'nope'}, format='json')
        self.assertEqual(resp.status_code, 404)


class SftpConfigOwnerIsolationTests(APITestCase):
    def setUp(self):
        self.a = User.objects.create_user(username='alice', password='pw')
        self.b = User.objects.create_user(username='bob', password='pw')

    def _save_as(self, user, **kwargs):
        self.client.force_authenticate(user)
        body = {'name': 'shared', 'host': 'h', 'port': 22, 'username': 'u', 'password': 'pw1'}
        body.update(kwargs)
        return self.client.post('/api/v1/sftp/save_config/', body, format='json')

    def test_b_list_excludes_a_config(self):
        self._save_as(self.a)
        self.client.force_authenticate(self.b)
        resp = self.client.get('/api/v1/sftp/configs/')
        self.assertEqual(resp.data['configs'], [])

    def test_b_save_same_name_creates_separate_row(self):
        self._save_as(self.a, password='a-pass')
        self._save_as(self.b, password='b-pass')
        a_cfg = SftpConfig.objects.get(owner=self.a, name='shared')
        b_cfg = SftpConfig.objects.get(owner=self.b, name='shared')
        self.assertNotEqual(a_cfg.id, b_cfg.id)
        self.assertEqual(a_cfg.get_password(), 'a-pass')
        self.assertEqual(b_cfg.get_password(), 'b-pass')

    def test_b_delete_does_not_touch_a(self):
        self._save_as(self.a)
        self._save_as(self.b)
        self.client.force_authenticate(self.b)
        resp = self.client.post('/api/v1/sftp/delete_config/', {'name': 'shared'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(SftpConfig.objects.filter(owner=self.a, name='shared').exists())
        self.assertFalse(SftpConfig.objects.filter(owner=self.b, name='shared').exists())


class SftpConfigSerializerKwargsTests(TestCase):
    """Regression: ``save(owner=request.user)`` must not 500 the view.

    The view calls ``serializer.save(owner=request.user)`` which forwards the
    keyword to the serializer's ``create``/``update`` methods. If those methods
    don't accept ``**kwargs`` the framework raises
    ``TypeError: create() got an unexpected keyword argument 'owner'`` and the
    API returns 500. See todo.md §1.
    """

    def setUp(self):
        self.user = User.objects.create_user(username='kw', password='pw')

    def test_create_accepts_owner_kwarg(self):
        from apps.sftp.serializers import SftpConfigSerializer
        data = {
            'name': 'kw-create', 'host': 'h1', 'port': 22,
            'username': 'u1', 'password': 'pw1',
        }
        s = SftpConfigSerializer(data=data)
        self.assertTrue(s.is_valid(), s.errors)
        # Must NOT raise TypeError; the kwarg must thread through to owner.
        instance = s.save(owner=self.user)
        self.assertEqual(instance.owner_id, self.user.id)
        self.assertEqual(instance.get_password(), 'pw1')

    def test_update_accepts_owner_kwarg(self):
        from apps.sftp.serializers import SftpConfigSerializer
        cfg = SftpConfig.objects.create(
            owner=self.user, name='kw-update', host='h0', port=22, username='u0',
        )
        cfg.set_password('old')
        cfg.save()
        s = SftpConfigSerializer(
            cfg, data={'name': 'kw-update', 'host': 'h2', 'port': 22, 'username': 'u2'},
            partial=True,
        )
        self.assertTrue(s.is_valid(), s.errors)
        # Must NOT raise TypeError even when owner is forwarded.
        updated = s.save(owner=self.user)
        self.assertEqual(updated.owner_id, self.user.id)
        self.assertEqual(updated.host, 'h2')
        # Old password preserved (none supplied in the update payload).
        self.assertEqual(updated.get_password(), 'old')

    def test_owner_from_kwarg_overrides_payload(self):
        # Even if a malicious payload tried to inject owner (it's read_only),
        # the kwarg from the view must be the authoritative source.
        from apps.sftp.serializers import SftpConfigSerializer
        other = User.objects.create_user(username='other', password='pw')
        data = {
            'name': 'inject', 'host': 'h', 'port': 22, 'username': 'u',
            'password': 'pw',
        }
        s = SftpConfigSerializer(data=data)
        self.assertTrue(s.is_valid(), s.errors)
        instance = s.save(owner=self.user)
        self.assertEqual(instance.owner_id, self.user.id)
        # And 'other' has no config of that name.
        self.assertFalse(SftpConfig.objects.filter(owner=other, name='inject').exists())
