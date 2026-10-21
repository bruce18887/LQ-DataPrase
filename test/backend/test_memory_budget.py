"""T1：内存预算公式、env 覆盖、水位与系统快照。"""
import os
import sys
from unittest import mock

from django.test import SimpleTestCase

from apps.common import memory

GB = 1024 ** 3
MB = 1024 ** 2


class BudgetMathTests(SimpleTestCase):
    def test_default_budget_is_half_ram_capped(self):
        plan = memory.compute_budget(16 * GB)
        self.assertEqual(plan.budget_bytes, 8 * GB)
        self.assertEqual(plan.jobs_budget_bytes, 2 * GB)
        self.assertEqual(plan.web_budget_bytes, 6 * GB)
        self.assertEqual(plan.cache_budget_bytes, 1536 * MB)

    def test_8gb_machine_cache_scales_with_web_budget(self):
        plan = memory.compute_budget(8 * GB)
        self.assertEqual(plan.budget_bytes, 4 * GB)
        self.assertEqual(plan.jobs_budget_bytes, int(4 * GB * 0.4))
        self.assertEqual(plan.web_budget_bytes, 4 * GB - int(4 * GB * 0.4))
        self.assertEqual(plan.cache_budget_bytes, int(plan.web_budget_bytes * 0.6))

    def test_small_ram_hits_floor(self):
        self.assertEqual(memory.compute_budget(2 * GB).budget_bytes, 1536 * MB)

    def test_large_ram_uses_default_cap(self):
        self.assertEqual(memory.compute_budget(64 * GB).budget_bytes, 8 * GB)

    def test_explicit_budget_can_exceed_default_cap(self):
        plan = memory.compute_budget(32 * GB, budget_mb=16384)
        self.assertEqual(plan.budget_bytes, 16 * GB)
        self.assertEqual(plan.jobs_budget_bytes, 2 * GB)
        self.assertEqual(plan.web_budget_bytes, 14 * GB)
        self.assertEqual(plan.cache_budget_bytes, 1536 * MB)

    def test_cache_env_zero_disables_cache(self):
        self.assertEqual(memory.compute_budget(16 * GB, cache_mb=0).cache_budget_bytes, 0)

    def test_cache_env_cannot_exceed_web_budget(self):
        plan = memory.compute_budget(16 * GB, cache_mb=99999)
        self.assertEqual(plan.cache_budget_bytes, plan.web_budget_bytes)

    def test_level_thresholds_and_unavailable(self):
        plan = memory.compute_budget(16 * GB)
        web = plan.web_budget_bytes
        self.assertEqual(plan.level(int(web * 0.74)), 'normal')
        self.assertEqual(plan.level(int(web * 0.75)), 'soft')
        self.assertEqual(plan.level(int(web * 0.90)), 'hard')
        self.assertIsNone(plan.level(None))


class EnvTests(SimpleTestCase):
    def tearDown(self):
        memory.reset_budget_for_tests()

    def test_invalid_budget_env_falls_back_with_warning(self):
        with mock.patch.object(memory, 'total_ram_bytes', return_value=16 * GB), \
             mock.patch.dict(os.environ, {'LQDP_MEMORY_BUDGET_MB': 'big'}):
            memory.reset_budget_for_tests()
            with self.assertLogs('apps.common.memory', level='WARNING'):
                plan = memory.get_budget()
        self.assertEqual(plan.budget_bytes, 8 * GB)

    def test_env_override_and_cache_override(self):
        with mock.patch.object(memory, 'total_ram_bytes', return_value=16 * GB), \
             mock.patch.dict(os.environ, {
                 'LQDP_MEMORY_BUDGET_MB': '4096',
                 'LQDP_PARSE_CACHE_MB': '512',
             }):
            memory.reset_budget_for_tests()
            plan = memory.get_budget()
        self.assertEqual(plan.budget_bytes, 4 * GB)
        self.assertEqual(plan.cache_budget_bytes, 512 * MB)

    def test_missing_psutil_falls_back_to_env_total(self):
        with mock.patch.dict(sys.modules, {'psutil': None}), \
             mock.patch.dict(os.environ, {'LQDP_TOTAL_RAM_MB': '2048'}):
            with self.assertLogs('apps.common.memory', level='WARNING'):
                self.assertEqual(memory.total_ram_bytes(), 2 * GB)


class SnapshotTests(SimpleTestCase):
    def setUp(self):
        memory.reset_budget_for_tests()

    def tearDown(self):
        memory.reset_budget_for_tests()

    def test_snapshot_marks_unavailable_level_as_none(self):
        with mock.patch.object(memory, '_process_rss_bytes', return_value=None), \
             mock.patch.object(memory, 'system_memory_snapshot', return_value={
                 'total_bytes': None, 'available_bytes': None,
                 'commit_used_bytes': None, 'commit_limit_bytes': None,
             }):
            snap = memory.memory_snapshot(None)
        self.assertIsNone(snap['used_ratio'])
        self.assertIsNone(snap['level'])
        self.assertEqual(set(snap['system']), {
            'total_bytes', 'available_bytes',
            'commit_used_bytes', 'commit_limit_bytes',
        })

    def test_oom_counter_increments(self):
        before = memory.oom_events()
        memory.record_oom()
        self.assertEqual(memory.oom_events(), before + 1)
