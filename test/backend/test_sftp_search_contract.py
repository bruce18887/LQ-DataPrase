"""SearchSpec 的校验与钳位（spec §3.2）。无 DB、无网络。

跑法：python manage.py test test.backend.test_sftp_search_contract
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp.search import contracts  # noqa: E402

BASE = {'roots': ['/datalogs'], 'mode': 'name'}


def spec(**over):
    return contracts.parse_spec({**BASE, **over})


class RequiredFieldTests(SimpleTestCase):
    def test_missing_roots_rejected(self):
        with self.assertRaises(contracts.SearchSpecError) as ctx:
            contracts.parse_spec({'mode': 'name'})
        self.assertEqual(ctx.exception.field, 'roots')

    def test_empty_roots_rejected(self):
        with self.assertRaises(contracts.SearchSpecError):
            contracts.parse_spec({'roots': [], 'mode': 'name'})

    def test_unknown_key_rejected(self):
        """未知键必须拒绝。sftp.ts 至今发 only_data 而后端从不读它，就是缺这条。"""
        with self.assertRaises(contracts.SearchSpecError) as ctx:
            spec(recursive=True)
        self.assertIn('recursive', str(ctx.exception))

    def test_content_mode_requires_term(self):
        with self.assertRaises(contracts.SearchSpecError) as ctx:
            spec(mode='content', term='   ')
        self.assertEqual(ctx.exception.field, 'term')

    def test_column_mode_requires_column_name(self):
        with self.assertRaises(contracts.SearchSpecError) as ctx:
            spec(mode='column', column_name='')
        self.assertEqual(ctx.exception.field, 'column_name')

    def test_bad_mode_enum_rejected(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(mode='regex')

    def test_bad_matching_enum_rejected(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(mode='content', term='x', matching='regex')

    def test_bad_depth_enum_rejected(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(depth='deep')


class DefaultTests(SimpleTestCase):
    def test_defaults(self):
        s = spec()
        self.assertEqual(s.depth, 'all')
        self.assertIsNone(s.effective_max_depth())
        self.assertEqual(s.workers, 4)
        self.assertEqual(s.timeout, 600)
        self.assertTrue(s.data_files_only)
        self.assertTrue(s.allow_server_grep)
        self.assertFalse(s.stop_after_listing)
        self.assertFalse(s.one_per_folder)
        self.assertTrue(s.first_hit_per_file)
        self.assertEqual(s.matching, 'substring')
        self.assertEqual(s.max_entries, 200_000)
        self.assertEqual(s.max_candidates, 5_000)
        self.assertEqual(s.max_matches, 2_000)
        self.assertEqual(s.max_scan_bytes, 64 * 1024 * 1024)
        self.assertEqual(s.column_rows, 10)
        self.assertEqual(s.matches_per_file, 1)
        self.assertEqual(s.prune_dirs, [])


class ClampTests(SimpleTestCase):
    """越界夹到边界并记码，不报错——用户拖个滑块到最大不该吃 400。"""

    def test_workers_ceiling_and_floor(self):
        self.assertEqual(spec(workers=99).workers, 8)
        self.assertIn('clamped_workers', spec(workers=99).clamped)
        self.assertEqual(spec(workers=0).workers, 1)

    def test_max_entries_ceiling(self):
        self.assertEqual(spec(max_entries=10 ** 9).max_entries, 500_000)

    def test_max_candidates_ceiling(self):
        self.assertEqual(spec(max_candidates=10 ** 9).max_candidates, 50_000)

    def test_max_matches_ceiling(self):
        self.assertEqual(spec(max_matches=10 ** 9).max_matches, 20_000)

    def test_matches_per_file_ceiling(self):
        self.assertEqual(spec(matches_per_file=999).matches_per_file, 20)

    def test_column_rows_ceiling(self):
        self.assertEqual(spec(column_rows=999).column_rows, 50)

    def test_max_scan_bytes_ceiling(self):
        self.assertEqual(spec(max_scan_bytes=10 ** 12).max_scan_bytes, 1 << 30)

    def test_timeout_goes_through_downloads_clamp(self):
        self.assertEqual(spec(timeout=5).timeout, 30)
        self.assertEqual(spec(timeout=10 ** 6).timeout, 3600)
        self.assertIn('clamped_timeout', spec(timeout=5).clamped)

    def test_term_length_rejected_not_clamped(self):
        """term 静默截断会让用户查到完全不同的东西，所以是报错不是钳位。"""
        with self.assertRaises(contracts.SearchSpecError) as ctx:
            spec(mode='content', term='x' * 201)
        self.assertEqual(ctx.exception.field, 'term')

    def test_roots_count_rejected_not_clamped(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(roots=[f'/p{i}' for i in range(21)])

    def test_non_integer_rejected(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(workers='lots')


class DepthTests(SimpleTestCase):
    def test_self_maps_to_zero(self):
        self.assertEqual(spec(depth='self').effective_max_depth(), 0)

    def test_children_maps_to_one(self):
        self.assertEqual(spec(depth='children').effective_max_depth(), 1)

    def test_all_means_unlimited(self):
        self.assertIsNone(spec(depth='all').effective_max_depth())

    def test_custom_requires_value(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(depth='custom')

    def test_custom_hard_capped(self):
        self.assertEqual(spec(depth='custom', max_depth=999)
                         .effective_max_depth(), 64)

    def test_custom_rejects_non_positive(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(depth='custom', max_depth=0)


class NormalisationTests(SimpleTestCase):
    def test_roots_normalised_and_deduped(self):
        self.assertEqual(spec(roots=['/a/b/', '/a/b', '/a']).roots,
                         ['/a/b', '/a'])

    def test_root_must_be_absolute(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(roots=['relative/path'])

    def test_root_with_parent_ref_rejected(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(roots=['/a/../b'])

    def test_dates_accept_two_formats(self):
        self.assertEqual(spec(modified_after='2026-09-01T00:00')
                         .modified_after.month, 9)
        self.assertIsNotNone(spec(modified_after='2026-09-01').modified_after)

    def test_bad_date_rejected(self):
        with self.assertRaises(contracts.SearchSpecError) as ctx:
            spec(modified_after='9月1号')
        self.assertEqual(ctx.exception.field, 'modified_after')

    def test_blank_optional_strings_become_none(self):
        self.assertIsNone(spec(name_pattern='   ').name_pattern)

    def test_prune_dirs_stripped_and_empties_dropped(self):
        self.assertEqual(spec(prune_dirs=[' *backup* ', '', '  ']).prune_dirs,
                         ['*backup*'])

    def test_inverted_size_bounds_rejected(self):
        with self.assertRaises(contracts.SearchSpecError):
            spec(min_size=100, max_size=50)
