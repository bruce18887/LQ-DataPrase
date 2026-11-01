"""J5 命中缓存的仪表板汇总不再重建 payload（clean_data 只在写入侧跑一次）。

从 `tests.py` 按主题拆出（该文件在 B4 之后越过 600 行硬约束）：本组用例的
共同判据是「响应体就是缓存里那一只对象」与「两次请求合计只清洗一次」，与
`/summary/` 的字段契约无关，独立性足够。

跑：``python -X utf8 manage.py test apps.dashboard.tests_clean_once``
"""
import json
from unittest import mock

import pandas as pd
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.datafiles.models import DataFile


class SummaryCleanOnceTests(TestCase):
    """J5：命中缓存的第二次请求不该再把整份 payload 重建一遍（clean_data 是纯函数）。"""

    def test_cache_hit_does_not_reclean(self):
        from unittest import mock

        from apps.analysis.views._helpers import clean_data
        from apps.dashboard import services as dash_services

        user = User.objects.create_user(username='clean_once', password='pw')
        datafile = DataFile.objects.create(
            owner=user, filename='a.csv', file_path='a.csv',
            file_size=1, format_type='CTA8290D', status='ready')
        raw = {'rows': [{'v': float('nan'), 'ok': 1.0}]}
        dash_services._summary_cache.clear()
        self.addCleanup(dash_services._summary_cache.clear)
        with mock.patch.object(dash_services, 'compute_dashboard_summary',
                               return_value=raw), \
             mock.patch.object(dash_services, 'clean_data', wraps=clean_data) as spy:
            first = dash_services.get_dashboard_summary(datafile, None, 'CTA8290D', {}, None)
            second = dash_services.get_dashboard_summary(datafile, None, 'CTA8290D', {}, None)

        self.assertEqual(spy.call_count, 1, '第二次是缓存命中，不该再清洗')
        self.assertIs(second, first, '命中必须返回同一只对象')
        self.assertIsNone(first['rows'][0]['v'], 'NaN 必须在缓存里就已经是 None')

    def test_cached_payload_matches_old_exit_clean_bytes(self):
        """J5 的「响应字节不变」对照：写入侧清洗的输出 == 旧出口写法的输出（逐字节）。

        旧写法是 ``clean_data(get_dashboard_summary(...))``（视图出口），新写法是
        ``get_dashboard_summary(...)`` 自己在写入侧清洗一次。两者都是同一只纯函数
        作用在同一只 raw payload 上，所以序列化结果必须逐字节相同 —— 这里按
        DRF 严格渲染器的同口径（``allow_nan=False``）比对，防止哪天「顺手」把
        清洗换成别的实现（丢键 / 改舍入 / 只清洗部分子树）而没人拦。
        """
        from unittest import mock

        from apps.analysis.views._helpers import clean_data
        from apps.dashboard import services as dash_services

        user = User.objects.create_user(username='clean_bytes', password='pw')
        datafile = DataFile.objects.create(
            owner=user, filename='b.csv', file_path='b.csv',
            file_size=1, format_type='CTA8290D', status='ready')
        raw = {
            'file_id': datafile.id,
            'metrics': {'yield_pct': float('nan'), 'total_rows': 4,
                        'ratio': float('inf'), 'neg': float('-inf')},
            'test_item_overview': [
                {'name': 'P1', 'mean': 1.5, 'cpk': None, 'lsl': float('nan')},
                {'name': 'P2', 'mean': [float('nan'), {'deep': float('inf')}]},
            ],
            'strings': ['x', None, 3],
        }
        dash_services._summary_cache.clear()
        self.addCleanup(dash_services._summary_cache.clear)
        with mock.patch.object(dash_services, 'compute_dashboard_summary',
                               return_value=raw):
            cached = dash_services.get_dashboard_summary(
                datafile, None, 'CTA8290D', {}, None)

        # 旧写法（出口清洗）产出的字节。B4 之后 payload 还带两个计数键（param_total /
        # top_n），它们不是清洗产物，清洗口径的对照只看原有键；两键另行断言。
        capped = {k: v for k, v in cached.items() if k not in ('param_total', 'top_n')}
        old_way = json.dumps(clean_data(raw), allow_nan=False, sort_keys=True)
        capped_way = json.dumps(capped, allow_nan=False, sort_keys=True)
        self.assertEqual(capped_way, old_way, '清洗挪侧不得改变响应字节')
        self.assertEqual(cached['param_total'], 2)
        self.assertEqual(cached['top_n'], 200)
        self.assertEqual(json.loads(old_way), clean_data(raw))
        self.assertNotIn('NaN', capped_way)
        self.assertNotIn('Infinity', capped_way)

    def test_real_endpoint_cleans_exactly_once_across_cache_hit(self):
        """J5 的另一半：清洗不许「再回到出口」—— 走真实端点，两道互补判据。

        `test_cache_hit_does_not_reclean` 的 spy 打在 `apps.dashboard.services.clean_data`
        这只绑定上，它钉得住「清洗发生在 services」，**钉不住「清洗不再发生在出口」**：
        有人把视图响应重新包成 `clean_data(get_dashboard_summary(...))`（本仓其余约 18 个
        端点正是这个写法，顺手会写，合并冲突时也会被自动「解」回来），上面那两条与
        `SummaryInfApiTests` 那族照样全绿 —— 提交信息里「命中不再重建整份 payload」只守住
        了半边。这里补两条方向相反、盲区互补的判据：

        ① spy 装在唯一源头 `apps.analysis.views._helpers.clean_data`（`mock.patch.object` +
           `wraps=`，行为不动只记次数）。`services.py:48-49` 的薄封装是**函数内**
           `from ... import clean_data`，每次调用都重新解析 `_helpers` 的那个属性 ⇒ patch 它
           写入侧一定看得见（R6③ 在这里的消费方就是 `_helpers.clean_data` 本身）。
           两次真实请求之间不清缓存 ⇒ 第二次必须命中，全程只该有「首次未命中」那一次：
             清洗丢了 → 0（红，`SummaryInfApiTests` 那条 ValueError 用例同时红）；
             缓存没建起来 → 2（红）；出口以「延迟 import / 属性调用」的形状加回来 → 3（红）。
        ② 但 ①有一处**实测过的盲区**：视图若按本仓惯例在文件头 `from _helpers import clean_data`
           （就是被本刀删掉的那行），那只绑定在 import 时就抓走了**真函数**，patch 模块属性
           看不见它 —— 把出口清洗原样加回去，①照样绿（Fix round 1 的对照组实测）。所以再断
           **响应体就是缓存里那一只对象**：`clean_data` 永远新建容器，出口只要再过一遍，
           `response.data` 就不是缓存对象了 → 红。这条不依赖任何人怎么 import。

        `compute_dashboard_summary` 桩成 `{}` 是刻意的：`clean_data` 递归调用的是**本模块全局
        同名函数**（`_helpers.py:84-94`），patch 后每递归到一个节点就多计一次，非空 payload 的
        `call_count` 是「遍历节点数」不是「清洗次数」，断不到 1。顶层次数与对象身份都跟
        payload 大小无关，所以空 payload 不削弱这两条的方向性。
        """
        from unittest import mock

        from rest_framework.test import APIClient

        from apps.analysis.views import _helpers
        from apps.dashboard import services as dash_services
        from apps.dashboard import views as dash_views

        user = User.objects.create_user(username='clean_once_api', password='pw')
        datafile = DataFile.objects.create(
            owner=user, filename='c.csv', file_path='c.csv',
            file_size=1, format_type='ETS88', status='ready')

        # 夹具沿用 SummaryInfApiTests.setUp（:360-392）的形状：视图侧两只函数按消费方
        # 绑定替换，请求才真能走到 compute 之前，而不是被「盘上没有这个文件」提前弹回。
        df = pd.DataFrame({'PG_RES': ['770.0', '800.0']})
        meta = {'format': 'ETS88', 'mins': {'PG_RES': '765.0000'},
                'maxs': {'PG_RES': '935.0000'}}
        orig = (dash_views.resolve_file_path, dash_views.get_cached_parsed_file)
        dash_views.resolve_file_path = lambda p: __file__
        dash_views.get_cached_parsed_file = lambda *a, **k: (df, meta, 'ETS88')
        self.addCleanup(setattr, dash_views, 'resolve_file_path', orig[0])
        self.addCleanup(setattr, dash_views, 'get_cached_parsed_file', orig[1])

        client = APIClient()
        client.force_authenticate(user)

        raw = {}
        dash_services._summary_cache.clear()
        self.addCleanup(dash_services._summary_cache.clear)
        with mock.patch.object(dash_services, 'compute_dashboard_summary', return_value=raw), \
             mock.patch.object(_helpers, 'clean_data', wraps=_helpers.clean_data) as spy:
            first = client.get('/api/v1/summary/', {'file_id': datafile.id})
            calls_after_first = spy.call_count
            self.assertEqual(len(dash_services._summary_cache), 1, '首次未命中必须写入缓存')
            cached = next(iter(dash_services._summary_cache.values()))
            self.assertIs(first.data, cached, '出口不该重建 payload：响应体就得是缓存那一只')
            # 两次请求之间不许清缓存：第二次必须命中，才谈得上「出口不再清洗」
            second = client.get('/api/v1/summary/', {'file_id': datafile.id})
            calls_after_second = spy.call_count
            self.assertIs(second.data, cached, '命中返回同一只对象，且出口没有再过一遍')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(calls_after_first, 1, '首次未命中只该有写入侧那一次清洗')
        self.assertEqual(calls_after_second, 1,
                         '第二次命中缓存且出口不再清洗 ⇒ 全程仍只有那 1 次；'
                         '变成 3 就是有人把 clean_data 加回了视图出口')
        self.assertEqual(spy.call_count, 1, '两次请求合计只清洗一次')

