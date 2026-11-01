"""批次报告载荷的判据：``compute_batch_yield_data`` 不为无人读的分区付账，
而 JSON 端点仍按 D3 之前（HEAD 的父提交 ``d203ca1^``）那 14 把键回包 —— 多回来的五把是
**类型正确的空占位**，不是旧数据。

背景（计划 ``docs/superpowers/plans/2026-10-28-backend-perf-remediation.md`` Task D3）。
「一次取全」那半条住在 ``test/backend/test_batch_report_fetch.py``，共享道具在
``test/backend/batch_report_fixtures.py``。

1. Step 1 复核（2026-10-30 实测，证据口径见下面「消费方」段，删任何东西前重跑一遍即可复核，
   勿整读前端）：``trend_data`` / ``bin_distribution`` / ``bin_table_data`` /
   ``bin_site_columns`` 的唯一读方是 ``apps/export/html_report/batch.py``；
   ``site_pass_data`` **谁都不读**（前端那两处命中是 ``batchAggregation.ts`` 描述「同构」的
   注释文字，不是读取）。⇒ D3 当时把五把 key 从 JSON 响应里删净（四把收进 HTML 开关后面、
   ``site_pass_data`` 整个删掉）。

   **2026-10-31 这批把 JSON 端点的键集合恢复成 D3 之前（``d203ca1^``）那 14 把**，因为
   「响应 JSON 键集合不变」是计划 Task D3 Step 2 与 Global Constraints 的硬口径，删键属契约
   变更、要前端同批 —— 而那批没动前端。恢复的是**键**，不是**账**：这五把在 JSON 分支是
   类型正确的空占位（``trend_data={}``、其余四把 ``[]``），一条计算都没接回来（两条 spy
   判据 ``test_json_branch_never_computes_yield_trend`` /
   ``test_json_branch_builds_no_bin_site_table`` 仍必须 ``not_called``）。所以
   ``JSON_COMPAT_KEYS`` 说的是形状，别把它读成「旧数据回来了」。四组键的名字与解释在
   ``batch_report_fixtures.py``（``JSON_KEYS`` / ``JSON_COMPAT_KEYS`` /
   ``JSON_RESPONSE_KEYS`` / ``HTML_EXTRA_KEYS``），键集合判据的 ``msg=`` 用
   ``PARTITION_HISTORY``：这几条红了的第一件事是分清**红的是哪一组**，不是把实值加回来。
   HTML 分支形状不变（13 把 = 9 真实 + 4 真算分区），``site_pass_data`` 两边都**不带实值**：
   JSON 那侧是空占位，HTML 那侧连键都没有（报告不读，不为 JSON 的形状兼容加无消费者的计算）。

2. Step 3 的后半条（2026-10-30 审查指出当时只落到了 JSON 分支）：趋势输入
   ``file_data_list`` 带**已算好的** ``bin_stats``/``total`` 而**不持有 ``df``**。
   改前 HTML 分支实测每文件 2 趟全量 bin 统计（``services`` 1 + ``trends`` 1）、
   DataFrame 峰值驻留 2；现在两分支同为 **1 趟 / 界 1**，于是
   ``for_html_report=False`` 省的只是那四把真算分区的构造与体积（兼容空键不记账）。分支归属写在
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
import json
import weakref
from unittest import mock

from apps.analysis.services.statistics import trends as trends_module
from apps.batch_report import services as batch_services
from apps.batch_report.services import compute_batch_yield_data
from test.backend.batch_report_fixtures import (
    HTML_EXTRA_KEYS, JSON_COMPAT_EMPTY_VALUES, JSON_COMPAT_KEYS, JSON_KEYS,
    JSON_RESPONSE_KEYS, PARTITION_HISTORY, _BatchFixture, _df, _meta,
)


class BatchYieldJsonBranchTests(_BatchFixture):
    def test_json_payload_key_set_is_the_head_shape_of_fourteen_keys(self):
        """JSON 端点键集合 = D3 之前那 14 把（9 真实 + 5 形状兼容空键）。"""
        out = compute_batch_yield_data(self.user, 'D3')
        self.assertEqual(set(out), JSON_RESPONSE_KEYS, msg=PARTITION_HISTORY)
        self.assertEqual(len(JSON_RESPONSE_KEYS), 14, '判据本身漂了：HEAD 的键集合是 14 把')

    def test_json_compat_keys_are_empty_placeholders_not_computed_data(self):
        """补回来的五把是**空占位**：这是形状兼容，不是旧数据逐值兼容。

        ``trend_data`` 在 HEAD 是 ``compute_yield_trend`` 的 dict、其余四把是 list ⇒
        类型必须一致（``{}`` / ``[]``），否则前端/调用方按类型取值照样炸。
        这几条 ``assertEqual`` 同时把「一把都没接上计算」钉住：本夹具里 HTML 分支那四把
        真算分区全是非空值（``site_pass_data`` 连 HTML 都不带），所以 JSON 那侧一旦给出
        任何非空值就是有人在算它 —— 上面那两条 ``not_called`` spy 从调用次数那一侧再夹一遍。
        """
        out = compute_batch_yield_data(self.user, 'D3')
        self.assertEqual(set(out) & JSON_COMPAT_KEYS, JSON_COMPAT_KEYS,
                         msg=PARTITION_HISTORY)
        for key in sorted(JSON_COMPAT_KEYS):
            self.assertEqual(
                out[key], JSON_COMPAT_EMPTY_VALUES[key],
                f'{key} 不再是空占位（期望 {JSON_COMPAT_EMPTY_VALUES[key]!r}，'
                f'实得 {out[key]!r}）：JSON 分支一把都不该计算')
            self.assertIs(type(out[key]), type(JSON_COMPAT_EMPTY_VALUES[key]),
                          f'{key} 的占位类型与 HEAD 实值的类型不一致：按类型取的调用方会炸')

    def test_json_compat_placeholders_are_fresh_per_call(self):
        """空占位必须**每次新建**：五把都是可变容器，共用一份模块级常量的话，任何一个
        调用方（或中间件、序列化前的加工）写脏一次，全站后续响应一起脏。"""
        first = compute_batch_yield_data(self.user, 'D3')
        second = compute_batch_yield_data(self.user, 'D3')
        for key in sorted(JSON_COMPAT_KEYS):
            self.assertIsNot(first[key], second[key],
                             f'{key} 的空占位在两次调用间是同一个对象（共享可变常量）')

    def test_json_branch_never_computes_yield_trend(self):
        """spied on the consuming module's binding（同分支先例
        ``test_multi_lot_param_scan.py``：patch 实际消费模块的名字）。

        2026-10-31 补回 ``trend_data`` **空占位**不构成豁免：键在、值为空，
        这条仍必须 ``not_called`` —— 否则「形状兼容」就地变成 D3 要消掉的那笔账。
        """
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
        """裁剪是外科式的：**只比 JSON_KEYS（9 把真实键）**与 HTML 分支那份逐值相等。

        兼容空键不在比较范围内 —— 那五把 JSON 侧恒为空、HTML 侧是真算值，本来就该不同；
        把它们拿进来比就是拿占位去冒充实值（判据也会当场假红）。
        """
        json_out = compute_batch_yield_data(self.user, 'D3')
        html_out = compute_batch_yield_data(self.user, 'D3', for_html_report=True)
        self.assertEqual(
            sorted(json_out), sorted(JSON_RESPONSE_KEYS),
            msg=f'JSON 分支的键集合被改动：前端会少读或多读。{PARTITION_HISTORY}')
        self.assertEqual(
            sorted(html_out), sorted(JSON_KEYS | HTML_EXTRA_KEYS),
            msg=f'HTML 分支的键集合被改动（不该为 JSON 的形状兼容多带 site_pass_data）。'
                f'{PARTITION_HISTORY}')
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
        """HTML 分支：13 把 = 9 真实 + 4 真算分区，**不带** ``site_pass_data``。

        2026-10-31 补回 JSON 那五把空占位时，HTML 这侧的形状**一个键都没跟着动**：
        ``site_pass_data`` 报告不读，为它把 JSON 的形状兼容传到 HTML 就是加一笔无消费者的
        计算/字段。这条同时是 ``build_batch_html_report`` 入口守卫的另一半判据 ——
        那边靠「带 ``site_pass_data`` ⇒ 这份是 JSON 形状」拦「忘了开开关」的载荷
        （``test_html_report_batch.py`` 的 ``test_json_shaped_payload_is_refused_not_rendered_empty``）。
        """
        out = compute_batch_yield_data(self.user, 'D3', for_html_report=True)
        self.assertEqual(set(out), JSON_KEYS | HTML_EXTRA_KEYS, msg=PARTITION_HISTORY)
        self.assertEqual(set(out), JSON_RESPONSE_KEYS - {'site_pass_data'},
                         'HTML 与 JSON 的键集合差应当恰好是 site_pass_data 这一把')
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
        """端点回包 = 14 把键，且**序列化之后**那五把兼容键仍然是空容器。

        只比 ``resp.data`` 不够：DRF 的渲染层才是前端真正看到的那一份 ⇒ 一并比
        ``json.loads(resp.content)``，键集合与空值都必须活着出网关。
        """
        resp = self.client.get(
            '/api/v1/batch-report/batch_yield_data/', {'batch_name': 'D3'})
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        self.assertEqual(set(resp.data), JSON_RESPONSE_KEYS, msg=PARTITION_HISTORY)
        body = json.loads(resp.content)
        self.assertEqual(set(body), JSON_RESPONSE_KEYS,
                         '序列化后键集合与 resp.data 不一致：前端拿到的就是 body 那份')
        for key in sorted(JSON_COMPAT_KEYS):
            self.assertEqual(body[key], JSON_COMPAT_EMPTY_VALUES[key],
                             f'{key} 经序列化后不再是空占位')
