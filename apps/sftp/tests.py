from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITestCase

from apps.sftp import crypto
from apps.sftp.models import SftpConfig

User = get_user_model()


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
