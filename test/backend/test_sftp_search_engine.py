"""引擎选择谓词（spec §3.3）。

它存在的全部理由是：**同一个查询在有无 grep 的两台服务器上必须给出同一个结果集**。
所以这里钉的是「什么情况必须回落 client」，不是「grep 能不能跑」。

跑法：python manage.py test test.backend.test_sftp_search_engine
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

from django.test import SimpleTestCase  # noqa: E402

from apps.sftp.search import contracts, engine  # noqa: E402

OK = engine.ProbeResult(has_grep=True, has_find_xargs=True, path_mapping_ok=True)


def spec(**over):
    base = {'roots': ['/d'], 'mode': 'content', 'term': 'ShadowReg2'}
    base.update(over)
    return contracts.parse_spec(base)


def name_of(s):
    return engine.select_engine(s, OK)[0]


class GrepEligibleTests(SimpleTestCase):
    def test_plain_substring(self):
        self.assertEqual(name_of(spec()), 'grep')

    def test_ascii_whole_word(self):
        """整词在 ASCII 上两档语义一致（scanners 按 [A-Za-z0-9_] 判边界）。"""
        self.assertEqual(name_of(spec(matching='whole_word')), 'grep')

    def test_time_filter_without_xargs_probe_falls_back(self):
        probe = engine.ProbeResult(has_grep=True, has_find_xargs=False,
                                   path_mapping_ok=True)
        self.assertEqual(
            engine.select_engine(spec(modified_after='2026-09-01'), probe)[0],
            'client')

    def test_time_filter_with_full_probe_uses_grep(self):
        self.assertEqual(name_of(spec(modified_after='2026-09-01')), 'grep')

    def test_name_pattern_does_not_block_grep(self):
        self.assertEqual(name_of(spec(name_pattern='*RT*.csv')), 'grep')


class MustFallBackTests(SimpleTestCase):
    CASES = [
        ('仅文件名模式', {'mode': 'name'}),
        ('列值模式', {'mode': 'column', 'column_name': 'ShadowReg2'}),
        ('模糊匹配无原语', {'matching': 'fuzzy'}),
        ('非 ASCII 词会静默漏 GBK 文件', {'term': '漏电电流'}),
        ('每目录一个无原语', {'one_per_folder': True}),
        ('仅列不扫不必动用 grep', {'stop_after_listing': True}),
        ('用户显式关掉加速', {'allow_server_grep': False}),
    ]

    def test_each_case_forces_client(self):
        for label, over in self.CASES:
            with self.subTest(label):
                base = {'mode': 'content', 'term': 'ShadowReg2'}
                base.update(over)
                self.assertEqual(name_of(spec(**base)), 'client',
                                 f'{label} 必须回落 client')

    def test_reason_always_non_empty(self):
        """回落必须带原因，前端要显示——不能让人猜这次是哪档跑的。"""
        for label, over in self.CASES:
            base = {'mode': 'content', 'term': 'ShadowReg2'}
            base.update(over)
            _name, reason = engine.select_engine(spec(**base), OK)
            with self.subTest(label):
                self.assertTrue(reason.strip())


class ProbeFailureTests(SimpleTestCase):
    def test_no_grep_binary(self):
        probe = engine.ProbeResult(False, False, False, '服务器上没有可用的 grep')
        name, reason = engine.select_engine(spec(), probe)
        self.assertEqual(name, 'client')
        self.assertIn('服务器上没有可用的 grep', reason)

    def test_chroot_mapping_mismatch_blocks_grep(self):
        """SFTP 常 chroot：同一路径字符串在 shell 侧可能不存在，
        不验就会 grep 空路径、返回 0 命中、用户以为真没有。"""
        probe = engine.ProbeResult(True, True, False, engine.PATH_MAPPING_MSG)
        self.assertEqual(engine.select_engine(spec(), probe)[0], 'client')

    def test_grep_without_mapping_probe_is_still_unusable(self):
        probe = engine.ProbeResult(True, True, False)
        self.assertFalse(probe.usable)
        _name, reason = engine.select_engine(spec(), probe)
        self.assertTrue(reason.strip(), '无 reason 的不可用也必须给出可显示的话')
