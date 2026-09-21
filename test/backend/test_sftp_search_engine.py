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

    def test_modified_before_alone_also_requires_find_xargs(self):
        """只设**上界**同样算「带时间过滤」，要的是 find -newermt 那一级探测。

        与上一条配对才完整：上一条只测 ``modified_after``，实现里
        ``spec.modified_after or spec.modified_before`` 的后半截删掉也不会有测试变红，
        等于只界了窗口的一半。
        """
        probe = engine.ProbeResult(has_grep=True, has_find_xargs=False,
                                   path_mapping_ok=True)
        name, reason = engine.select_engine(spec(modified_before='2026-09-01'), probe)
        self.assertEqual(name, 'client')
        self.assertIn('find', reason)

    def test_modified_before_with_full_probe_uses_grep(self):
        """反向半边：探测齐备时只设上界也该能用 grep，别把回落写死。"""
        self.assertEqual(name_of(spec(modified_before='2026-09-01')), 'grep')

    def test_time_filter_with_full_probe_uses_grep(self):
        self.assertEqual(name_of(spec(modified_after='2026-09-01')), 'grep')

    def test_name_pattern_does_not_block_grep(self):
        self.assertEqual(name_of(spec(name_pattern='*RT*.csv')), 'grep')

    def test_limited_depth_still_uses_grep_when_unlimited(self):
        """正例半边：``depth='all'``（默认）不设深度闸，也就没什么可翻译的。"""
        self.assertEqual(name_of(spec(depth='all')), 'grep')


class DepthAndScopeFallbackTests(SimpleTestCase):
    """第四条件（深度）与翻译过程中新暴露的两条 scope 缺口。

    判据只有一条：**grep 拼不出与 walker 相同的结果集**。性能不在考虑范围内——
    前三条能翻成 grep 选项，``depth`` 翻不了（GNU grep 没有 ``--max-depth``），
    根目录撞剪枝模式则两条路都翻不动（walker 永远会进根目录，grep/find 会整棵跳过）。
    """

    def test_each_limited_depth_falls_back(self):
        for over in ({'depth': 'self'}, {'depth': 'children'},
                     {'depth': 'custom', 'max_depth': 2}):
            with self.subTest(**over):
                name, reason = engine.select_engine(spec(**over), OK)
                self.assertEqual(name, 'client', f'{over} 必须回落 client')
                self.assertIn('深度', reason)

    def test_root_matching_a_prune_pattern_falls_back(self):
        """根目录自身叫 ``backup`` 又剪 ``backup``：walker 照常进，grep 整棵跳过。"""
        name, reason = engine.select_engine(
            spec(roots=['/data/backup'], prune_dirs=['backup', 'cache']), OK)
        self.assertEqual(name, 'client')
        self.assertIn('根', reason)

    def test_hidden_root_falls_back(self):
        """dot 规则也作用于命令行上的根（实测 grep 3.0），故隐藏根同样必须回落。"""
        self.assertEqual(name_of(spec(roots=['/data/.snapshot'])), 'client')

    def test_root_with_pruned_component_deeper_down_still_uses_grep(self):
        """只有根的**最后一段**参与这条判定：中间层撞模式时两档都会进那个根。"""
        self.assertEqual(
            name_of(spec(roots=['/data/backup/lot12'], prune_dirs=['backup'])), 'grep')

    def test_prune_dirs_alone_do_not_block_grep(self):
        """前三条是「翻译」不是「回落」：只勾剪枝/汇总/dot 也必须能用 grep。"""
        self.assertEqual(
            name_of(spec(prune_dirs=['cache', '*bak*'], data_files_only=True)), 'grep')

    def test_name_pattern_with_data_only_needs_find_xargs(self):
        """``name_pattern`` ∩「仅数据文件」求交只有 find 分支能表达（``--include`` 是或）。"""
        probe = engine.ProbeResult(has_grep=True, has_find_xargs=False,
                                   path_mapping_ok=True)
        name, reason = engine.select_engine(spec(name_pattern='RT_*'), probe)
        self.assertEqual(name, 'client')
        self.assertIn('find', reason)

    def test_size_filter_without_find_xargs_falls_back(self):
        """大小过滤和深度无关，但它同样走 find 管道 → 探测缺 xargs 就不能留给 grep 档。

        原实现只在**有时间过滤**时要求 has_find_xargs，于是「只勾大小范围」的查询会
        拼出一条 find 命令发到没有 GNU find 的服务器上，靠退出码 2 才发现。
        """
        probe = engine.ProbeResult(has_grep=True, has_find_xargs=False,
                                   path_mapping_ok=True)
        self.assertEqual(engine.select_engine(spec(min_size=1024), probe)[0], 'client')

    def test_name_pattern_without_data_only_needs_no_find(self):
        """反例半边：不求交时 ``--include`` 一条就够，不该把 find 档拉进来当条件。"""
        probe = engine.ProbeResult(has_grep=True, has_find_xargs=False,
                                   path_mapping_ok=True)
        self.assertEqual(
            engine.select_engine(spec(name_pattern='RT_*', data_files_only=False),
                                 probe)[0], 'grep')


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


class ReasonPrecedenceTests(SimpleTestCase):
    """两侧同时不合格时，**spec 侧**必须赢——这是 ``select_engine`` 判断顺序的唯一理由。

    上面两个反例集各自留了另一侧为真：spec 侧全配「probe 通过」，probe 侧全配
    「spec 合格」，两者从未同时失败。把 ``not probe.usable`` 挪到函数第一行照样全绿，
    而这正是会害到用户的那种退化：非 ASCII 查询拿到一句「服务器上没有 grep」，真正
    的原因（会静默漏 GBK 文件）被藏掉，换台有 grep 的服务器就又被坑一遍。
    """

    CASES = [
        ('非 ASCII + probe 全红', {'term': '漏电电流'}, engine.NON_ASCII_GREP_MSG),
        ('模糊匹配 + probe 全红', {'matching': 'fuzzy'}, engine.FUZZY_UNSUPPORTED_MSG),
    ]

    def test_spec_side_reason_wins_over_probe_reason(self):
        probe = engine.ProbeResult(has_grep=False, has_find_xargs=False,
                                   path_mapping_ok=False,
                                   reason='服务器上没有可用的 grep')
        for label, over, expected in self.CASES:
            with self.subTest(label):
                name, reason = engine.select_engine(spec(**over), probe)
                self.assertEqual(name, 'client')
                self.assertEqual(reason, expected)
                self.assertNotIn('服务器上没有可用的 grep', reason)

    def test_chroot_mismatch_is_reported_when_spec_is_clean(self):
        """反向半边：spec 侧全合格时才轮到 probe.reason 出口，别把这条也写死成别的。"""
        probe = engine.ProbeResult(has_grep=True, has_find_xargs=True,
                                   path_mapping_ok=False,
                                   reason=engine.PATH_MAPPING_MSG)
        _name, reason = engine.select_engine(spec(), probe)
        self.assertEqual(reason, engine.PATH_MAPPING_MSG)
