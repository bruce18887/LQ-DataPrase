from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITestCase

from apps.datafiles.models import DataFile
from apps.datafiles.utils import extract_product_code

User = get_user_model()


class ExtractProductCodeTests(TestCase):
    """Unit tests for extract_product_code against real filename examples."""

    def test_real_filename_examples(self):
        cases = {
            'BPD60320_FT.csv': 'BPD60320',
            'BPD60320_QA1.csv': 'BPD60320',
            'BPD60320_C01F40#AAA12603030006_FT1-FT1-1_R2603030042_20260305_204439.csv': 'BPD60320',
            'DA35_BPC50338_CL08D4.01#AEA3_414A07_2604140567_FT_20260420_164504.csv': 'BPC50338',
            'BN281R3CYCAA_2604160006_TTTA803100.03_06_CP1_20260418161733.csv': 'BN281',
            'BPD93204_FT1_ETS163550_12252024.csv': 'BPD93204',
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(extract_product_code(filename), expected)

    def test_non_matching_returns_empty(self):
        self.assertEqual(extract_product_code('gage_m_S1.csv'), '')
        self.assertEqual(extract_product_code('random.csv'), '')
        self.assertEqual(extract_product_code(''), '')


def _make_datafile(owner, filename, **kwargs):
    defaults = dict(
        file_path=f'/tmp/{filename}',
        file_size=100,
        format_type='CTA8290D',
        product_code=extract_product_code(filename),
    )
    defaults.update(kwargs)
    return DataFile.objects.create(owner=owner, filename=filename, **defaults)


class BulkDeleteTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u1', password='pw')
        self.other = User.objects.create_user(username='u2', password='pw')
        self.client.force_authenticate(self.user)
        self.f1 = _make_datafile(self.user, 'BPD60320_FT.csv')
        self.f2 = _make_datafile(self.user, 'BPD93204_FT1_ETS163550.csv')
        self.other_file = _make_datafile(self.other, 'BN281R3CYCAA_x.csv')

    def test_bulk_delete_only_own_files(self):
        ids = [self.f1.id, self.f2.id, self.other_file.id]
        resp = self.client.post('/api/v1/files/bulk_delete/', {'ids': ids}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['deleted'], 2)
        # Owner's files deleted, other user's file untouched.
        self.assertFalse(DataFile.objects.filter(id=self.f1.id).exists())
        self.assertFalse(DataFile.objects.filter(id=self.f2.id).exists())
        self.assertTrue(DataFile.objects.filter(id=self.other_file.id).exists())

    def test_bulk_delete_empty_ids(self):
        resp = self.client.post('/api/v1/files/bulk_delete/', {'ids': []}, format='json')
        self.assertEqual(resp.status_code, 400)


class ListFilterTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='lf', password='pw')
        self.client.force_authenticate(self.user)
        _make_datafile(self.user, 'BPD60320_FT.csv')
        _make_datafile(self.user, 'BPD60320_QA1.csv')
        _make_datafile(self.user, 'BPD93204_FT1.csv')

    def test_filter_by_product_code(self):
        resp = self.client.get('/api/v1/files/', {'product_code': 'BPD60320'})
        self.assertEqual(resp.status_code, 200)
        results = resp.data['results'] if 'results' in resp.data else resp.data
        codes = {r['product_code'] for r in results}
        self.assertEqual(codes, {'BPD60320'})
        self.assertEqual(len(results), 2)

    def test_search_by_filename(self):
        resp = self.client.get('/api/v1/files/', {'search': 'BPD93204'})
        self.assertEqual(resp.status_code, 200)
        results = resp.data['results'] if 'results' in resp.data else resp.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['product_code'], 'BPD93204')

    def test_product_codes_endpoint(self):
        resp = self.client.get('/api/v1/files/product_codes/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['product_codes'], ['BPD60320', 'BPD93204'])

    def test_product_codes_owner_scoped(self):
        other = User.objects.create_user(username='lf2', password='pw')
        _make_datafile(other, 'BN281R3CYCAA_x.csv')
        resp = self.client.get('/api/v1/files/product_codes/')
        self.assertNotIn('BN281', resp.data['product_codes'])
