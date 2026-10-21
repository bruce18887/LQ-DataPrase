"""T1：内存预算公式、env 覆盖、水位与系统快照。"""
import logging
import os
import sys
from unittest import mock

from django.test import SimpleTestCase

from apps.common import memory

GB = 1024 ** 3
MB = 1024 ** 2

# 系统快照全空：让「空闲 commit < budget」那条 warning 不可能出现，
# 使 assertLogs / 日志输出只反映被测逻辑本身。
_NO_SYSTEM = {
    'total_bytes': None,
    'available_bytes': None,
    'commit_used_bytes': None,
    'commit_limit_bytes': None,
}


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
             mock.patch.object(memory, 'system_memory_snapshot',
                              return_value=dict(_NO_SYSTEM)), \
             mock.patch.dict(os.environ, {'LQDP_MEMORY_BUDGET_MB': 'big'}):
            memory.reset_budget_for_tests()
            with self.assertLogs('apps.common.memory', level='WARNING') as logs:
                plan = memory.get_budget()
        self.assertEqual(plan.budget_bytes, 8 * GB)
        self.assertTrue(
            any('LQDP_MEMORY_BUDGET_MB' in line for line in logs.output),
            f'warning 未点名变量名: {logs.output}',
        )

    def test_env_override_and_cache_override(self):
        with mock.patch.object(memory, 'total_ram_bytes', return_value=16 * GB), \
             mock.patch.object(memory, 'system_memory_snapshot',
                              return_value=dict(_NO_SYSTEM)), \
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


class EnvIntTests(SimpleTestCase):
    """批 2 用 env_int 夹取 1–8 与 0–60；越界/非整数必须有钉住的行为。"""

    def test_minimum_and_maximum_clamp(self):
        with mock.patch.dict(os.environ, {'LQDP_TEST_INT': '0'}):
            self.assertEqual(
                memory.env_int('LQDP_TEST_INT', 5, minimum=1, maximum=8), 1)
        with mock.patch.dict(os.environ, {'LQDP_TEST_INT': '99'}):
            self.assertEqual(
                memory.env_int('LQDP_TEST_INT', 5, minimum=1, maximum=8), 8)

    def test_non_integer_falls_back_with_warning(self):
        with mock.patch.dict(os.environ, {'LQDP_TEST_INT': 'big'}):
            with self.assertLogs('apps.common.memory', level='WARNING') as logs:
                value = memory.env_int(
                    'LQDP_TEST_INT', 5, minimum=1, maximum=8)
        self.assertEqual(value, 5)
        self.assertTrue(
            any('LQDP_TEST_INT' in line and '不是整数' in line
                for line in logs.output),
            logs.output,
        )

    def test_unset_uses_default_and_default_is_clamped(self):
        with mock.patch.dict(os.environ, {'LQDP_TEST_INT': ''}):
            self.assertEqual(
                memory.env_int('LQDP_TEST_INT', 5, minimum=1, maximum=8), 5)
        with mock.patch.dict(os.environ, {'LQDP_TEST_INT': '99'}):
            self.assertEqual(
                memory.env_int('LQDP_TEST_INT', 99, minimum=1, maximum=8), 8)


class SnapshotTests(SimpleTestCase):
    def setUp(self):
        memory.reset_budget_for_tests()
        self.addCleanup(memory.reset_budget_for_tests)
        # 总 RAM 与系统 commit 都打桩：快照测试不该因本机实际余量而打印
        # 「空闲 commit < 预算」这类与断言无关的 warning。
        ram = mock.patch.object(memory, 'total_ram_bytes', return_value=16 * GB)
        ram.start()
        self.addCleanup(ram.stop)
        system = mock.patch.object(memory, 'system_memory_snapshot',
                                   return_value=dict(_NO_SYSTEM))
        system.start()
        self.addCleanup(system.stop)

    def test_snapshot_marks_unavailable_level_as_none(self):
        with mock.patch.object(memory, '_process_rss_bytes', return_value=None):
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


class StartupLogTests(SimpleTestCase):
    """启动预算行必须真的可见：logger 级别来自真实 settings，记录走 handler。"""

    def test_memory_logger_effective_level_is_info(self):
        logger = logging.getLogger('apps.common.memory')
        self.assertEqual(logger.getEffectiveLevel(), logging.INFO)
        self.assertFalse(logger.propagate)

    def test_log_plan_emits_budget_line(self):
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logger = logging.getLogger('apps.common.memory')
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)

        plan = memory.compute_budget(16 * GB)
        with mock.patch.object(memory, 'system_memory_snapshot',
                               return_value=dict(_NO_SYSTEM)):
            memory._log_plan(plan)

        messages = [record.getMessage() for record in records]
        self.assertTrue(
            any(message.startswith('内存预算:') for message in messages),
            messages,
        )


class MemoryErrorHandlerTests(SimpleTestCase):
    def _payload(self, exc, path='/api/v1/analysis/histogram/'):
        from types import SimpleNamespace
        from apps.common.exceptions import custom_exception_handler
        return custom_exception_handler(exc, {
            'request': SimpleNamespace(path=path),
        })

    def test_memory_error_maps_to_503_and_clears_cache(self):
        from unittest import mock
        before = memory.oom_events()
        with mock.patch(
                'apps.datafiles.services.clear_parse_cache') as clear, \
                self.assertLogs('apps.common.exceptions', level='ERROR'):
            response = self._payload(MemoryError('boom'))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'out_of_memory')
        self.assertIn('内存不足', response.data['message'])
        self.assertEqual(response['Retry-After'], '5')
        self.assertEqual(response.data['detail']['path'],
                         '/api/v1/analysis/histogram/')
        clear.assert_called_once()
        self.assertEqual(memory.oom_events(), before + 1)

    def test_clear_cache_failure_still_returns_503_and_counts_oom(self):
        """清缓存自身再抛 MemoryError 时，503 信封与 OOM 记账都必须保住。"""
        before = memory.oom_events()
        with mock.patch(
                'apps.datafiles.services.clear_parse_cache',
                side_effect=MemoryError('again')) as clear, \
                self.assertLogs('apps.common.exceptions', level='ERROR') as logs:
            response = self._payload(MemoryError('boom'))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data, {
            'code': 'out_of_memory',
            'message': '服务器内存不足，请关闭其他任务后重试',
            'detail': {'path': '/api/v1/analysis/histogram/'},
        })
        self.assertEqual(response['Retry-After'], '5')
        clear.assert_called_once()
        self.assertEqual(memory.oom_events(), before + 1)
        self.assertTrue(any('clear_parse_cache' in line for line in logs.output))

    def test_memory_error_survives_side_effect_import_failure(self):
        """懒导入自身失败时跳过副作用，503 信封仍必须返回。"""
        import builtins
        real_import = builtins.__import__

        def failing_import(name, *args, **kwargs):
            if name == 'apps.datafiles.services':
                raise ImportError('simulated import failure')
            return real_import(name, *args, **kwargs)

        before = memory.oom_events()
        with mock.patch('builtins.__import__', side_effect=failing_import), \
                self.assertLogs('apps.common.exceptions', level='ERROR') as logs:
            response = self._payload(MemoryError('boom'))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data, {
            'code': 'out_of_memory',
            'message': '服务器内存不足，请关闭其他任务后重试',
            'detail': {'path': '/api/v1/analysis/histogram/'},
        })
        self.assertEqual(response['Retry-After'], '5')
        self.assertEqual(memory.oom_events(), before)
        self.assertTrue(any('imports failed' in line for line in logs.output),
                        logs.output)

    def test_other_exceptions_still_500(self):
        with self.assertLogs('apps.common.exceptions', level='ERROR'):
            response = self._payload(ValueError('boom'))
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data['code'], 'internal_error')
