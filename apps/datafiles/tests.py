from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APITestCase

from apps.datafiles.models import DataFile
from apps.datafiles.utils import extract_product_code
from apps.datafiles.views import _user_upload_dir

import io
import os
import shutil
import tempfile
import time
import zipfile

User = get_user_model()


class ExtractProductCodeTests(TestCase):
    """Unit tests for extract_product_code against real filename examples."""

    def test_real_filename_examples(self):
        cases = {
            'BPD60320_FT.csv': 'BPD60320',
            'BPD60320_QA1.csv': 'BPD60320',
            'BPD60320_C01F40#AAA12603030006_FT1-FT1-1_R2603030042_20260305_204439.csv': 'BPD60320',
            'DA35_BPC50338_CL08D4.01#AEA3_414A07_2604140567_FT_20260420_164504.csv': 'BPC50338',
            # Alphanumeric suffix is part of the product code — capture it.
            'BN281R3CYCAA_2604160006_TTTA803100.03_06_CP1_20260418161733.csv': 'BN281R3CYCAA',
            'BPD93204_FT1_ETS163550_12252024.csv': 'BPD93204',
            # C01Q batch markers carry a BP01-... prefix that must NOT win
            # over the real whole-token product code.
            'C01Q_BP01-2605220057_BPD93204__H0GG80#AAA12605220057__R2605230015_ETS165943_05242026.csv': 'BPD93204',
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                # When no program_name is supplied the function falls back to
                # the historical filename-regex behaviour.
                self.assertEqual(extract_product_code(filename), expected)

    def test_whole_token_beats_partial_prefix(self):
        # A token that is exactly a product code wins over an earlier token
        # whose regex only matches a prefix (the BP01 in "BP01-2605220057"
        # is a batch marker, not the product).
        self.assertEqual(
            extract_product_code(
                'C01Q_BP01-2605220057_BPD93204__H0GG80#AAA12605220057__R2605230015_ETS165943_05242026.csv',
            ),
            'BPD93204',
        )
        self.assertEqual(
            extract_product_code('BP01-2605220057_BPD93204_QA1.csv'),
            'BPD93204',
        )
        # Compound .cpts program: first whole token wins over the longer
        # BPD60320XBAF suffix (both are whole tokens in their own right).
        self.assertEqual(
            extract_product_code(
                'R2602280062_FT1-RT2-1.csv',
                'BPC61320A_FT_AAA_BPD60320XBAF_PD.cpts',
            ),
            'BPC61320A',
        )
        # Partial match alone still works as a fallback (dash-suffix token).
        self.assertEqual(
            extract_product_code('BPD80350XBAD-FB_2503310007_C005X6_14_CP1_20250415194938.csv'),
            'BPD80350XBAD',
        )
        # ... and a lone partial prefix remains the best available answer.
        self.assertEqual(extract_product_code('X_BP01-2605220057.csv'), 'BP01')

    def test_non_matching_returns_empty(self):
        self.assertEqual(extract_product_code('gage_m_S1.csv'), '')
        self.assertEqual(extract_product_code('random.csv'), '')
        self.assertEqual(extract_product_code(''), '')

    def test_program_name_pts_pgs_pds(self):
        # The data filename is the primary source — the CSV test-program
        # name is only consulted when the filename doesn't expose a
        # B-prefix token. Both sources are scanned with the same regex so
        # trailing suffixes (``_FT_SAB_BPC50338XBAC_EN``,
        # ``JAVBN281R3CYCAAV1.6``) collapse to the leading product code.
        cases = {
            'BPD60320_FT.csv':         ('BPD60320.pts',                       'BPD60320'),
            'BPD60320_QA1.csv':         ('BPD60320.pgs',                       'BPD60320'),
            'DA35_BPC50338_...':        ('BPC50338_FT_SAB_BPC50338XBAC_EN.pts', 'BPC50338'),
            'BN281R3CYCAA_x.csv':       ('JAVBN281R3CYCAAV1.6.pgs',            'BN281R3CYCAA'),
            'BPD93204_FT1_ETS163550.csv': ('BPD93204.pts',                      'BPD93204'),
        }
        for filename, (program_name, expected) in cases.items():
            with self.subTest(filename=filename, program_name=program_name):
                self.assertEqual(extract_product_code(filename, program_name), expected)

    def test_program_name_extension_case_insensitive(self):
        # Some tester hosts report the extension in upper case; treat that
        # the same as the lower-case form.
        self.assertEqual(extract_product_code('BPD60320.csv', 'BPD60320.PTS'), 'BPD60320')
        self.assertEqual(extract_product_code('BPD60320.csv', 'BPD60320.Pgs'), 'BPD60320')

    def test_program_name_with_directory(self):
        # The parser feeds a basename already, but if a future caller passes
        # a full path it should still work.
        self.assertEqual(
            extract_product_code('BPD60320.csv', 'Z:\\tests\\BPD60320.pts'),
            'BPD60320',
        )

    def test_program_name_unknown_ext_falls_back_to_filename(self):
        # If the program extension is not in the recognised set, the
        # function falls back to scanning the data filename.
        self.assertEqual(
            extract_product_code('BPD60320_FT.csv', 'something.bin'),
            'BPD60320',
        )
        # Same for the historical empty-program_name case.
        self.assertEqual(
            extract_product_code('BPD60320_FT.csv', ''),
            'BPD60320',
        )

    def test_program_name_only_no_filename_match(self):
        # Program-only path (e.g. STS8200 device-name "BN281" without
        # a product-code-like token in the data filename).
        self.assertEqual(extract_product_code('2604160006_x.csv', 'BN281.pts'), 'BN281')
        self.assertEqual(extract_product_code('2604160006_x.csv', 'BN281.pgs'), 'BN281')

    def test_cpts_compound_program_extension(self):
        # Regression (quest.txt #5): SFTP batch files whose data filename has
        # no B-prefix token but whose CSV header program name is a ``.cpts``
        # compound spec. Without ``.cpts`` in the recognised extensions the
        # product code was silently dropped (product column showed empty).
        self.assertEqual(
            extract_product_code(
                'R2602280062_FT1-RT2-1_20260314_091556.csv',
                'BPC61320A_FT_AAA_BPD60320XBAF_PD.cpts',
            ),
            'BPC61320A',
        )
        # Case-insensitive extension still applies to .cpts.
        self.assertEqual(
            extract_product_code('R260_x.csv', 'BPC61320A_FT.CPTS'),
            'BPC61320A',
        )


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


class UserUploadDirTests(TestCase):
    """Verify _user_upload_dir uses the user's username (not numeric id).

    Regression test for the 2026-06-07 bug: `_user_upload_dir` had been
    refactored in the project memory but the change never reached disk —
    paths were still emitted as ``media/data/<id>/<file_type>/``. This locks
    in the username-based layout so a future refactor can't silently
    regress to id-based directories.
    """

    def setUp(self):
        # _user_upload_dir creates the directory on disk, so capture a list
        # of pre-existing entries under media/data so tearDown can clean up
        # only the test-introduced ones.
        from django.conf import settings
        self._data_root = os.path.join(settings.MEDIA_ROOT, 'data')
        self._pre_existing = set(os.listdir(self._data_root)) if os.path.isdir(self._data_root) else set()

    def tearDown(self):
        # Best-effort: remove only directories we created, leave admin/ and
        # any other pre-existing user dirs alone.
        if not os.path.isdir(self._data_root):
            return
        for name in os.listdir(self._data_root):
            if name in self._pre_existing:
                continue
            full = os.path.join(self._data_root, name)
            if os.path.isdir(full):
                shutil.rmtree(full, ignore_errors=True)

    def test_uses_username_not_id(self):
        u = User.objects.create_user(username='admin', password='pw')
        path = _user_upload_dir(u, 'single')
        # Path must include the username segment and NOT the numeric id.
        self.assertIn('admin', path)
        self.assertNotIn(f'/{u.id}/', path)
        # The relative suffix is media/data/<username>/<file_type>/.
        self.assertTrue(
            path.replace('\\', '/').endswith('/data/admin/single'),
            f'unexpected path: {path!r}',
        )

    def test_file_type_segment(self):
        u = User.objects.create_user(username='qa01', password='pw')
        path = _user_upload_dir(u, 'batch')
        self.assertTrue(path.replace('\\', '/').endswith('/data/qa01/batch'))

    def test_separate_users_get_separate_dirs(self):
        a = User.objects.create_user(username='alice', password='pw')
        b = User.objects.create_user(username='bob', password='pw')
        self.assertNotEqual(_user_upload_dir(a), _user_upload_dir(b))

    def test_creates_directory_on_disk(self):
        import os
        u = User.objects.create_user(username='create_test_user', password='pw')
        path = _user_upload_dir(u, 'single')
        self.assertTrue(os.path.isdir(path), f'expected {path} to exist')

    def test_none_user_raises(self):
        with self.assertRaises(ValueError):
            _user_upload_dir(None)

    def test_unicode_username_is_safe(self):
        # Django's UnicodeUsernameValidator allows letters from any script;
        # ensure the path is built without raising on common non-ASCII names.
        u = User.objects.create_user(username='alice测试', password='pw')
        path = _user_upload_dir(u, 'single')
        self.assertIn('alice测试', path)


class NormalizeTagsTests(TestCase):
    """Pure-function coverage for normalize_tags (see serializers.py)."""

    def test_none_or_empty_returns_empty_list(self):
        from apps.datafiles.serializers import normalize_tags
        self.assertEqual(normalize_tags(None), [])
        self.assertEqual(normalize_tags([]), [])
        self.assertEqual(normalize_tags(''), [])

    def test_trims_and_drops_empty_strings(self):
        from apps.datafiles.serializers import normalize_tags
        self.assertEqual(normalize_tags(['  alpha  ', '', '   ']), ['alpha'])

    def test_case_insensitive_dedup_keeps_first_casing(self):
        from apps.datafiles.serializers import normalize_tags
        self.assertEqual(
            normalize_tags(['Hot', 'HOT', 'hot', 'Lot']),
            ['Hot', 'Lot'],
        )

    def test_non_string_raises(self):
        from rest_framework import serializers as s
        from apps.datafiles.serializers import normalize_tags
        with self.assertRaises(s.ValidationError):
            normalize_tags(['ok', 42])

    def test_non_list_raises(self):
        from rest_framework import serializers as s
        from apps.datafiles.serializers import normalize_tags
        with self.assertRaises(s.ValidationError):
            normalize_tags('not-a-list')  # type: ignore[arg-type]

    def test_max_length_enforced(self):
        from rest_framework import serializers as s
        from apps.datafiles.serializers import normalize_tags, TAG_MAX_LENGTH
        too_long = 'a' * (TAG_MAX_LENGTH + 1)
        with self.assertRaises(s.ValidationError):
            normalize_tags([too_long])

    def test_max_count_enforced(self):
        from rest_framework import serializers as s
        from apps.datafiles.serializers import normalize_tags, TAG_MAX_COUNT
        with self.assertRaises(s.ValidationError):
            normalize_tags([f't{i}' for i in range(TAG_MAX_COUNT + 1)])


class DataFileTagsAPITests(APITestCase):
    """End-to-end coverage for the §4 set_tags / list_tags endpoints."""

    def setUp(self):
        self.user = User.objects.create_user(username='taguser', password='pw')
        self.client.force_authenticate(self.user)
        self.f1 = _make_datafile(self.user, 'BPD60320_FT.csv', tags=['Hot', 'PR_Phase1'])
        self.f2 = _make_datafile(self.user, 'BPD93204_FT1.csv', tags=['PR_Phase1', 'COLD'])

    def test_set_tags_overwrites_and_normalises(self):
        resp = self.client.post(
            f'/api/v1/files/{self.f1.id}/set_tags/',
            {'tags': ['  New_Tag  ', 'NEW_TAG', '', 'Q2']},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.f1.refresh_from_db()
        # Whitespace trimmed, case-insensitive dedup → New_Tag kept, Q2 kept.
        self.assertEqual(self.f1.tags, ['New_Tag', 'Q2'])
        self.assertEqual(resp.data['tags'], ['New_Tag', 'Q2'])

    def test_set_tags_owner_scoped_404(self):
        other = User.objects.create_user(username='other', password='pw')
        f_other = _make_datafile(other, 'X.csv')
        resp = self.client.post(
            f'/api/v1/files/{f_other.id}/set_tags/',
            {'tags': ['hack']},
            format='json',
        )
        # get_object() applies the view's queryset, which is owner-scoped.
        self.assertEqual(resp.status_code, 404)

    def test_set_tags_validation_error_returns_400(self):
        from apps.datafiles.serializers import TAG_MAX_COUNT
        resp = self.client.post(
            f'/api/v1/files/{self.f1.id}/set_tags/',
            {'tags': [f't{i}' for i in range(TAG_MAX_COUNT + 1)]},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('tags', resp.data)

    def test_list_tags_aggregates_user_files(self):
        resp = self.client.post('/api/v1/files/list_tags/', {}, format='json')
        self.assertEqual(resp.status_code, 200)
        # Case-insensitive dedup: Hot, PR_Phase1, COLD → PR_Phase1, COLD, Hot
        self.assertEqual(
            sorted(resp.data['tags'], key=str.lower),
            sorted(['Hot', 'PR_Phase1', 'COLD'], key=str.lower),
        )

    def test_list_tags_prefix_filter(self):
        resp = self.client.post(
            '/api/v1/files/list_tags/', {'prefix': 'pr'}, format='json',
        )
        self.assertEqual(resp.data['tags'], ['PR_Phase1'])

    def test_list_tags_owner_scoped(self):
        other = User.objects.create_user(username='other2', password='pw')
        _make_datafile(other, 'X.csv', tags=['SECRET'])
        resp = self.client.post('/api/v1/files/list_tags/', {}, format='json')
        self.assertNotIn('SECRET', resp.data['tags'])

    def test_list_tags_empty_when_no_files(self):
        User.objects.filter(username='taguser').delete()
        # Now there is no file at all. list_tags should return [].
        resp = self.client.post('/api/v1/files/list_tags/', {}, format='json')
        self.assertEqual(resp.data['tags'], [])


class BatchDirNormpathTests(APITestCase):
    r"""quest.txt #2: legacy SFTP folder downloads stored mixed-separator
    file paths (``...\dir\sub/file.csv``). Registered-detection and
    import-dedup must reconcile them via ``os.path.normpath`` so a fully
    imported batch isn't shown as "unregistered" (clickable import button)
    and re-importing doesn't create duplicate DataFile rows.
    """

    def setUp(self):
        self.user = User.objects.create_user(username='bd', password='pw')
        self.client.force_authenticate(self.user)
        self.batch_base = _user_upload_dir(self.user, 'batch')
        self.dir_name = 'BE01-TEST'
        self.csv_dir = os.path.join(self.batch_base, self.dir_name, 'R260')
        os.makedirs(self.csv_dir, exist_ok=True)
        self.csv_path = os.path.join(self.csv_dir, 'file.csv')
        with open(self.csv_path, 'w') as f:
            f.write('a,b\n1,2\n')
        # Store a NON-normalized path (extra '.' segment) that only equals the
        # on-disk os.walk path after normpath() — OS-independent stand-in for
        # the Windows backslash/forward-slash mismatch.
        stored = os.path.join(self.batch_base, self.dir_name, 'R260', '.', 'file.csv')
        self.df = DataFile.objects.create(
            owner=self.user, filename='file.csv', file_path=stored,
            file_size=8, format_type='CTA8290D', file_type='batch',
            batch_name=self.dir_name, status='ready',
        )

    def tearDown(self):
        shutil.rmtree(os.path.join(self.batch_base, self.dir_name), ignore_errors=True)

    def test_registered_detection_handles_separator_mismatch(self):
        resp = self.client.get('/api/v1/batch-dirs/')
        self.assertEqual(resp.status_code, 200)
        entry = next((d for d in resp.data if d['name'] == self.dir_name), None)
        self.assertIsNotNone(entry)
        # Must be reported as fully registered, not falsely "unregistered".
        self.assertTrue(entry['registered'])

    def test_import_dedups_non_normalized_path(self):
        before = DataFile.objects.filter(
            owner=self.user, batch_name=self.dir_name
        ).count()
        resp = self.client.post(
            '/api/v1/batch-dirs/import/', {'dir_name': self.dir_name}, format='json'
        )
        self.assertEqual(resp.status_code, 201)
        after = DataFile.objects.filter(
            owner=self.user, batch_name=self.dir_name
        ).count()
        # No duplicate row created for the already-registered file.
        self.assertEqual(after, before)


class SummaryFileSkipTests(APITestCase):
    """quest.txt 旁注: ``Sum_*.csv`` summary dumps must never be counted or
    registered as batch data — they parse to zero rows, carry no program
    name, and pollute the dashboard's "latest ready file" pick.
    """

    def setUp(self):
        self.user = User.objects.create_user(username='sf', password='pw')
        self.client.force_authenticate(self.user)
        self.batch_base = _user_upload_dir(self.user, 'batch')
        self.dir_name = 'LOT-SUM'
        self.dir_path = os.path.join(self.batch_base, self.dir_name)
        os.makedirs(self.dir_path, exist_ok=True)
        self.data_csv = os.path.join(self.dir_path, 'BPD60320_FT.csv')
        self.sum_csv = os.path.join(self.dir_path, 'Sum_093518.csv')
        for p in (self.data_csv, self.sum_csv):
            with open(p, 'w') as f:
                f.write('a,b\n1,2\n')

    def tearDown(self):
        shutil.rmtree(self.dir_path, ignore_errors=True)

    def test_predicate(self):
        from apps.datafiles.views import _is_summary_csv, _is_data_csv
        self.assertTrue(_is_summary_csv('Sum_093518.csv'))
        self.assertTrue(_is_summary_csv('sum_x.csv'))
        self.assertFalse(_is_summary_csv('BPD60320_FT.csv'))
        self.assertFalse(_is_data_csv('Sum_1.csv'))
        self.assertTrue(_is_data_csv('R2602280062_FT1.csv'))

    def test_list_excludes_summary_from_count(self):
        resp = self.client.get('/api/v1/batch-dirs/')
        self.assertEqual(resp.status_code, 200)
        entry = next((d for d in resp.data if d['name'] == self.dir_name), None)
        self.assertIsNotNone(entry)
        self.assertEqual(entry['file_count'], 1)  # only the real data file

    def test_import_skips_summary(self):
        resp = self.client.post(
            '/api/v1/batch-dirs/import/', {'dir_name': self.dir_name}, format='json'
        )
        self.assertEqual(resp.status_code, 201)
        names = set(
            DataFile.objects.filter(
                owner=self.user, batch_name=self.dir_name
            ).values_list('filename', flat=True)
        )
        self.assertEqual(names, {'BPD60320_FT.csv'})

class ParseCacheInvalidationTests(TestCase):
    """Regression: the parse cache must auto-invalidate when a DataFile's
    ``file_path`` is re-pointed at a new on-disk location, otherwise
    the analysis endpoints keep 400-ing with
    ``file_not_found_or_parse_failed`` even after the DB row was fixed
    (this is what happened when the project was moved from
    ``DataPhrase_Django`` to ``LQ-DataPrase`` on 2026-06-12 -- the
    move-management command rewrote ``file_path`` but the in-process
    cache was still serving the old (None, None, fmt) entry).

    The fix is to fold the file's on-disk mtime into the cache key, so
    any path/content change forces a re-parse.
    """

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='cache_user', password='pw')
        # Two real on-disk files in a tmp dir, one with valid data, one empty.
        self.tmp = tempfile.mkdtemp(prefix='parse_cache_test_')
        self.good_path = os.path.join(self.tmp, 'good.csv')
        with open(self.good_path, 'w') as f:
            # 合法的 CTA8290D 格式：marker + 表头/单位/下限/上限 4 行 + 数据行
            # （此前 fixture 缺 [Data] 标记，解析器返回 None，测试恒失败）
            f.write('[Data]\ncol1,col2\nu1,u2\n1,2\n2,1\n1,2\n3,4\n')
        self.bad_path = os.path.join(self.tmp, 'bad.csv')
        with open(self.bad_path, 'w') as f:
            f.write('not a real data file')
        self.df = DataFile.objects.create(
            owner=self.user,
            filename='good.csv',
            file_path=self.good_path,
            file_size=os.path.getsize(self.good_path),
            format_type='CTA8290D',
            status='ready',
        )
        # Make sure no stale cache entry leaks in from another test.
        from apps.datafiles.services import clear_parse_cache
        clear_parse_cache()

    def tearDown(self):
        from apps.datafiles.services import clear_parse_cache
        clear_parse_cache()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cache_hits_when_path_unchanged(self):
        from apps.datafiles.services import get_cached_parsed_file
        df1, _, _ = get_cached_parsed_file(self.df.id, self.user.id)
        self.assertIsNotNone(df1)
        # Second call should hit the same cache entry (returns the same DataFrame).
        df2, _, _ = get_cached_parsed_file(self.df.id, self.user.id)
        self.assertIs(df1, df2, 'cache should return the same DataFrame object')

    def test_cache_reparses_when_file_path_re_pointed(self):
        from apps.datafiles.services import get_cached_parsed_file
        # Prime the cache against the (working) good.csv.
        df1, _, _ = get_cached_parsed_file(self.df.id, self.user.id)
        self.assertIsNotNone(df1)
        # Re-point at the bad file (still on disk, so the cache key's
        # ``path_key`` derived from the new file's mtime will be different
        # and bust the cache).
        DataFile.objects.filter(pk=self.df.id).update(file_path=self.bad_path)
        df2, _, fmt2 = get_cached_parsed_file(self.df.id, self.user.id)
        # The bad file is not a parseable CSV -- df is None, fmt is CTA8290D.
        # The crucial part: we did NOT get the old cached (df1, ...) back.
        self.assertIsNot(df2, df1, 'cache must not return the previous (good) parse')
        self.assertIsNone(df2)
        self.assertEqual(fmt2, 'CTA8290D')

    def test_cache_reparses_when_file_content_replaced(self):
        from apps.datafiles.services import get_cached_parsed_file
        df1, _, _ = get_cached_parsed_file(self.df.id, self.user.id)
        self.assertIsNotNone(df1)
        # Replace the on-disk file contents in place -- mtime_ns changes,
        # which changes the cache key, which forces a re-parse.
        with open(self.good_path, 'w') as f:
            f.write('[Data]\ncol1,col2\nu1,u2\n1,2\n2,1\n99,98\n')
        # Also bump mtime explicitly to defeat coarse-grained FS mtime
        # resolution (Windows defaults to 100-ns FAT granularity, but
        # two writes within the same tick would still differ at ns).
        new_mtime = time.time() + 5
        os.utime(self.good_path, (new_mtime, new_mtime))
        df2, _, _ = get_cached_parsed_file(self.df.id, self.user.id)
        # A fresh parse must have happened, so the DataFrame is a new
        # object holding the new data.
        self.assertIsNot(df2, df1)
        self.assertIsNotNone(df2)
        self.assertEqual(list(df2['col1']), [99])


class FixMovedProjectPathsCommandTests(TestCase):
    """Coverage for the ``fix_moved_project_paths`` management command:

    * rewrites ``file_path`` from old project root to new project root
    * leaves rows already under the new root untouched
    * refuses to run if old and new roots are identical
    * refuses to rewrite to a path whose target file is missing on disk
    """

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='move_user', password='pw')
        self.tmp = tempfile.mkdtemp(prefix='fix_paths_test_')
        # Pretend the project was once at ``<tmp>/OldProject`` and is
        # now at ``<tmp>/NewProject``. The DB rows still point at OldProject.
        self.old_root = os.path.join(self.tmp, 'OldProject')
        self.new_root = os.path.join(self.tmp, 'NewProject')
        self.old_uploads = os.path.join(self.old_root, 'media', 'uploads')
        self.new_uploads = os.path.join(self.new_root, 'media', 'uploads')
        os.makedirs(self.old_uploads, exist_ok=True)
        os.makedirs(self.new_uploads, exist_ok=True)
        # Two files: one copied to new root, one only on old root (orphan).
        self.copied_name = 'copied.csv'
        self.orphan_name = 'orphan.csv'
        with open(os.path.join(self.old_uploads, self.copied_name), 'w') as f:
            f.write('a,b\n1,2\n')
        with open(os.path.join(self.old_uploads, self.orphan_name), 'w') as f:
            f.write('a,b\n3,4\n')
        with open(os.path.join(self.new_uploads, self.copied_name), 'w') as f:
            f.write('a,b\n1,2\n')  # real target the command should re-point at

        self.df_copied = DataFile.objects.create(
            owner=self.user, filename=self.copied_name,
            file_path=os.path.join(self.old_uploads, self.copied_name),
            file_size=8, format_type='CTA8290D', status='ready',
        )
        self.df_orphan = DataFile.objects.create(
            owner=self.user, filename=self.orphan_name,
            file_path=os.path.join(self.old_uploads, self.orphan_name),
            file_size=8, format_type='CTA8290D', status='ready',
        )
        # Plus one row that already points at the new root �� must be left alone.
        self.df_already_new = DataFile.objects.create(
            owner=self.user, filename='already_new.csv',
            file_path=os.path.join(self.new_uploads, 'already_new.csv'),
            file_size=8, format_type='CTA8290D', status='ready',
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *extra):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command(
            'fix_moved_project_paths',
            '--old-root', self.old_root,
            '--new-root', self.new_root,
            *extra,
            stdout=out,
        )
        return out.getvalue()

    def test_rewrites_only_rows_with_target_on_disk(self):
        output = self._run()
        self.df_copied.refresh_from_db()
        self.df_orphan.refresh_from_db()
        self.df_already_new.refresh_from_db()
        self.assertEqual(
            self.df_copied.file_path,
            os.path.join(self.new_uploads, self.copied_name),
        )
        # Orphan's target doesn't exist on the new root �� left alone.
        self.assertEqual(
            self.df_orphan.file_path,
            os.path.join(self.old_uploads, self.orphan_name),
        )
        # Already-new row was never under the old root �� untouched.
        self.assertEqual(
            self.df_already_new.file_path,
            os.path.join(self.new_uploads, 'already_new.csv'),
        )
        self.assertIn('rewrote 1', output)

    def test_dry_run_does_not_touch_db(self):
        self._run('--dry-run')
        self.df_copied.refresh_from_db()
        self.assertEqual(
            self.df_copied.file_path,
            os.path.join(self.old_uploads, self.copied_name),
        )

    def test_refuses_identical_roots(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('fix_moved_project_paths',
                         '--old-root', self.old_root,
                         '--new-root', self.old_root)


class ConsistencyCheckTests(APITestCase):
    """数据修复中心：GET 三区块扫描（孤立 DB 记录 / 孤立磁盘文件 / 产品名缺失）
    与 POST 修复动作（import_orphaned_disk / fix_product_codes），含角色权限与
    既有 delete 动作回归。
    """

    def setUp(self):
        # The main actor is an administrator so every action is permitted;
        # the role matrix itself is covered by test_post_role_permissions.
        self.user = User.objects.create_user(username='cc', password='pw')
        self.user.role = 'administrator'
        self.user.save()
        self.other = User.objects.create_user(username='cc2', password='pw')
        self.client.force_authenticate(self.user)
        self.batch_base = _user_upload_dir(self.user, 'batch')
        self.other_base = _user_upload_dir(self.other, 'batch')

    def tearDown(self):
        shutil.rmtree(self.batch_base, ignore_errors=True)
        shutil.rmtree(self.other_base, ignore_errors=True)

    def _write(self, rel_path, content='a,b\n1,2\n'):
        """Write a file under the current user's batch base, returning its path."""
        path = os.path.join(self.batch_base, rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(content)
        return os.path.normpath(path)

    def _get(self):
        return self.client.get('/api/v1/consistency-check/')

    def _post(self, action):
        return self.client.post(
            '/api/v1/consistency-check/', {'action': action}, format='json'
        )

    # ── GET：孤立数据库记录 ──────────────────────────────────────────

    def test_get_orphaned_db_records(self):
        _make_datafile(
            self.user, 'BPD60320_FT.csv', file_type='batch', batch_name='LOT-A',
            sub_batch='S1', file_path='C:\\nonexistent\\x.csv',
        )
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['orphaned_db_count'], 1)
        entry = resp.data['orphaned_db'][0]
        self.assertEqual(entry['filename'], 'BPD60320_FT.csv')
        self.assertEqual(entry['batch_name'], 'LOT-A')
        self.assertEqual(entry['sub_batch'], 'S1')
        self.assertIn('file_path', entry)

    # ── GET：孤立磁盘文件（结构化 + 批次聚合） ───────────────────────

    def test_get_orphaned_disk_structured(self):
        path = self._write('LOT-A/R260/BPD60320_FT.csv')
        resp = self._get()
        self.assertEqual(resp.data['orphaned_disk_count'], 1)
        entry = resp.data['orphaned_disk'][0]
        self.assertEqual(entry['path'], path)
        self.assertEqual(entry['filename'], 'BPD60320_FT.csv')
        self.assertEqual(entry['batch_name'], 'LOT-A')
        self.assertEqual(entry['sub_batch'], 'R260')

    def test_get_orphaned_disk_excludes_registered_and_summary(self):
        path = self._write('LOT-A/BPD60320_FT.csv')
        self._write('LOT-A/Sum_093518.csv')
        DataFile.objects.create(
            owner=self.user, filename='BPD60320_FT.csv', file_path=path,
            file_size=100, format_type='CTA8290D', file_type='batch',
            batch_name='LOT-A',
        )
        resp = self._get()
        self.assertEqual(resp.data['orphaned_disk_count'], 0)

    def test_get_display_truncates_at_50(self):
        for i in range(60):
            self._write(f'LOT-T/f{i}.csv')
        resp = self._get()
        self.assertEqual(resp.data['orphaned_disk_count'], 60)  # count is full
        self.assertEqual(len(resp.data['orphaned_disk']), 50)   # display slice

    # ── GET：产品名缺失 ──────────────────────────────────────────────

    def test_get_missing_product_code_preview_from_program(self):
        path = self._write('LOT-A/2604160006_x.csv')
        _make_datafile(
            self.user, '2604160006_x.csv', program_name='BN281.pts',
            product_code='', file_path=path, file_type='batch', batch_name='LOT-A',
        )
        resp = self._get()
        self.assertEqual(resp.data['missing_product_code_count'], 1)
        entry = resp.data['missing_product_code'][0]
        self.assertEqual(entry['preview_code'], 'BN281')
        self.assertFalse(entry['reparse_needed'])
        self.assertFalse(entry['file_missing'])

    def test_get_missing_product_code_flags(self):
        on_disk = self._write('LOT-A/x.csv')
        _make_datafile(
            self.user, 'x.csv', program_name='', product_code='',
            file_path=on_disk, file_type='batch', batch_name='LOT-A',
        )
        _make_datafile(
            self.user, 'random.csv', program_name='', product_code='',
            file_path='C:\\gone\\random.csv', file_type='single',
        )
        # Not missing — must never appear in the list.
        _make_datafile(self.user, 'BPD60320_FT.csv', product_code='BPD60320')
        resp = self._get()
        by_name = {e['filename']: e for e in resp.data['missing_product_code']}
        self.assertEqual(set(by_name), {'x.csv', 'random.csv'})
        self.assertTrue(by_name['x.csv']['reparse_needed'])
        self.assertFalse(by_name['x.csv']['file_missing'])
        self.assertFalse(by_name['random.csv']['reparse_needed'])
        self.assertTrue(by_name['random.csv']['file_missing'])
        self.assertIn('file_type', by_name['x.csv'])

    def test_get_owner_scoped(self):
        # Other user's orphaned disk file and missing-product-code row must
        # not leak into this user's check.
        other_path = os.path.join(self.other_base, 'LOT-X', 'other.csv')
        os.makedirs(os.path.dirname(other_path), exist_ok=True)
        with open(other_path, 'w') as f:
            f.write('a,b\n1,2\n')
        _make_datafile(
            self.other, 'other.csv', program_name='', product_code='',
            file_path=other_path,
        )
        resp = self._get()
        self.assertEqual(resp.data['orphaned_disk_count'], 0)
        self.assertEqual(resp.data['missing_product_code_count'], 0)

    # ── POST：import_orphaned_disk ───────────────────────────────────

    def test_import_orphaned_disk(self):
        self._write('LOT-A/BPD60320_FT.csv')                 # batch root level
        self._write('LOT-B/R260/2604160006_x.csv')           # sub-batch
        self._write('LOT-B/R260/Sum_1.csv')                  # summary: skipped
        resp = self._post('import_orphaned_disk')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['imported_count'], 2)
        self.assertEqual(resp.data['skipped_count'], 0)

        rows = {
            df.filename: df for df in DataFile.objects.filter(owner=self.user)
        }
        self.assertEqual(set(rows), {'BPD60320_FT.csv', '2604160006_x.csv'})
        bpd = rows['BPD60320_FT.csv']
        self.assertEqual(bpd.file_type, 'batch')
        self.assertEqual(bpd.batch_name, 'LOT-A')
        self.assertEqual(bpd.sub_batch, '')
        self.assertEqual(bpd.product_code, 'BPD60320')
        num = rows['2604160006_x.csv']
        self.assertEqual(num.batch_name, 'LOT-B')
        self.assertEqual(num.sub_batch, 'R260')

        # The imported set is no longer orphaned on the next check.
        self.assertEqual(self._get().data['orphaned_disk_count'], 0)

    def test_import_orphaned_disk_idempotent(self):
        self._write('LOT-A/BPD60320_FT.csv')
        self._post('import_orphaned_disk')
        before = DataFile.objects.filter(owner=self.user).count()
        resp = self._post('import_orphaned_disk')
        self.assertEqual(resp.data['imported_count'], 0)
        self.assertEqual(DataFile.objects.filter(owner=self.user).count(), before)

    # ── POST：fix_product_codes ──────────────────────────────────────

    def test_fix_from_stored_program_name(self):
        path = self._write('LOT-A/2604160006_x.csv')
        df = _make_datafile(
            self.user, '2604160006_x.csv', program_name='BN281.pts',
            product_code='', file_path=path, file_type='batch', batch_name='LOT-A',
        )
        resp = self._post('fix_product_codes')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['fixed_count'], 1)
        self.assertEqual(resp.data['still_missing_count'], 0)
        result = resp.data['results'][0]
        self.assertEqual(result['status'], 'fixed')
        self.assertEqual(result['product_code'], 'BN281')
        df.refresh_from_db()
        self.assertEqual(df.product_code, 'BN281')
        # Stored program_name already had a match — not rewritten.
        self.assertEqual(df.program_name, 'BN281.pts')

    def test_fix_reparses_file_for_program_name(self):
        # A self-contained mini CTA8280F file: filename WITHOUT the B-prefix
        # token so the filename source cannot match, header carrying a
        # TestFileName program (BPD60320.pts) the fix must recover by
        # reparsing. (A real sample was considered, but its program name
        # ``JAVBN281R3CYCAAV1.6.pgs`` does not start with a B token, so the
        # program-name path of extract_product_code cannot match it.)
        content = (
            '[CTA8280F]\n'
            'TestFileName,BPD60320.pts\n'
            '[Data]\n'
            'col1,col2\n'
            'mm,mm\n'
            '0,0\n'
            '1,1\n'
            '1,1\n'
            '1,1\n'
        )
        tmp = tempfile.mkdtemp(prefix='cc_fix_')
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        target = os.path.join(tmp, '2604_repair_x.csv')
        with open(target, 'w') as f:
            f.write(content)
        df = _make_datafile(
            self.user, '2604_repair_x.csv', program_name='', product_code='',
            file_path=target, file_type='batch',
        )
        resp = self._post('fix_product_codes')
        self.assertEqual(resp.data['fixed_count'], 1)
        self.assertEqual(resp.data['results'][0]['product_code'], 'BPD60320')
        df.refresh_from_db()
        self.assertEqual(df.product_code, 'BPD60320')
        # Reparse refreshed the stored program name too.
        self.assertEqual(df.program_name, 'BPD60320.pts')

    def test_fix_cannot_resolve(self):
        on_disk = self._write('LOT-A/random.csv')  # unparseable content
        _make_datafile(
            self.user, 'random.csv', program_name='', product_code='',
            file_path=on_disk, file_type='batch', batch_name='LOT-A',
        )
        _make_datafile(
            self.user, 'gone.csv', program_name='', product_code='',
            file_path='C:\\gone\\gone.csv', file_type='single',
        )
        resp = self._post('fix_product_codes')
        self.assertEqual(resp.data['fixed_count'], 0)
        self.assertEqual(resp.data['still_missing_count'], 2)
        by_name = {r['filename']: r for r in resp.data['results']}
        self.assertEqual(by_name['random.csv']['reason'], 'no_match')
        self.assertEqual(by_name['gone.csv']['reason'], 'file_missing')
        self.assertTrue(
            DataFile.objects.filter(owner=self.user, product_code='').count() == 2
        )

    def test_fix_and_import_owner_scoped(self):
        other_path = os.path.join(self.other_base, 'LOT-X', 'other.csv')
        os.makedirs(os.path.dirname(other_path), exist_ok=True)
        with open(other_path, 'w') as f:
            f.write('a,b\n1,2\n')
        _make_datafile(
            self.other, 'other.csv', program_name='BN281.pts', product_code='',
            file_path=other_path,
        )
        imp = self._post('import_orphaned_disk')
        self.assertEqual(imp.data['imported_count'], 0)
        fix = self._post('fix_product_codes')
        self.assertEqual(fix.data['fixed_count'], 0)
        self.assertEqual(fix.data['still_missing_count'], 0)
        other_df = DataFile.objects.get(owner=self.other, filename='other.csv')
        self.assertEqual(other_df.product_code, '')

    # ── 回归：既有 delete 动作 ───────────────────────────────────────

    def test_delete_orphaned_db_regression(self):
        _make_datafile(
            self.user, 'gone.csv', file_type='batch', batch_name='LOT-A',
            file_path='C:\\gone\\gone.csv',
        )
        kept_path = self._write('LOT-A/kept.csv')
        DataFile.objects.create(
            owner=self.user, filename='kept.csv', file_path=kept_path,
            file_size=100, format_type='CTA8290D', file_type='batch',
            batch_name='LOT-A',
        )
        resp = self._post('delete_orphaned_db')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['deleted_count'], 1)
        self.assertTrue(
            DataFile.objects.filter(owner=self.user, filename='kept.csv').exists()
        )
        self.assertFalse(
            DataFile.objects.filter(owner=self.user, filename='gone.csv').exists()
        )

    def test_delete_orphaned_disk_regression(self):
        orphan = self._write('LOT-A/orphan.csv')
        kept = self._write('LOT-A/kept.csv')
        DataFile.objects.create(
            owner=self.user, filename='kept.csv', file_path=kept,
            file_size=100, format_type='CTA8290D', file_type='batch',
            batch_name='LOT-A',
        )
        empty_dir = os.path.join(self.batch_base, 'LOT-EMPTY')
        os.makedirs(empty_dir, exist_ok=True)
        resp = self._post('delete_orphaned_disk')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['deleted_count'], 1)
        self.assertFalse(os.path.exists(orphan))
        self.assertTrue(os.path.exists(kept))
        self.assertFalse(os.path.exists(empty_dir))  # empty dir cleaned up

    # ── 权限：POST 按 action 分角色 ─────────────────────────────────

    def test_post_role_permissions(self):
        viewer = User.objects.create_user(username='cc_viewer', password='pw')
        viewer.role = 'viewer'
        viewer.save()
        self.client.force_authenticate(viewer)
        self.assertEqual(self._get().status_code, 200)  # viewer may check
        for action in ('delete_orphaned_db', 'delete_orphaned_disk',
                       'import_orphaned_disk', 'fix_product_codes'):
            self.assertEqual(self._post(action).status_code, 403, action)

        regular = User.objects.create_user(username='cc_user', password='pw')
        regular.role = 'user'
        regular.save()
        self.client.force_authenticate(regular)
        self.assertEqual(self._post('delete_orphaned_db').status_code, 403)
        self.assertEqual(self._post('delete_orphaned_disk').status_code, 403)
        self.assertEqual(self._post('import_orphaned_disk').status_code, 200)
        self.assertEqual(self._post('fix_product_codes').status_code, 200)

    def test_post_invalid_action(self):
        resp = self._post('nonsense')
        self.assertEqual(resp.status_code, 400)


# ── zip 压缩包上传 → 批次数据 ─────────────────────────────────

_MIN_CSV = (
    '[GENERAL],\n'
    'Tester_Type,CTA8290DPlus,\n'
    '[Data]\n'
    'col1,col2\n'
    'u1,u2\n'
    'min1,min2\n'
    'max1,max2\n'
    '1,2\n'
    '3,4\n'
)


def _zip_bytes(entries):
    """Build an in-memory zip archive from {member_name: content}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


class SafeExtractZipTests(TestCase):
    """Pure-function checks for _safe_extract_zip's Zip-Slip protection."""

    def test_safe_extract_blocks_traversal(self):
        from apps.datafiles.views import _safe_extract_zip
        tmp = tempfile.mkdtemp(prefix='safe_zip_')
        try:
            archive = _zip_bytes({
                'good.csv': 'a\n1\n',
                '../evil.csv': 'x\n',
                'a/../../evil2.csv': 'x\n',
                'C:/evil3.csv': 'x\n',
                'sub/../loop.csv': 'x\n',  # contains '..' segment → refused
                '/abs_evil.csv': 'x\n',    # absolute-style → lands inside dest
            })
            extracted = _safe_extract_zip(io.BytesIO(archive), tmp)
            basenames = sorted(os.path.basename(p) for p in extracted)
            # Escape attempts are dropped; absolute-style names are contained.
            self.assertEqual(basenames, ['abs_evil.csv', 'good.csv'])
            self.assertEqual(sorted(os.listdir(tmp)), ['abs_evil.csv', 'good.csv'])
            # Nothing was written next to tmp (i.e. outside dest_dir).
            self.assertFalse(os.path.exists(os.path.join(os.path.dirname(tmp), 'evil.csv')))
            self.assertFalse(os.path.exists(os.path.join(os.path.dirname(tmp), 'evil2.csv')))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_safe_extract_skips_directory_entries(self):
        from apps.datafiles.views import _safe_extract_zip
        tmp = tempfile.mkdtemp(prefix='safe_zip_')
        try:
            archive = _zip_bytes({'dir/': '', 'dir/a.csv': 'a\n1\n'})
            extracted = _safe_extract_zip(io.BytesIO(archive), tmp)
            self.assertEqual(
                [os.path.relpath(p, tmp) for p in extracted],
                [os.path.join('dir', 'a.csv')],
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ZipUploadTests(APITestCase):
    """Uploading a .zip extracts its CSVs and registers them as batch data."""

    def setUp(self):
        self.user = User.objects.create_user(username='zip_user', password='pw')
        self.client.force_authenticate(self.user)
        self.batch_base = _user_upload_dir(self.user, 'batch')
        self.single_dir = _user_upload_dir(self.user, 'single')

    def tearDown(self):
        for d in (self.batch_base, self.single_dir):
            if os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)

    def _upload_zip(self, name, entries):
        uploaded = SimpleUploadedFile(name, _zip_bytes(entries), content_type='application/zip')
        return self.client.post('/api/v1/upload/', {'files': uploaded}, format='multipart')

    def _upload_raw(self, name, content):
        uploaded = SimpleUploadedFile(name, content)
        return self.client.post('/api/v1/upload/', {'files': uploaded}, format='multipart')

    def test_zip_upload_creates_batch_files_with_subbatch(self):
        resp = self._upload_zip('LOT-A.zip', {
            'root.csv': _MIN_CSV,
            'sub/below.csv': _MIN_CSV,
            'readme.txt': 'ignored',
        })
        self.assertEqual(resp.status_code, 201, resp.data)
        rows = DataFile.objects.filter(owner=self.user, file_type='batch')
        self.assertEqual(rows.count(), 2)
        root = rows.get(filename='root.csv')
        sub = rows.get(filename='below.csv')
        self.assertEqual(root.batch_name, 'LOT-A')
        self.assertEqual(root.sub_batch, '')
        self.assertEqual(sub.batch_name, 'LOT-A')
        self.assertEqual(sub.sub_batch, 'sub')
        for df in rows:
            self.assertTrue(os.path.exists(df.file_path))

    def test_zip_upload_skips_summary_and_non_csv(self):
        resp = self._upload_zip('LOT-SUM.zip', {
            'BPD60320_FT.csv': _MIN_CSV,
            'Sum_093518.csv': _MIN_CSV,
            'readme.txt': 'ignored',
        })
        self.assertEqual(resp.status_code, 201, resp.data)
        names = set(DataFile.objects.filter(owner=self.user, file_type='batch')
                    .values_list('filename', flat=True))
        self.assertEqual(names, {'BPD60320_FT.csv'})

    def test_zip_upload_no_csv_returns_400_and_cleans_new_dir(self):
        resp = self._upload_zip('EMPTY.zip', {'readme.txt': 'no csv here'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('未找到 CSV', resp.data['error'])
        # Freshly created destination directory is cleaned up.
        self.assertFalse(os.path.isdir(os.path.join(self.batch_base, 'EMPTY')))
        self.assertEqual(DataFile.objects.filter(owner=self.user, file_type='batch').count(), 0)

    def test_zip_upload_no_csv_keeps_existing_dir(self):
        first = self._upload_zip('LOT-X.zip', {'data.csv': _MIN_CSV})
        self.assertEqual(first.status_code, 201, first.data)
        before = DataFile.objects.filter(owner=self.user, file_type='batch').count()

        resp = self._upload_zip('LOT-X.zip', {'readme.txt': 'no csv now'})
        self.assertEqual(resp.status_code, 400)
        # Existing batch directory and its records survive.
        self.assertTrue(os.path.exists(os.path.join(self.batch_base, 'LOT-X', 'data.csv')))
        self.assertEqual(DataFile.objects.filter(owner=self.user, file_type='batch').count(), before)

    def test_zip_upload_corrupt_zip_returns_400(self):
        resp = self._upload_raw('broken.zip', b'this is not a zip archive at all')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('已损坏', resp.data['error'])
        self.assertEqual(DataFile.objects.filter(owner=self.user).count(), 0)

    def test_zip_upload_unsupported_ext_400(self):
        for name, content in [('note.txt', b'x'), ('arc.7z', b'PK\x03\x04x'), ('arc.rar', b'x')]:
            resp = self._upload_raw(name, content)
            self.assertEqual(resp.status_code, 400, name)
            self.assertIn('仅支持 CSV 或 ZIP', resp.data['error'])

    def test_zip_upload_zip_slip_members_skipped(self):
        resp = self._upload_zip('SLIP.zip', {
            'good.csv': _MIN_CSV,
            '../evil.csv': 'x\n',
            'a/../../evil2.csv': 'x\n',
            'C:/evil3.csv': 'x\n',
        })
        self.assertEqual(resp.status_code, 201, resp.data)
        names = set(DataFile.objects.filter(owner=self.user, file_type='batch')
                    .values_list('filename', flat=True))
        self.assertEqual(names, {'good.csv'})
        # No files were written outside the batch base dir.
        for root, _dirs, files in os.walk(os.path.dirname(self.batch_base)):
            for f in files:
                fp = os.path.normpath(os.path.join(root, f))
                self.assertTrue(fp.startswith(os.path.normpath(self.batch_base)), f)

    def test_zip_upload_reupload_same_name_dedups(self):
        first = self._upload_zip('LOT-R.zip', {'a.csv': _MIN_CSV})
        self.assertEqual(first.status_code, 201, first.data)
        second = self._upload_zip('LOT-R.zip', {'a.csv': _MIN_CSV})
        self.assertEqual(second.status_code, 201, second.data)
        rows = DataFile.objects.filter(owner=self.user, file_type='batch', batch_name='LOT-R')
        self.assertEqual(rows.count(), 1)  # no duplicate registration
        self.assertEqual(len(second.data), 0)

    def test_zip_upload_reupload_refreshes_disk_content(self):
        from apps.datafiles.services import clear_parse_cache, get_cached_parsed_file
        first = self._upload_zip('LOT-C.zip', {'a.csv': _MIN_CSV})
        self.assertEqual(first.status_code, 201, first.data)
        df_row = DataFile.objects.get(owner=self.user, batch_name='LOT-C')
        clear_parse_cache()
        df0, _meta0, _ = get_cached_parsed_file(df_row.id, self.user.id)
        original = df0['col2'].iloc[0]

        replaced = (
            '[GENERAL],\n'
            'Tester_Type,CTA8290DPlus,\n'
            '[Data]\n'
            'col1,col2\n'
            'u1,u2\n'
            'min1,min2\n'
            'max1,max2\n'
            '5,6\n'
            '7,4\n'
        )
        second = self._upload_zip('LOT-C.zip', {'a.csv': replaced})
        self.assertEqual(second.status_code, 201, second.data)
        # mtime_ns cache key invalidates → re-parse serves the new content.
        df1, _meta1, _ = get_cached_parsed_file(df_row.id, self.user.id)
        self.assertEqual(df1['col2'].iloc[0], 6)
        self.assertNotEqual(df1['col2'].iloc[0], original)

    def test_zip_upload_mixed_csv_and_zip_one_request(self):
        csv_file = SimpleUploadedFile('single.csv', _MIN_CSV.encode())
        zip_file = SimpleUploadedFile('MIXED.zip', _zip_bytes({'a.csv': _MIN_CSV}),
                                      content_type='application/zip')
        resp = self.client.post('/api/v1/upload/',
                                {'files': [csv_file, zip_file]}, format='multipart')
        self.assertEqual(resp.status_code, 201, resp.data)
        single = DataFile.objects.get(owner=self.user, filename='single.csv')
        self.assertEqual(single.file_type, 'single')
        batch = DataFile.objects.get(owner=self.user, filename='a.csv')
        self.assertEqual(batch.file_type, 'batch')
        self.assertEqual(batch.batch_name, 'MIXED')

    def test_zip_upload_owner_scoped(self):
        resp = self._upload_zip('SHARED.zip', {'a.csv': _MIN_CSV})
        self.assertEqual(resp.status_code, 201, resp.data)

        other = User.objects.create_user(username='zip_user2', password='pw')
        self.client.force_authenticate(other)
        resp2 = self._upload_zip('SHARED.zip', {'b.csv': _MIN_CSV})
        self.assertEqual(resp2.status_code, 201, resp2.data)

        # Same zip name, isolated per-user batch directories.
        dir_a = os.path.join(self.batch_base, 'SHARED')
        dir_b = os.path.join(_user_upload_dir(other, 'batch'), 'SHARED')
        self.assertTrue(os.path.exists(os.path.join(dir_a, 'a.csv')))
        self.assertFalse(os.path.exists(os.path.join(dir_a, 'b.csv')))
        self.assertTrue(os.path.exists(os.path.join(dir_b, 'b.csv')))
        self.assertFalse(os.path.exists(os.path.join(dir_b, 'a.csv')))
