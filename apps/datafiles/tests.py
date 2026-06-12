﻿from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITestCase

from apps.datafiles.models import DataFile
from apps.datafiles.utils import extract_product_code
from apps.datafiles.views import _user_upload_dir

import os
import shutil
import tempfile
import time

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
        }
        for filename, expected in cases.items():
            with self.subTest(filename=filename):
                # When no program_name is supplied the function falls back to
                # the historical filename-regex behaviour.
                self.assertEqual(extract_product_code(filename), expected)

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
            f.write('col1,col2\n1,2\n3,4\n')
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
            f.write('col1,col2\n99,98\n')
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
