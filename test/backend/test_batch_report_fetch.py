"""D3 前半条：``generate_report`` 的「一次取全」与 IN 分块（N 文件 ⇒ 1 条 DataFile SELECT）。

背景（计划 ``docs/superpowers/plans/2026-10-28-backend-perf-remediation.md`` Task D3）：
``generate_report`` 原在循环里逐 id ``get_object_or_404`` ⇒ N 个文件 N 条 SELECT。
改成循环外一次按 owner 过滤的批量取（再按连接上报的 ``max_query_params`` 分块），
**其余语义逐字节不变**：404 的信封内容、重复 id 的保重、``df is None ⇒ continue``
的跳过、出表行序。这几条「不变」是本文件的全部判据 —— 省的那条 SELECT 反而是次要的。

取数本身住在 ``apps/datafiles/lookup.py`` 的 ``owned_files_by_pk``（2026-10-30 审查
Important 3：它与 ``apps/analysis/views/_helpers.py`` 的 ``_load_files_from_request``
曾逐字近似，差别只在**调用方**拿到缺失者之后做什么 —— 这边判 404、那边静默跳过，
所以那句判断留在视图里，不跟着取数一起下沉）。analysis 那一侧的分块判据住在
``test/backend/test_analysis_load_db_count.py``（A3 的钉子，本轮一行未改）。

runner: ``manage.py test test.backend.test_batch_report_fetch``
"""

import json
from unittest import mock

from django.db import connection
from django.db.utils import OperationalError
from django.test.utils import CaptureQueriesContext

from apps.accounts.services import get_user_setting
from apps.batch_report import views as batch_views
from apps.datafiles.models import DataFile
from test.backend.batch_report_fixtures import (
    NOT_FOUND_BODY, URL_GEN, _BatchFixture, _df, _meta, sqlite_parameter_limit,
)


class GenerateReportBatchedFetchTests(_BatchFixture):
    def _datafile_selects(self, queries):
        return [q for q in queries
                if 'FROM "datafiles_datafile"' in q['sql']
                and q['sql'].lstrip().upper().startswith('SELECT')]

    def test_n_files_cost_one_datafile_select(self):
        """D3 的账只有 ``DataFile`` 那一族语句：3 个文件 ⇒ 恰好 1 条 SELECT。

        **不再钉「整请求语句总数 = 5」**（本判据先前那版钉的是 5，实测拆解如下）：
        一次 ``generate_report`` 请求打出的 5 条是
        ``DataFile`` SELECT × 1 + ``accounts_user_setting`` SELECT × 1 + ``BEGIN`` +
        ``accounts_user_setting`` INSERT × 1 + ``COMMIT`` —— 后 4 条是 D1 给缺失设置行
        建行（``apps/export/user_prefs.py`` 的 ``get_export_dpi`` 走
        ``render_export_filename`` 之前那趟）的账，与「循环里逐 id SELECT」这件事无关。
        把总数钉在 D3 的用例里，等于让 accounts 侧任何改动都在这里红（改前实测 7 条 =
        这 4 条 + 循环里那 3 条逐 id SELECT，扣掉的正是 DataFile 那 2 条冗余 ⇒
        判据本来就只在 DataFile 族上）。
        ``DataFile`` SELECT 条数对文件数不变这条判据在
        ``GenerateReportChunkedFetchTests.test_datafile_select_count_is_invariant_in_file_count``
        （1/3/18 个文件各钉一次），本条只钉「3 个文件 = 1 条」。
        """
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.post(URL_GEN, {'file_ids': self.ids}, format='json')
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        selects = self._datafile_selects(ctx.captured_queries)
        self.assertEqual(
            len(selects), 1,
            f'3 个文件打出 {len(selects)} 条 DataFile SELECT，期望 1 条（一次取全）')

    def test_missing_id_returns_unchanged_404_envelope(self):
        """404 的信封与改前 ``get_object_or_404`` 逐字节一致（不只状态码）。

        **钉不住的东西写在这里**：视图按输入顺序找第一个缺失者并抛
        ``Http404('No DataFile matches the given query.')``，而这句话**不含 id**
        （``get_object_or_404`` 的固定文案）。所以「报的是哪一个缺失者」在当前信封下
        不可观察 ⇒ 「输入序优先」这条**不是本用例钉住的判据**：把实现改成取最后一个
        缺失者（2026-10-30 审查变异 M6），本文件与全仓都不会有任何一条转红。行为照旧
        保留（取第一个），只是别把这条当成它的哨兵；信封一旦改成带 id，才谈得上钉它。
        """
        resp = self.client.post(URL_GEN, {'file_ids': [987654]}, format='json')
        self.assertEqual(resp.status_code, 404, getattr(resp, 'data', resp))
        self.assertEqual(json.loads(resp.content), NOT_FOUND_BODY)

    def test_missing_id_short_circuits_before_any_parse(self):
        """缺失者排在有效者后面也一样：取全阶段先判缺，一条解析都不发。

        改前是「解析与逐条 SELECT 交错」，``[有效, 缺失]`` 会先把有效那个解析掉
        （挤解析缓存）再抛 404。
        """
        parse = self._patch_parse(batch_views, return_value=(_df(), _meta(), 'CTA8290D'))
        resp = self.client.post(
            URL_GEN, {'file_ids': [self.ids[0], 987654, self.ids[1]]}, format='json')
        self.assertEqual(resp.status_code, 404, getattr(resp, 'data', resp))
        self.assertEqual(parse.call_count, 0,
                         '404 前已经解析过文件：批量取全没有前置')

    def test_out_of_range_id_is_404_not_db_error(self):
        """超出 PK 合法范围的整数不进 IN 列表（IN 不拒它，精确 ``pk=`` 拒），
        按缺失处理 ⇒ 与改前一样是 404，不是 500。

        合法区间由 ``BigAutoField`` 自己定（±2^63）：``2**63-1`` 进 ``IN``、
        ``2**63`` 被剔。取数侧那条口径与它的判据在
        ``apps/datafiles/lookup.py`` 的 ``valid_file_ids``（analysis 那边由
        ``test_analysis_load_db_count.py`` 的 out-of-range 用例钉同一条）。
        """
        resp = self.client.post(URL_GEN, {'file_ids': [2 ** 63]}, format='json')
        self.assertEqual(resp.status_code, 404, getattr(resp, 'data', resp))

    def test_duplicate_ids_keep_one_parse_each(self):
        """重复 id 的保重不变：``[a, a]`` 解析两次、仍只 1 条 SELECT。

        按输入去重取、按输入顺序回放是这一改的要点 —— 去重输出会让 Excel 少写一行。
        """
        parse = self._patch_parse(batch_views, return_value=(_df(), _meta(), 'CTA8290D'))
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.post(
                URL_GEN, {'file_ids': [self.ids[0], self.ids[0]]}, format='json')
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        self.assertEqual(parse.call_count, 2)
        self.assertEqual(len(self._datafile_selects(ctx.captured_queries)), 1)

    def test_other_users_file_is_404_not_partial_export(self):
        """owner 过滤留在批量取里：别人的文件不会被带进批次。"""
        resp = self.client.post(
            URL_GEN, {'file_ids': [self.ids[0], self.theirs.id]}, format='json')
        self.assertEqual(resp.status_code, 404, getattr(resp, 'data', resp))

    def test_generate_report_and_analysis_loader_bind_one_shared_fetch(self):
        """取数只有**一份实现**（2026-10-30 审查 Important 3 的绊线）。

        ``from apps.datafiles.lookup import owned_files_by_pk`` 在每个消费模块里建的是
        指向同一函数对象的绑定（R6③ 那条在这里反过来用），所以断「两边绑的都是
        ``lookup`` 里那一个对象」钉得住「谁把那段分块复制回自己模块」：
        复制回去 ⇒ 那个属性消失（``AttributeError``）或 ``is`` 不成立 ⇒ 本条红。
        两份实现**逐字等价**（404 还是跳过只是调用方的选择），所以行为判据永远抓不到
        「复制一份」这种回归 —— 红只能来自身份，这也是本条存在的理由。

        下半段是「绑到 ≠ 走到」的补集：拿 ``wraps`` 数一次真实调用，防止公共函数被
        导入却没人用（那样上面两句仍然成立）。
        """
        from apps.analysis.views import _helpers
        from apps.datafiles import lookup

        self.assertIs(batch_views.owned_files_by_pk, lookup.owned_files_by_pk,
                      '批次视图用的不是 lookup 里那一份 ⇒ 分块又被复制了一份')
        self.assertIs(_helpers.owned_files_by_pk, lookup.owned_files_by_pk,
                      'analysis 视图用的不是 lookup 里那一份 ⇒ 分块又被复制了一份')
        with mock.patch.object(batch_views, 'owned_files_by_pk',
                               wraps=lookup.owned_files_by_pk) as fetch:
            resp = self.client.post(URL_GEN, {'file_ids': self.ids}, format='json')
        self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
        self.assertEqual(
            fetch.call_count, 1,
            f'公共取数被调了 {fetch.call_count} 次：视图没走它（本条前半段就只是钉了个导入）')


class GenerateReportChunkedFetchTests(_BatchFixture):
    """``owned_files_by_pk`` 的 IN 分块（``apps/datafiles/lookup.py``）。

    那段按连接自己上报的 ``max_query_params`` 分块、并给 ``owner`` 过滤预留 1 个参数的
    代码，此前**一条用例都没钉** —— 而仓里早就有钉这类判据的夹具形状
    （``test/backend/test_analysis_load_db_count.py`` 的 ``sqlite_parameter_limit``，
    它同时压低 SQLite 真实变量上限与 ``connection.features.max_query_params``，
    所以「超限」不是假想的；那一侧的判据本轮一行未改，本类钉的是批次这一侧）。
    照那份形状搬过来（harness 收在 ``batch_report_fixtures.sqlite_parameter_limit``，
    全仓只有那一份归本文件用）：将来谁把分块「简化」成一次 ``in_bulk(ids)``，
    本类当场红，而不是在生产上撞到 ``too many SQL variables``。
    """

    file_count = 18

    def setUp(self):
        super().setUp()
        # ``UserSetting`` 的建行 INSERT 有 10+ 个参数，必须在下压变量上限**之前**跑完：
        # 否则 ``OperationalError`` 是 accounts 那侧的写触发的，本用例就白钉了
        # （请求路径上的 ``get_export_dpi`` 只读 ⇒ 一条 1 参数的 SELECT）。
        get_user_setting(self.user, create=True)

    @staticmethod
    def _is_datafile_select(sql):
        return ('FROM "datafiles_datafile"' in sql
                and sql.lstrip().upper().startswith('SELECT'))

    def _datafile_select_param_sizes(self, executed):
        return [n for sql, n in executed if self._is_datafile_select(sql)]

    def test_bulk_fetch_chunks_under_the_sqlite_parameter_limit(self):
        """上限 8、18 个 id ⇒ 3 条 SELECT，参数 8/8/5，且不炸 OperationalError。

        每块 7 个 id + 1 个 ``owner`` 参数 = 恰好等于上限
        （``chunk_size = max_params - 1``）；前置的 ``assertRaises`` 证明「超限」是真的：
        不分块的 ``in_bulk(18)`` 会被 SQLite 拒。
        """
        with sqlite_parameter_limit(self) as limit:
            self.assertGreater(len(self.ids), limit, '前置：18 个 id 必须真的超过上限')
            with self.assertRaises(OperationalError):
                DataFile.objects.filter(owner=self.user).in_bulk(id_list=self.ids)

            executed = []

            def record(execute, sql, params, many, context):
                executed.append((sql, len(params)))
                return execute(sql, params, many, context)

            with connection.execute_wrapper(record):
                resp = self.client.post(URL_GEN, {'file_ids': self.ids}, format='json')
            self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
            sizes = self._datafile_select_param_sizes(executed)
            budget = limit - 1                       # owner 过滤占 1 个参数
            expected = [min(budget, len(self.ids) - offset) + 1
                        for offset in range(0, len(self.ids), budget)]
            self.assertEqual(
                sizes, expected,
                f'IN 分块的参数分布 {sizes} 不是每块顶到上限（期望 {expected}，'
                f'即 {expected[0] - 1} 个 id + 1 个 owner）：分块被改坏了或干脆没了')
            self.assertEqual(len(sizes), 3, f'18 个 id 打了 {len(sizes)} 条 SELECT，期望 3 条')

    def test_datafile_select_count_is_invariant_in_file_count(self):
        """一次取全的**不变量**：1 / 3 / 18 个文件都只打 1 条 DataFile SELECT。

        这条替掉先前那句「整请求语句总数 = 5」（那句把 D1 的 ``UserSetting``
        ``SELECT+INSERT`` 也钉进来了，属于 accounts 的账，见
        ``GenerateReportBatchedFetchTests.test_n_files_cost_one_datafile_select`` 的 docstring）。
        18 个那一格在压过上限的夹具里跑 ⇒ 顺带证明分块没有把条数放大成「每块一条」以外
        的形态（3 块就是 3 条，见上一条）。
        """
        with sqlite_parameter_limit(self) as limit:
            for count in (1, 3, len(self.ids)):
                ids = self.ids[:count]
                with self.subTest(count=count):
                    executed = []

                    def record(execute, sql, params, many, context):
                        executed.append((sql, len(params)))
                        return execute(sql, params, many, context)

                    with connection.execute_wrapper(record):
                        resp = self.client.post(URL_GEN, {'file_ids': ids}, format='json')
                    self.assertEqual(resp.status_code, 200, getattr(resp, 'data', resp))
                    selects = [e for e in executed if self._is_datafile_select(e[0])]
                    # 界内（<= 每块容量）必须一条打完，界外才按块数铺开。
                    expected = 1 if count <= limit - 1 else 3
                    self.assertEqual(
                        len(selects), expected,
                        f'{count} 个文件打了 {len(selects)} 条 DataFile SELECT，'
                        f'期望 {expected} 条（上限 {limit}）')
