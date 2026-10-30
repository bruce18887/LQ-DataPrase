"""批次报告载荷的判据：``compute_batch_yield_data`` 不为无人读的分区付账。

背景（计划 ``docs/superpowers/plans/2026-10-28-backend-perf-remediation.md`` Task D3）。
「一次取全」那半条住在 ``test/backend/test_batch_report_fetch.py``，共享道具在
``test/backend/batch_report_fixtures.py``。

1. Step 1 复核（2026-10-30 实测，证据口径见下面「消费方」段，删任何东西前重跑一遍即可复核，
   勿整读前端）：``trend_data`` / ``bin_distribution`` / ``bin_table_data`` /
   ``bin_site_columns`` 的唯一读方是 ``apps/export/html_report/batch.py``；
   ``site_pass_data`` **谁都不读**（前端那两处命中是 ``batchAggregation.ts`` 描述「同构」的
   注释文字，不是读取）。⇒ 五把 key 里四把收进 HTML 开关后面，``site_pass_data`` 整个删掉。
   键集合判据的 ``msg=`` 用 ``batch_report_fixtures.PARTITION_HISTORY``：这几条红了的第一件事
   是去问「谁读它」，不是把 key 加回来。

2. Step 3 的后半条（2026-10-30 审查指出当时只落到了 JSON 分支）：趋势输入
   ``file_data_list`` 带**已算好的** ``bin_stats``/``total`` 而**不持有 ``df``**。
   改前 HTML 分支实测每文件 2 趟全量 bin 统计（``services`` 1 + ``trends`` 1）、
   DataFrame 峰值驻留 2；现在两分支同为 **1 趟 / 界 1**，于是
   ``for_html_report=False`` 省的只是那四把 key 本身的构造与体积。分支归属写在
   ``test_html_trend_input_carries_precomputed_bin_stats_and_no_frame`` /
   ``test_html_branch_retains_no_dataframe_as_performance_tripwire`` /
   ``test_both_branches_run_one_bin_statistics_pass_per_file_as_performance_tripwire``
   三条的 docstring 里，别再用「省一趟全量统计」这种只对旧状态成立的措辞解释 JSON 分支。

   「消费方」（核对口径）：

   - ``grep -rn "trend_data|bin_distribution|site_pass_data|bin_table_data|bin_site_columns" frontend/src``
     ⇒ ``trend_data`` 0、``bin_distribution`` 0、``site_pass_data`` 2（均为注释）、
     ``bin_table_data`` 10、``bin_site_columns`` 9。后两键的命中分属两个**别的**生产者：
     ``frontend/src/pages/dashboard/DashboardPage.vue`` 里读 ``analysisApi.getDashboard()``
     响应的 ``d.bin_table_data`` 那两处（生产者是 ``apps/dashboard/services.py`` 里产出同名键
     的那一段），以及 ``frontend/src/pages/dashboard/components/batch/BatchBinSection.vue``
     读前端自己 ``aggregateBinSiteTable()``（``frontend/src/utils/batchAggregation.ts``）
     返回值的 ``phaseBinSite.bin_table_data`` 那一处；批次 JSON 载荷那个同名键没有任何读点
     （``frontend/e2e`` 对五把 key **0 命中**）。
   - 引用一律**按符号不按行号**（教训 2026-10-13「产品注释里的行号锚点会漂」）：
     上面这几处改名或改位置时本段要跟着改，但一个把行号写死的锚点在漂了之后仍然「看着对」。

runner: ``manage.py test test.backend.test_batch_report_payload``
"""

import gc
import weakref
from unittest import mock

from apps.analysis.services.statistics import trends as trends_module
from apps.batch_report import services as batch_services
from apps.batch_report.services import compute_batch_yield_data
from test.backend.batch_report_fixtures import (
    HTML_EXTRA_KEYS, JSON_KEYS, PARTITION_HISTORY, _BatchFixture, _df, _meta,
)


class BatchYieldJsonBranchTests(_BatchFixture):
    def test_json_payload_key_set_drops_four_partitions(self):
        out = compute_batch_yield_data(self.user, 'D3')
        self.assertEqual(set(out), JSON_KEYS, msg=PARTITION_HISTORY)

    def test_json_branch_never_computes_yield_trend(self):
        """spied on the consuming module's binding（同分支先例
        ``test_multi_lot_param_scan.py``：patch 实际消费模块的名字）。"""
        with mock.patch.object(
                batch_services, 'compute_yield_trend',
                side_effect=AssertionError('JSON 分支不该算趋势')) as trend:
            compute_batch_yield_data(self.user, 'D3')
        trend.assert_not_called()

    def test_json_branch_builds_no_bin_site_table(self):
        with mock.patch.object(
                batch_services, 'aggregate_bin_site_table',
                side_effect=AssertionError('JSON 分支不该凑 Bin×Site 批级交叉表')) as agg:
            compute_batch_yield_data(self.user, 'D3')
        agg.assert_not_called()

    def test_json_branch_retains_no_dataframe_as_performance_tripwire(self):
        """性能绊线（**JSON 分支那份**，红了只改本条，别动上面那几条契约判据）。

        钉的是**峰值驻留**而不是「调用结束后有没有泄漏」：改前那条
        ``file_data_list`` 会把批次内每个文件的 DataFrame 一路攒到函数返回，
        所以判据是「第 k 次取帧时，前面那些帧还剩几个活着」。
        HTML 分支那份由同名的 ``test_html_branch_retains_no_dataframe_..._tripwire``
        钉（2026-10-30 补 Step 3 后半条之前只有本条成立，界也确实是靠分支区分的）。

        - 界内上界是 **1**：服务循环里那个 ``df`` 局部量在第 k 次调用时尚未被子 k−1
          的帧放手（赋值还没完成），这一份是既有语义、不是本任务要消掉的账。
        - 攒 ``file_data_list``（带 ``df`` 的那种）会给出 ``0,1,2,…`` ⇒ 当场转红。
        - 判据对象是**服务自己持有什么**：解析函数在这里是桩，真站点的解析缓存本来
          就按预算驻留帧，不属本条口径。钉的是 DataFrame **对象**存活，不是字节数
          （HTML 分支合法地留每文件的 ``bin_stats`` 计数账，那不该触这条）。
        """
        refs = []
        live_at_call = []

        def _fresh_frame(_file_id, _owner_pk, _df_obj):
            gc.collect()
            live_at_call.append(sum(1 for ref in refs if ref() is not None))
            frame = _df()
            refs.append(weakref.ref(frame))
            return frame, _meta(), 'CTA8290D'

        with mock.patch.object(batch_services, 'get_cached_parsed_file',
                               side_effect=_fresh_frame):
            payload = compute_batch_yield_data(self.user, 'D3')
        self.assertEqual(len(refs), self.file_count, '前置：每文件各发一帧')
        self.assertEqual(
            max(live_at_call), 1,
            f'批次循环同时驻留 {max(live_at_call)} 个 DataFrame（界 1，即上一轮的局部量）：'
            f'取帧时的存活序列 {live_at_call} ⇒ 又在攒 file_data_list')
        del payload
        gc.collect()
        alive = [ref() for ref in refs if ref() is not None]
        self.assertEqual(alive, [], 'JSON 分支返回后仍持有批次文件的 DataFrame')

    def test_json_kept_keys_equal_the_html_payload_values(self):
        """裁剪是外科式的：留下的 9 把 key 与 HTML 分支那份逐值相等。"""
        json_out = compute_batch_yield_data(self.user, 'D3')
        html_out = compute_batch_yield_data(self.user, 'D3', for_html_report=True)
        self.assertEqual(
            sorted(json_out), sorted(JSON_KEYS),
            msg=f'JSON 分支的键集合被改动：前端会少读或多读。{PARTITION_HISTORY}')
        for key in JSON_KEYS:
            self.assertEqual(json_out[key], html_out[key], f'{key} 两分支取值不同')

    def test_phases_still_carry_per_bin_site_data(self):
        """前端 ``aggregateBinSiteTable`` 吃 ``phase['bin_info'][i]['sites']``：
        删批次级交叉表不能把每阶段的 sites 一起删掉。"""
        out = compute_batch_yield_data(self.user, 'D3')
        self.assertEqual(out['sorted_sites'], ['Site1', 'Site2'])
        self.assertEqual(
            [b['sites'] for b in out['phases'][0]['bin_info']],
            [{'Site1': 1, 'Site2': 2}, {'Site1': 1, 'Site2': 0}],
            '每阶段 bin_info[].sites 被删：前端 BatchBinSection 的 Bin×Site 表会空')


class BatchYieldHtmlBranchTests(_BatchFixture):
    def test_html_branch_computes_yield_trend_exactly_once(self):
        real = batch_services.compute_yield_trend
        with mock.patch.object(
                batch_services, 'compute_yield_trend',
                side_effect=lambda lst: real(lst)) as trend:
            out = compute_batch_yield_data(self.user, 'D3', for_html_report=True)
        self.assertEqual(trend.call_count, 1)
        self.assertEqual(len(out['trend_data']['trend_data']), self.file_count)

    def test_html_payload_carries_report_partitions_and_drops_site_pass_data(self):
        out = compute_batch_yield_data(self.user, 'D3', for_html_report=True)
        self.assertEqual(set(out), JSON_KEYS | HTML_EXTRA_KEYS, msg=PARTITION_HISTORY)
        self.assertNotIn('site_pass_data', out)
        self.assertTrue(out['bin_table_data'], 'HTML 的 Bin×Site 表不能空')
        self.assertEqual(out['bin_site_columns'], ['Site1', 'Site2'])

    def test_html_trend_input_carries_precomputed_bin_stats_and_no_frame(self):
        """``compute_yield_trend`` 的入参形状（计划 Step 3 的后半条，两分支都必须成立）。

        带**已算好的** ``bin_stats``/``total``、**不带 ``df``/``metadata``**：
        ``apps/analysis/services/statistics/trends.py`` 的 ``_bin_stats_and_total``
        只认这份形状（没有按 ``df`` 现算的 fallback 可走，反垫片判据在
        ``test/backend/test_bin_trend_yield.py`` 的
        ``test_frame_shape_is_rejected_there_is_no_second_dialect``）⇒ 这里不会再跑
        第二趟全量 bin 统计，也就没有理由把批次里每个文件的 DataFrame 攒在一个列表里
        （那正是它此前唯一需要 ``df`` 的地方）。
        """
        real = batch_services.compute_yield_trend
        seen = []

        def spy(lst):
            seen.extend(lst)
            return real(lst)

        with mock.patch.object(batch_services, 'compute_yield_trend', side_effect=spy):
            compute_batch_yield_data(self.user, 'D3', for_html_report=True)
        self.assertEqual(len(seen), self.file_count, '趋势输入必须逐文件一份')
        self.assertEqual(
            {frozenset(entry) for entry in seen},
            {frozenset({'bin_stats', 'total', 'file_id', 'filename', 'timestamp'})},
            '趋势输入的键集合漂了：多一个 df 就把整批帧留在手上')
        for entry in seen:
            self.assertNotIn('df', entry, '趋势输入又带上 DataFrame 了')
            self.assertTrue(entry['bin_stats'], 'bin_stats 必须是那份非空统计')

    def test_html_branch_retains_no_dataframe_as_performance_tripwire(self):
        """性能绊线（HTML 分支那份，红了只改本条）：界 1，与 JSON 分支同一个界。

        Step 3 前半条（只给 JSON 分支省掉 ``file_data_list``）留下的账就在这儿：
        ``for_html_report=True`` 时那份列表**仍然**按 ``df`` 攒帧 ⇒ 峰值驻留实测 2
        （上一轮的局部量 + 列表里那一份）。把输入换成 ``bin_stats``/``total`` 之后
        两分支同界，本条把 HTML 那侧也钉住，别让「只剩 JSON 分支成立」的说法漂回散文。
        界值取 1 的理由与 ``test_json_branch_retains_no_dataframe_as_performance_tripwire``
        相同（循环里的局部 ``df`` 到下一次赋值才放手，那是既有语义）。
        """
        refs = []
        live_at_call = []

        def _fresh_frame(_file_id, _owner_pk, _df_obj):
            gc.collect()
            live_at_call.append(sum(1 for ref in refs if ref() is not None))
            frame = _df()
            refs.append(weakref.ref(frame))
            return frame, _meta(), 'CTA8290D'

        with mock.patch.object(batch_services, 'get_cached_parsed_file',
                               side_effect=_fresh_frame):
            payload = compute_batch_yield_data(
                self.user, 'D3', for_html_report=True)
        self.assertEqual(len(refs), self.file_count, '前置：每文件各发一帧')
        self.assertEqual(
            max(live_at_call), 1,
            f'HTML 分支同时驻留 {max(live_at_call)} 个 DataFrame（界 1）：'
            f'存活序列 {live_at_call} ⇒ 趋势输入又开始攒帧')
        del payload
        gc.collect()
        alive = [ref() for ref in refs if ref() is not None]
        self.assertEqual(alive, [], 'HTML 分支返回后仍持有批次文件的 DataFrame')

    def test_both_branches_run_one_bin_statistics_pass_per_file_as_performance_tripwire(self):
        """性能绊线（两分支同判）：每文件只有**一趟**全量 bin 统计，红了只改本条。

        计划 Step 3 点名的重复计算落点是 ``trends.py`` 的 ``_bin_stats_and_total`` ——
        它先前有一条「没带 ``bin_stats`` 就按 ``df`` 现算」的 fallback，与
        ``services.py`` 循环里那次是同一个计算。改前 HTML 分支实测每文件 2 次
        （``services`` 1 + ``trends`` 1），JSON 分支 1 次。那条 fallback 连同垫片一起
        删掉了（2026-10-30 审查 Important 1），所以 ``trends`` 这一趟**必须**是 0：
        把它加回来 ⇒ 本条与 ``test_bin_trend_yield.py`` 的反垫片用例双双转红。
        口径：数的是**函数调用次数**，按「实际消费模块的绑定」分别 patch（R6③），
        不数行数、不比耗时 ⇒ 换解析夹具不会漂。
        """
        for for_html in (False, True):
            with self.subTest(for_html_report=for_html):
                calls = []
                real_services = batch_services.calculate_fail_bin_statistics
                real_trends = trends_module.calculate_fail_bin_statistics

                def counting(where, fn):
                    def inner(df, metadata, *args, **kwargs):
                        calls.append(where)
                        return fn(df, metadata, *args, **kwargs)
                    return inner

                with mock.patch.object(batch_services, 'get_cached_parsed_file',
                                       return_value=(_df(), _meta(), 'CTA8290D')), \
                     mock.patch.object(batch_services, 'calculate_fail_bin_statistics',
                                       side_effect=counting('services', real_services)), \
                     mock.patch.object(trends_module, 'calculate_fail_bin_statistics',
                                       side_effect=counting('trends', real_trends)):
                    compute_batch_yield_data(self.user, 'D3',
                                             for_html_report=for_html)
                self.assertEqual(
                    calls.count('trends'), 0,
                    f'for_html_report={for_html} 时 trends 侧又跑了 {calls.count("trends")} 趟'
                    '全量 bin 统计：bin_stats 没被带下去（每文件第二趟 = 本任务要消掉的账）')
                self.assertEqual(
                    calls.count('services'), self.file_count,
                    f'for_html_report={for_html} 时 services 侧跑了 '
                    f'{calls.count("services")} 次，期望每文件恰好 1 次')

    def test_batch_yield_data_endpoint_still_200_and_json_shaped(self):
        resp = self.client.get(
            '/api/v1/batch-report/batch_yield_data/', {'batch_name': 'D3'})
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        self.assertEqual(set(resp.data), JSON_KEYS, msg=PARTITION_HISTORY)
