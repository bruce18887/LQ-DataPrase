"""D3 批次报告判据的**共享道具**：假帧夹具、404 信封、键集合与它们的解释、SQLite 分块 harness。

消费者是两个文件，拆开的唯一原因是 600 行绊线（`scripts/line-limit.mjs`，
判据口径见 `.claude/CLAUDE.md`「600 行约束的适用面」）：

* `test/backend/test_batch_report_fetch.py` —— `generate_report` 的「一次取全」与 IN 分块；
* `test/backend/test_batch_report_payload.py` —— `compute_batch_yield_data` 的分支裁剪。

写法照 `test/backend/job_cancel_fixtures.py`：夹具只有这一份，**不许**复制假帧。
理由就是它自己 —— 两份会各自漂，而漂出来的那份会替「JSON 分支到底带不带那四把 key」
撒谎，那正是本批判据的判据本身。

`sqlite_parameter_limit` 的**唯一一份**也在这里（2026-10-30 审查 Important 3 的尾款：
它先前在本仓出现两次，一次在 `test_analysis_load_db_count.py`、一次在批次载荷测试里）。
analysis 那一份这轮**不许动**（A3 的判据必须以未修改的状态通过，见 `git diff --exit-code
test/backend/test_analysis_load_db_count.py`），所以它仍带着自己那份同名方法；
把两边并成本函数是后续单独一批的活，别在批改进一半时把它「顺手」改掉。
"""

import sqlite3
from contextlib import contextmanager
from unittest import mock

import pandas as pd
from django.contrib.auth import get_user_model
from django.db import connection
from rest_framework.test import APITestCase

from apps.batch_report import services as batch_services
from apps.batch_report import views as batch_views
from apps.datafiles.models import DataFile

User = get_user_model()

URL_GEN = '/api/v1/batch-report/generate_report/'

# JSON 端点（``batch_yield_data``）的键集合。前端 BatchYieldTab.vue 逐键读的就是这一组：
# kpi / stage_yields / phase_summary / phases / site_matrix / sorted_sites / qa_checks /
# uph / batch_name。
JSON_KEYS = {
    'batch_name', 'kpi', 'phases', 'phase_summary', 'stage_yields',
    'sorted_sites', 'site_matrix', 'uph', 'qa_checks',
}
# HTML 报告分支额外带回的四把 key。
HTML_EXTRA_KEYS = {
    'trend_data', 'bin_distribution', 'bin_table_data', 'bin_site_columns',
}

#: 键集合判据的 ``msg=``：这几把断言红了，下一件事必须是「谁读它」，不是「把它加回来」。
#: 三条断言各钉一层，缺一层就会有人把它当成漏带：
PARTITION_HISTORY = (
    '这五把 key 是 2026-10-30 D3 **刻意**删掉的，不是漏带：'
    '(a) 没有任何消费者读 JSON 里的那几份拷贝 —— trend_data / bin_distribution / '
    'bin_table_data / bin_site_columns 的唯一读方是 apps/export/html_report/batch.py，'
    'site_pass_data 连 HTML 都不读（核对口径见 test_batch_report_payload.py 模块 '
    'docstring 的「消费方」段）；'
    '(b) 前端那张 Bin×Site 表是它自己按当前阶段现算的 —— '
    'frontend/src/utils/batchAggregation.ts 的 aggregateBinSiteTable 吃 '
    'phases[].bin_info[].sites，批级那两把同名 key 不是它的输入；'
    '(c) 前四把仍然由 HTML 分支带回（for_html_report=True，见 HTML_EXTRA_KEYS），'
    '删的只是 JSON 那一份。要恢复任何一把：先给出读它的那个人。'
)

# 改前 ``get_object_or_404`` 抛出的正是这句话，DRF 把它塞进 ``detail.detail``。
# 信封逐字节不变是这一改的硬约束，所以比**上线字节**（``json.loads``）而不是比
# ``resp.data``：DRF 的 ``ErrorDetail`` 是带 ``code`` 的 ``str`` 子类，它的 ``__eq__``
# 对普通字符串恒返回 ``NotImplemented`` ⇒ 拿 dict 直接比会假红。
NOT_FOUND_BODY = {
    'code': 'not_found',
    'message': '资源不存在',
    'detail': {'detail': 'No DataFile matches the given query.'},
}


def _df():
    # Site 取数值：``compute_site_yield_data`` 会 ``float(sv)`` 过滤站点，'S1' 这类
    # 非数字站点名会让 ``yield_data`` 直接空掉，``bin_info[].sites`` / ``sorted_sites``
    # 全都退化成空 ⇒ 这份夹具就钉不住「每阶段 sites 不能被删」那条。
    return pd.DataFrame({
        'Site': [1, 1, 2, 2],
        'SW_Bin': [1, 2, 1, 1],
        'P1': [1.0, 2.0, 3.0, 4.0],
    })


def _meta():
    return {'format': 'CTA8290D'}


class _BatchFixture(APITestCase):
    """三个属于本用户的批次文件 + 一个别人的文件；解析一律走假帧。"""

    file_count = 3

    def setUp(self):
        self.user = User.objects.create_user(username='d3_user', password='pw')
        self.other = User.objects.create_user(username='d3_other', password='pw')
        self.client.force_authenticate(self.user)
        self.ids = []
        for i in range(self.file_count):
            row = DataFile.objects.create(
                owner=self.user, filename=f'FT{i}.csv',
                file_path=f'data/d3_user/batch/D3/FT{i}.csv', file_size=2048,
                format_type='CTA8290D', file_type='batch', batch_name='D3',
                status='ready',
            )
            self.ids.append(row.id)
        self.theirs = DataFile.objects.create(
            owner=self.other, filename='OTHER.csv',
            file_path='data/d3_other/batch/D3/OTHER.csv', file_size=2048,
            format_type='CTA8290D', file_type='batch', batch_name='D3',
            status='ready',
        )
        self._patch_parse(batch_views, return_value=(_df(), _meta(), 'CTA8290D'))
        self._patch_parse(batch_services, return_value=(_df(), _meta(), 'CTA8290D'))

    def _patch_parse(self, module, **kwargs):
        # R6③：patch **实际消费模块**的绑定 —— ``from .x import f`` 会在两个模块里
        # 各建一个名字，patch 源模块只改到没人用的那一份。
        patcher = mock.patch.object(module, 'get_cached_parsed_file', **kwargs)
        started = patcher.start()
        self.addCleanup(patcher.stop)
        return started


@contextmanager
def sqlite_parameter_limit(tc, limit=8):
    """把**真实** SQLite 变量上限与 ``connection.features.max_query_params`` 一起压低。

    两个都要压：只 patch Django 那个数字，``in_bulk`` 会按假上限分块但底层驱动不报错，
    于是「超限」是想象出来的；只压驱动，Django 报的上限没变 ⇒ 分块代码根本不会被推到
    多块。压低期间断言 `getlimit` 真的读回新值，出块时还原并复核（还原失败会污染
    同一进程后面的用例）。

    前置：所有夹具 INSERT 必须在压低之前跑完（``UserSetting`` 建行那条有 10+ 个参数，
    否则 ``OperationalError`` 是 accounts 那侧的写触发的，用例就白钉了）。
    照 ``test_analysis_load_db_count.py`` 的 ``sqlite_parameter_limit`` 同一套动作 ——
    那份是 A3 的既有判据、本轮不许改，合并成一份是后续单独一批的活（见模块 docstring）。
    """
    if connection.vendor != 'sqlite':
        tc.skipTest('Requires the real SQLite variable limit')
    connection.ensure_connection()
    raw = connection.connection
    if not hasattr(raw, 'setlimit'):
        tc.skipTest('sqlite3.Connection.setlimit requires Python 3.11+')
    category = sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER
    previous_limit = raw.getlimit(category)
    previous_feature = connection.features.max_query_params
    try:
        raw.setlimit(category, limit)
        with mock.patch.object(type(connection.features), 'max_query_params', limit):
            tc.assertEqual(raw.getlimit(category), limit)
            yield limit
    finally:
        raw.setlimit(category, previous_limit)
        tc.assertEqual(raw.getlimit(category), previous_limit)
        tc.assertEqual(connection.features.max_query_params, previous_feature)
