"""`GET /api/v1/auth/users/` 必须在**有序**集合上分页（Task 10 质量整改批）。

起因：`UserManagementViewSet.queryset` 原本写作 `User.objects.all()`。三个事实都是本机现量
（Django 6.0.9 / DRF 3.18.3，`manage.py shell -c`）：

  * `User.objects.all().query.order_by` 是空元组 `()`；
  * `User._meta.ordering` 是空列表 `[]`（`apps/accounts/models.py` 的 Meta 只有 db_table 与两个
    verbose_name）—— 所以模型侧也补不上这根线；
  * 于是 `User.objects.all().ordered is False`，加上 `.order_by('id')` 才为 `True`。

而全局 `PAGE_SIZE=20`（`config/settings/base.py:214-215`）配 `PageNumberPagination`（本 ViewSet
未覆写 `pagination_class`），DRF 于是在这个无序集合上做 limit/offset。两个后果：

  1. 每次构造 `Paginator` 都命中 `django/core/paginator.py::_check_object_list_is_ordered` 那条
     `UnorderedObjectListWarning`（现量：删掉 `order_by` 就出现，加上就消失）。注意发警告的是
     **Django 的分页器**，DRF 那边只是调用点（`rest_framework/pagination.py:198`
     `paginator = self.django_paginator_class(queryset, page_size)`）。
  2. 两次 LIMIT 查询之间没有任何东西保证同一次序 ⇒ 页与页之间可以重复同一行、也可以漏掉某行。

第 2 条在本仓不是理论问题，有两个消费方都靠「跟着 `next` 走完全表」拿全集，失真还都是静默的：
`UserManagement.vue` 的 `collectAllPages`（kpi 的 total/active/locked/admins 全按取回的数组算 ⇒
重复行会被双计）与 `frontend/e2e/admin/admin.spec.ts` 的 `afterAll`（扫不到就不删，那条按 `mine`
的清理保证直接失效）。

判据形状抄同仓先例 `test_audit_api.py::PaginationTests`（那次的坑是 `-created_at` 只构成偏序）。
关键教训是那条 **ORDER BY 文本判据不可省**：SQLite 今天按 rowid 返回、正好也是 id 升序，所以
「删掉 `order_by('id')`」在可观察层面什么都测不出来（本模块第一条实测罩不住它，见其 docstring），
只有钉发出的 SQL 才抓得到。三条判据：

  1. `test_pages_neither_repeat_nor_drop_a_row` —— 值判据：>PAGE_SIZE 行、跟着 `next` 走完全表，
     收上来的 `(id, username)` 无重无漏且 id 升序；
  2. `test_paginator_no_longer_warns_about_an_unordered_object_list` —— 直接钉第 1 条症状；
  3. `test_list_sql_carries_the_order_by` —— 钉 ORDER BY 子句文本，唯一抓得住「整条排序被删/被换」
     的那根线。

运行：``python -X utf8 manage.py test test.backend.test_user_list_pagination``
"""
import math
import re
import warnings
from unittest.mock import patch

from django.core.paginator import UnorderedObjectListWarning
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase
from rest_framework.settings import api_settings

from apps.accounts.models import User

USERS_URL = '/api/v1/auth/users/'
PASSWORD = 'strong-pass-123'

# 必须**超过**一页，否则「翻页」这件事根本没发生，第 1 条判据就成了恒真断言。
# 用 api_settings.PAGE_SIZE 推导而不是抄字面 20：PAGE_SIZE 变了本模块要跟着变长，
# 而不是悄悄退化成「只有一页」的空判据（护栏在 test_pages_...里，它自己会红）。
N_USERS = api_settings.PAGE_SIZE + 7


def _fillers(prefix, count):
    """造 `count` 行填充账号。走 `bulk_create` 而不是 `create_user`：本模块一个都不登录它们，
    而 `create_user` 要给每行做一次 PBKDF2-SHA256（1,200,000 次迭代，本机现量单次 `set_password`
    ≈319ms ⇒ 26 行 ≈8.3s，本模块两个类各 26 行）。`password` 不给值即落 `''`
    （`Field._get_default()` 对 NOT NULL 的 CharField 返回空串），列约束照旧满足。"""
    User.objects.bulk_create(
        [User(username=f'{prefix}-{i:03d}', role='user') for i in range(count)]
    )


class UserListPaginationTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='pager-admin', password=PASSWORD, role='administrator',
        )
        _fillers('pager', N_USERS - 1)
        self.client.force_authenticate(user=self.admin)

    def _walk_pages(self):
        """跟着 `next` 把全表走一遍，返回**按出现顺序**收集的 (id, username) 与页数。"""
        seen, url, pages = [], USERS_URL, 0
        while url and pages < 50:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, resp.content)
            pages += 1
            seen += [(r['id'], r['username']) for r in resp.data['results']]
            url = resp.data['next']
        return seen, pages

    def test_pages_neither_repeat_nor_drop_a_row(self):
        """全表跨页拼起来必须**正好**等于表内容：无重（重复行会让 kpi 双计）无漏。

        刻意不写「第 N 行是谁」这种位置判据，也不依赖 SQL 文本：这条管的是可观察契约
        （每一行出现恰好一次）。它管不住的是「删掉 `order_by('id')`」—— 本机现量：删掉之后
        SQLite 照样按 rowid 升序返回，本条仍然绿（这正是 ORDER BY 那条存在的原因）。
        """
        whole = set(User.objects.values_list('id', 'username'))
        self.assertGreater(len(whole), api_settings.PAGE_SIZE,
                           f'夹具只有 {len(whole)} 行，不足一页，本条什么都没测')

        seen, pages = self._walk_pages()

        self.assertEqual(len(seen), len(set(seen)),
                         f'跨页出现了重复行：{[x for x in seen if seen.count(x) > 1]}')
        self.assertEqual(set(seen), whole, '翻页拼出来的集合不等于全表（漏行或多行）')
        self.assertEqual(pages, math.ceil(len(whole) / api_settings.PAGE_SIZE),
                         f'{len(whole)} 行 / 每页 {api_settings.PAGE_SIZE} 应走 '
                         f'{math.ceil(len(whole) / api_settings.PAGE_SIZE)} 页，实走 {pages} 页')
        ids = [i for i, _ in seen]
        self.assertEqual(ids, sorted(ids), '返回顺序不是 id 升序（页面顺序变了就是这条该改）')

    def test_paginator_no_longer_warns_about_an_unordered_object_list(self):
        """DRF→Django 那条「无序 object_list」告警必须不再出现。

        `simplefilter('always')` 是必须的：Python 的默认过滤器按「消息+类别+发出位置」去重，同进程
        里前面任何一次触发都会把它记进发出模块的 `__warningregistry__`；不复位注册表（改过滤器就会
        让它整体失效）的话本条会假绿 —— 它断的是「没有」，最怕的正是「有，但被去重掉了」。
        「捕获机制真的抓得到」由本文件下面的 `UnorderedRegressionIsVisibleTests` 反向自证。
        """
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            self.client.get(USERS_URL)
        unordered = [w for w in caught if issubclass(w.category, UnorderedObjectListWarning)]
        self.assertEqual(unordered, [],
                         f'仍在无序集合上分页：{[str(w.message) for w in unordered]}')

    def test_list_sql_carries_the_order_by(self):
        """钉**发出的 ORDER BY 子句文本**：可观察层面罩不住「删掉排序」，只有 SQL 抓得住。

        与 `test_audit_api.py::PaginationTests::test_order_by_sql_carries_the_tiebreaker` 同一条
        理由 —— 本机现量（2026-11-10，SQLite + Django 6.0.9）：没有 ORDER BY 时这条 SELECT 照样
        按 rowid 升序吐行，与 `order_by('id')` 的结果逐字相同，所以「排序被删」在响应体里不可见。
        不变式：删掉 `views.py` 里的 `.order_by('id')` ⇒ 本条与上面那条告警判据红（顺序断言抓不到，
        见前一条的 docstring）；把它换成别的列（例如 `-date_joined`）⇒ 本条红，而那是一次**用户
        可见**的显示顺序变更，要连 `views.py` 那段注释一起改，不该顺手发生。
        """
        with CaptureQueriesContext(connection) as cap:
            resp = self.client.get(USERS_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        clauses = [re.search(r'ORDER BY (.*?)\s*\bLIMIT', q['sql']).group(1)
                   for q in cap.captured_queries if 'ORDER BY' in q['sql']]
        # 实测这条请求里只有一条带 ORDER BY 的语句：分页器先行的那次 COUNT(*) 不带排序
        # （`Paginator.count` → `Query.get_count`，本机现量其 SQL 里没有 ORDER BY），
        # 所以 clauses 只可能装着取页那条 —— 不是「挑了第一条」。
        self.assertEqual(clauses, ['"accounts_user"."id" ASC'], clauses)


class UnorderedRegressionIsVisibleTests(APITestCase):
    """反向自证：把 ViewSet 的排序摘掉，上面那两条**必须**变红（否则绊线恒绿）。

    不动 `views.py` 的字节，而是原地替换 `queryset` 属性 —— 与本仓「判据要能被它声称抓住的那个
    改动杀掉」的写法同构（`roleLabelHygiene.spec.ts` 的绊线自证是前端侧的同一件事）。
    """

    def setUp(self):
        self.admin = User.objects.create_user(
            username='kill-admin', password=PASSWORD, role='administrator',
        )
        _fillers('kill', N_USERS - 1)
        self.client.force_authenticate(user=self.admin)

    def test_unordered_queryset_trips_the_warning_and_the_sql_probe(self):
        from apps.accounts import views

        with patch.object(views.UserManagementViewSet, 'queryset', User.objects.all()):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                with CaptureQueriesContext(connection) as cap:
                    resp = self.client.get(USERS_URL)
            self.assertEqual(resp.status_code, 200, resp.content)
            self.assertTrue(
                [w for w in caught if issubclass(w.category, UnorderedObjectListWarning)],
                '摘掉排序后 Django 竟没有告警 ⇒ 告警那条判据抓不住回归',
            )
            self.assertFalse(
                [q['sql'] for q in cap.captured_queries if 'ORDER BY' in q['sql']],
                '摘掉排序后 SQL 里竟还有 ORDER BY ⇒ SQL 那条判据抓不住回归',
            )
