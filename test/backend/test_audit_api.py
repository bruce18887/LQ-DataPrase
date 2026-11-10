"""审计查询 API：`GET /api/v1/auth/audit-events/`（spec §6 契约、§10 错误信封）。

Task 8 只有读侧，与本仓其余审计判据的分工：`test_audit_writer.py` 量写入器、
`test_audit_login_events.py` 与 `test_audit_account_events.py` 量十个码接在哪个动作上，
本文件只量「查出来的形状对不对、谁能查、什么参数算错」。响应体是 Task 11 审计页的
唯一契约，所以这里的整值断言就是那份契约本身。六条口径：

1. **整值判据**：每个筛选都钉「返回的 id 精确列表 + `count` 精确值 + 键集合精确值」，
   不写 `assertIn(…, str(resp.content))`，也不按位置从「无序」列表里取数。
2. **建行走 `audit.record()`**（`_seed`），不手搓 INSERT —— 端点读的必须是写入器真正
   写得出的那种行。只有时间戳例外：`created_at` 是 `auto_now_add`，同批 `record()` 的
   值不可控，所以落库后用 `queryset.update()` 钉到墙上（判据要的日期/并列次序都靠它）。
3. **排序是全序而不是「大致倒序」**：同一瞬间记下的两笔（一次请求里连记两条，例如第五次
   登录失败那对 `login_failure`+`account_locked`）时间戳可以完全相同，`-created_at` 之后
   必须有第二根线。两支判据各管一半（原因见 `test_order_by_sql_carries_the_tiebreaker`
   的 docstring）：`test_equal_timestamp_order_is_total_and_pager_stable` 钉可观察顺序与
   页边界，`test_order_by_sql_carries_the_tiebreaker` 钉发出的 ORDER BY 子句。
4. **日期按本地整日**（spec §10「避免 UTC 和本地日界混用」）：`TIME_ZONE` 是
   Asia/Shanghai（`config/settings/base.py`），所以「今天 00:30」这一行在 UTC 里是
   **昨天 16:30**。`LocalDayBoundaryTests` 把两侧的边界行都种上（凌晨/深夜/次日零点整），
   按 UTC 解释日期、或把上界写成 `__lte`，都会立刻红。
5. **`page_size` 的上下界由视图判，不由 DRF 兜**。DRF 3.18.3 `PageNumberPagination.get_page_size()`
   现量（2026-11-10，配 `page_size=50` + `page_size_query_param='page_size'` +
   `max_page_size=100`）：`0`、`-5`、`abc`、`2.5`、`''` 一律**静默回落成 50**，`101`
   **静默截成 100**，一个 400 都不发。所以干活的是显式校验，本视图因此不设
   `max_page_size`（校验先拒 ⇒ 那层 clamp 够不到）。反向也量过：把视图里那段显式校验删掉，
   超限值就原样传到 DRF —— 抓住它的是
   `BadParamTests::test_page_size_that_drf_would_silently_absorb`。
6. **`page` 不在这条闸里**：非法页码走的是 DRF 分页自己的 `NotFound` ⇒ 404
   `not_found`（同样现量），不是 400。Task 11 要按 404 处理「页码超范围」。
"""
import os
import re
import sys
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.unit')

import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402
from django.test import RequestFactory, TestCase  # noqa: E402
from django.test.utils import CaptureQueriesContext  # noqa: E402
from django.utils.dateparse import parse_datetime  # noqa: E402
from django.utils import timezone  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.accounts import audit  # noqa: E402
from apps.accounts.models import AuditEvent, User  # noqa: E402
from apps.accounts.serializers import AuditEventSerializer  # noqa: E402

ADMIN_PW = 'x-admin-pass-123'
USER_PW = 'x-user-pass-123'

AUDIT_URL = '/api/v1/auth/audit-events/'
# 没有这条路由就没有「按 id 读单行」的入口（spec §6 只给了列表端点）。
AUDIT_DETAIL_URL = AUDIT_URL + '1/'

# 响应一行的键**清单与顺序**都是契约（顺序 = `AuditEventSerializer.Meta.fields`）。
ROW_KEYS = ['id', 'created_at', 'event', 'actor_username',
            'target_username', 'ip_address', 'detail']
# 分页信封的键由 DRF `PageNumberPagination.get_paginated_response` 定（异源核对：
# 读的是 DRF 3.18.3 的符号，不是本仓视图代码）。
PAGE_KEYS = {'count', 'next', 'previous', 'results'}

# `_seed` 里 RequestFactory 请求的 REMOTE_ADDR，写入器 `_client_ip()` 认它。
SEED_IP = '10.0.0.7'

# 列宽现取模型字段，不抄视图常量、也不抄 `audit.USERNAME_MAX_LENGTH`：判据与实现
# 必须异源，否则「视图写死 150 + 列宽改成 120」这种漂移会两边一起动、测不出来，
# 后果是「一个存得进快照列的用户名查不到」——审计页永远搜不到那笔事件。
SNAPSHOT_COLUMN_WIDTH = AuditEvent._meta.get_field('actor_username').max_length

HOUR = timedelta(hours=1)


def _seed(event, *, actor=None, target=None, target_username=None,
          detail=None, created_at=None):
    """用真实写入器种一行，返回它的 id（`created_at` 非空则把时间钉到墙上）。"""
    before = AuditEvent.objects.count()
    request = RequestFactory().get('/api/v1/auth/login/', REMOTE_ADDR=SEED_IP)
    audit.record(request, event, actor=actor, target=target,
                 target_username=target_username, detail=detail)
    row_id = AuditEvent.objects.order_by('-id').values_list('id', flat=True).first()
    # 先确认这一行真的落下去了：`audit.record()` 是 best-effort，失败只留一条 warning，
    # 那时本助手会返回**上一条**的 id（表空时返回 None），29 条用例就全变成看不懂的
    # id 比对失败，而不是「审计行没写进去」这一句人话。行数+1 而不是「非 None」：
    # 只判非 None 会放过「静默丢行但仍读到上一条」这一种。
    assert AuditEvent.objects.count() == before + 1, f'{event} 没有落成审计行'
    if created_at is not None:
        # `auto_now_add` 是 `Field.pre_save` 在 Python 侧盖的时间戳，`queryset.update()`
        # 不走 `pre_save`，因此绕得过它（现量：写 123456 微秒读回来还是 123456）。
        AuditEvent.objects.filter(pk=row_id).update(created_at=created_at)
    return row_id


def _at_day(offset_days, hour=0, minute=0, second=0):
    """本地时区里「今天+offset 天」的那个时刻（aware），日期参数的判据都用它。"""
    day = timezone.localdate() + timedelta(days=offset_days)
    return timezone.make_aware(
        datetime(day.year, day.month, day.day, hour, minute, second))


def _ids(response):
    """整值取这一页的 id 列表（顺序即响应顺序，判据拿它比精确列表）。"""
    return [row['id'] for row in response.data['results']]


def _day_str(offset_days):
    return _at_day(offset_days).strftime('%Y-%m-%d')


class AccessAndShapeTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('api-admin', 'a@localhost', ADMIN_PW)
        self.plain = User.objects.create_user('api-user', 'u@localhost', USER_PW)
        self.client = APIClient()

    def test_admin_only(self):
        row = _seed('login_success', actor=self.admin, target=self.admin)
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(AUDIT_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(_ids(resp), [row])

        self.client.force_authenticate(user=self.plain)
        denied = self.client.get(AUDIT_URL)
        self.assertEqual(denied.status_code, 403, denied.content)

        self.client.force_authenticate()  # 断开：走真实认证通路
        anon = self.client.get(AUDIT_URL)
        self.assertEqual(anon.status_code, 401, anon.content)
        self.assertTrue(anon['WWW-Authenticate'].startswith('Bearer'),
                        anon['WWW-Authenticate'])

        # 信封是项目统一的 {code,message,detail}（`apps/common/exceptions.py`），
        # 不是 DRF 裸 `detail` —— 前端按 code 分支，拿到裸 detail 就只能猜文案。
        for resp_body, code in ((denied.data, 'forbidden'), (anon.data, 'unauthorized')):
            self.assertEqual(set(resp_body), {'code', 'message', 'detail'}, resp_body)
            self.assertEqual(resp_body['code'], code, resp_body)

    def test_shape_and_newest_first(self):
        # id 顺序与时间顺序**相反**地种：只看 id 也能凑出「三条、倒着」，
        # 但只有按 created_at 排才拿到这个顺序。
        oldest = _seed('user_created', actor=self.admin, target_username='a-oldest',
                       created_at=_at_day(-2, 9))
        middle = _seed('user_updated', actor=self.admin, target_username='b-middle',
                       created_at=_at_day(-1, 9))
        newest = _seed('password_reset', actor=self.admin, target_username='c-newest',
                       created_at=_at_day(0, 9))
        self.client.force_authenticate(user=self.admin)
        resp = self.client.get(AUDIT_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(set(resp.data), PAGE_KEYS, resp.data)
        self.assertEqual(resp.data['count'], 3)
        self.assertEqual(_ids(resp), [newest, middle, oldest])
        self.assertIsNone(resp.data['next'], '一页装得下就不该有下一页链接')
        self.assertIsNone(resp.data['previous'])

        row = resp.data['results'][0]
        self.assertEqual(list(row), ROW_KEYS, row)
        self.assertEqual(row['id'], newest)
        # 时间串按瞬时比（渲染成哪种偏移是下面那一记的事）。
        self.assertEqual(parse_datetime(row['created_at']), _at_day(0, 9),
                         row['created_at'])
        # Task 11 的显示契约：这一串带本地偏移，页面按 UTC 解析就会整体差 8 小时。
        self.assertTrue(row['created_at'].endswith('+08:00'), row['created_at'])
        self.assertEqual(row['event'], 'password_reset')
        self.assertEqual(row['actor_username'], 'api-admin')
        self.assertEqual(row['target_username'], 'c-newest')
        self.assertEqual(row['ip_address'], SEED_IP)
        self.assertEqual(row['detail'], {})

    def test_serializer_exposes_no_writable_fields(self):
        """只读的第二处证明：`Meta.read_only_fields` 那句是**声明**，`_writable_fields` 才是事实。"""
        instance = AuditEvent.objects.get(id=_seed('login_failure',
                                                   target_username='x', detail={'reason': 'x'}))
        serializer = AuditEventSerializer(instance)
        self.assertEqual([f.field_name for f in serializer._writable_fields], [])
        self.assertEqual(sorted(serializer.fields), sorted(ROW_KEYS))
        # 反方向也钉住：给它一份完整载荷，validated_data 必须是空的（一个键都收不下）。
        fresh = AuditEventSerializer(data={key: 'probe' for key in ROW_KEYS})
        self.assertTrue(fresh.is_valid(), fresh.errors)
        self.assertEqual(fresh.validated_data, {})

    def test_every_registered_event_code_is_queryable(self):
        """十个码逐个能筛（白名单与 `AUDIT_EVENTS` 同源，Task 9 的标签表还要与两边对齐）。"""
        seeded = {}
        for offset, code in enumerate(audit.AUDIT_EVENTS):
            seeded[code] = _seed(code, actor=self.admin,
                                 created_at=_at_day(0, 1, minute=offset))
        self.client.force_authenticate(user=self.admin)
        for code, row_id in seeded.items():
            with self.subTest(event=code):
                resp = self.client.get(AUDIT_URL, {'event': code})
                self.assertEqual(resp.status_code, 200, resp.content)
                self.assertEqual(_ids(resp), [row_id])
                self.assertEqual(resp.data['count'], 1)


class FilterTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('flt-admin', 'a@localhost', ADMIN_PW)
        self.target = User.objects.create_user('ev-target', 't@localhost', USER_PW)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        # a1：admin → ev-target（只有 target 侧含 'target'）
        self.a1 = _seed('password_reset', actor=self.admin, target=self.target,
                        created_at=_at_day(-3, 12))
        # a2：无操作者（登录失败形状），只有 target_username 快照
        self.a2 = _seed('login_failure', target_username='nobody',
                        detail={'reason': 'unknown_user'}, created_at=_at_day(-2, 12))
        # a3：ev-target → admin（actor 侧含 'target'，target 侧含 'admin'）
        self.a3 = _seed('user_updated', actor=self.target, target=self.admin,
                        detail={'changed_fields': ['is_active']},
                        created_at=_at_day(-1, 12))

    def _assert_ids(self, params, expected):
        resp = self.client.get(AUDIT_URL, params)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(_ids(resp), expected, resp.data)
        self.assertEqual(resp.data['count'], len(expected))

    def test_filter_by_event(self):
        self._assert_ids({'event': 'password_reset'}, [self.a1])
        self._assert_ids({'event': 'user_updated'}, [self.a3])

    def test_username_matches_actor_or_target_case_insensitively(self):
        # 'TARGET' 大写：只按 actor 匹配的实现会在这里红（a1 的 actor 是 flt-admin）。
        self._assert_ids({'username': 'TARGET'}, [self.a3, self.a1])
        self._assert_ids({'username': 'ev-target'}, [self.a3, self.a1])
        # 子串（icontains）而不是全等，且两侧都参与：'dmiN' 不是任何一个完整用户名，
        # 'ev-t' 是 'ev-target' 的前缀片段。
        self._assert_ids({'username': 'dmiN'}, [self.a3, self.a1])
        self._assert_ids({'username': 'ev-t'}, [self.a3, self.a1])
        self._assert_ids({'username': 'nobody'}, [self.a2])

    def test_event_and_username_are_anded(self):
        """两个参数之间是 AND、username 内部两个字段之间是 OR —— 别把这两层混了。"""
        self._assert_ids({'event': 'password_reset', 'username': 'flt-admin'}, [self.a1])
        self._assert_ids({'event': 'user_updated', 'username': 'nobody'}, [])

    def test_empty_params_mean_no_filter(self):
        # `event=''` 那一腿有牙：去掉视图里 `if event` 那道判断，`filter(event='')` 筛出零行。
        # `username=''` 那一腿**没有**牙 —— `icontains ''` 匹配所有非 NULL，跳过筛选同样是全部，
        # 两种实现给同一个结果，所以它只顺带钉住「传空串不 400」。日期两腿才是真有牙的那两条：
        # `_parse_day_bound` 若不在入口挡掉空串，'' 会被当日期解析 ⇒ 400。
        self._assert_ids({'event': '', 'username': ''}, [self.a3, self.a2, self.a1])
        self._assert_ids({'date_from': '', 'date_to': ''}, [self.a3, self.a2, self.a1])
        self._assert_ids({}, [self.a3, self.a2, self.a1])


class LocalDayBoundaryTests(TestCase):
    """`date_from` / `date_to` 是**本地整日**、两端包含（spec §6 + §10）。"""

    def setUp(self):
        self.admin = User.objects.create_superuser('tz-admin', 'a@localhost', ADMIN_PW)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        today = _at_day(0)
        # 五行把两侧边界都占住：本地今天凌晨（UTC 昨天下午）、本地今天 23:59:59.123456、
        # 本地昨天深夜（UTC 今天凌晨）、本地明天凌晨（UTC 今天下午）、明天零点整。
        # 微秒不是装饰：`created_at` 存到微秒，而「上界写成当天 23:59:59 + `__lte`」这种
        # 实现只会漏掉**带微秒**的那一行，整数秒的行它在两种写法下都返回。
        self.early_today = _seed('login_success', actor=self.admin,
                                 created_at=today.replace(hour=0, minute=30))
        self.late_today = _seed('login_failure', actor=self.admin, target_username='z',
                                created_at=today.replace(hour=23, minute=59, second=59,
                                                         microsecond=123456))
        self.late_yesterday = _seed('login_success', actor=self.admin,
                                    created_at=_at_day(-1).replace(hour=23, minute=30))
        self.early_tomorrow = _seed('login_success', actor=self.admin,
                                    created_at=_at_day(1).replace(minute=10))
        # 正好落在 `date_to=today` 那个边界瞬间上的行（次日本地零点）：上界写成 `__lte`
        # 就会把它漏进来 —— 「两端包含」说的是两个本地日，不是两个瞬间。
        self.next_midnight = _seed('login_success', actor=self.admin,
                                   created_at=_at_day(1))

    def test_today_to_today_is_inclusive_of_both_day_ends(self):
        d = _day_str(0)
        resp = self.client.get(AUDIT_URL, {'date_from': d, 'date_to': d})
        self.assertEqual(resp.status_code, 200, resp.content)
        # 23:59:59.123456 那一行必须在：写成 `created_at__lte(当天 23:59:59)` 就正好漏掉它
        # （漏的是带微秒的那一行，整数秒的行两种写法都返回，所以那行必须种微秒）；
        # 写成 `__lte(次日 00:00)` 会连明天零点整那行一起进来；
        # 只有 `__lt(次日的本地 00:00)` 既含它又不含明天那两行。
        self.assertEqual(_ids(resp), [self.late_today, self.early_today])
        self.assertEqual(resp.data['count'], 2)

    def test_each_adjacent_day_holds_only_its_own_rows(self):
        self.assertEqual(_ids(self.client.get(
            AUDIT_URL, {'date_from': _day_str(-1), 'date_to': _day_str(-1)})),
            [self.late_yesterday])
        self.assertEqual(_ids(self.client.get(
            AUDIT_URL, {'date_from': _day_str(1), 'date_to': _day_str(1)})),
            [self.early_tomorrow, self.next_midnight])

    def test_window_outside_the_seeded_days_is_empty_not_400(self):
        """窗口整体落在种子数据之外（往后、往前各一次）⇒ 空页，不是 400。

        判的是「日期筛选真的参与 WHERE」：两边过滤若被整段删掉，这里会返回五行；
        而把不合法的窗口当参数错误抛 400 也是错的 —— 空区间完全合法，用户只是问了个
        没有记录的时间段（`test_inverted_range` 钉的是相反那一半：倒置才该 400）。
        """
        for params in ({'date_from': _day_str(2), 'date_to': _day_str(3)},
                       {'date_from': _day_str(-3), 'date_to': _day_str(-2)}):
            with self.subTest(**params):
                resp = self.client.get(AUDIT_URL, params)
                self.assertEqual(resp.status_code, 200, resp.content)
                self.assertEqual(_ids(resp), [], params)
                self.assertEqual(resp.data['count'], 0, resp.data)

    def test_open_ended_bounds(self):
        self.assertEqual(_ids(self.client.get(AUDIT_URL, {'date_from': _day_str(0)})),
                         [self.early_tomorrow, self.next_midnight,
                          self.late_today, self.early_today])
        self.assertEqual(_ids(self.client.get(AUDIT_URL, {'date_to': _day_str(0)})),
                         [self.late_today, self.early_today, self.late_yesterday])

    def test_bounds_are_local_not_utc(self):
        """前提自检：本地今天凌晨那一行在 UTC 日历上属于**昨天**（Asia/Shanghai = UTC+8）。

        视图若按 UTC 解释 `date_from`/`date_to`（即 `make_aware(..., utc)`），上面三条
        日期判据会同时红 —— 本条只钉「这个前提是真的」，红在这里说明时区配置变了，
        而不是筛选写错。
        """
        row = AuditEvent.objects.get(pk=self.early_today)
        self.assertEqual(row.created_at.astimezone(dt_timezone.utc).strftime('%Y-%m-%d'),
                         _day_str(-1), row.created_at)
        self.assertEqual(row.created_at.astimezone(timezone.get_current_timezone())
                         .strftime('%Y-%m-%d'), _day_str(0), row.created_at)


class PaginationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('pg-admin', 'a@localhost', ADMIN_PW)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        base = _at_day(0, 12)
        # 60 行、时间戳互不相同且与 id 同序：默认页大小一测就准。
        self.ids = [_seed('login_success', actor=self.admin, created_at=base - i * HOUR)
                    for i in range(60)]

    def test_default_page_size_is_50_not_the_global_20(self):
        resp = self.client.get(AUDIT_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.data['count'], 60)
        self.assertEqual(len(resp.data['results']), 50, resp.data['count'])
        self.assertEqual(_ids(resp), self.ids[:50])

    def test_page_size_bounds_are_accepted_and_honored(self):
        resp = self.client.get(AUDIT_URL, {'page_size': 1})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(_ids(resp), [self.ids[0]])
        self.assertEqual(resp.data['count'], 60, 'count 是筛选后的总行数，不是这一页的行数')

        at_max = self.client.get(AUDIT_URL, {'page_size': 100})
        self.assertEqual(at_max.status_code, 200, at_max.content)
        self.assertEqual(len(at_max.data['results']), 60)

    def test_page_walks_the_whole_result_set_without_repeats(self):
        seen = []
        for page in (1, 2):
            resp = self.client.get(AUDIT_URL, {'page': page, 'page_size': 40})
            self.assertEqual(resp.status_code, 200, resp.content)
            seen += _ids(resp)
        self.assertEqual(seen, self.ids, '两页拼起来必须正好等于全量顺序，不重不漏')

    def test_equal_timestamp_order_is_total_and_pager_stable(self):
        stamp = _at_day(0, 8)
        AuditEvent.objects.all().delete()
        first = _seed('login_failure', actor=self.admin, target_username='tie-a',
                      created_at=stamp)
        second = _seed('account_locked', actor=self.admin, target_username='tie-b',
                       created_at=stamp)
        self.assertEqual(AuditEvent.objects.filter(created_at=stamp).count(), 2,
                         '两行必须真的同一瞬间，否则本条什么都没钉')

        resp = self.client.get(AUDIT_URL)
        self.assertEqual(_ids(resp), [second, first],
                         '同一时间戳内按 id 倒序：后写的那笔在前，与整体「新在前」一致')

        # 同一条契约再走另一条访问路径问一次（`username` 那对 icontains 与纯列表那条
        # SELECT 不是同一个 WHERE）。M1 探针：这条**也**罩不住删 tiebreaker，
        # 真正抓得住它的是下面那条 ORDER BY 判据。
        self.assertEqual(_ids(self.client.get(AUDIT_URL, {'username': 'tie-'})),
                         [second, first])

        page1 = self.client.get(AUDIT_URL, {'page_size': 1})
        page2 = self.client.get(AUDIT_URL, {'page_size': 1, 'page': 2})
        self.assertEqual(_ids(page1), [second])
        self.assertEqual(_ids(page2), [first])
        self.assertIsNone(page2.data['next'])

    def test_order_by_sql_carries_the_tiebreaker(self):
        """上面那条响应顺序判据**罩不住「删掉 `-id`」**，所以这里钉 SQL。

        本机现量（2026-11-10，SQLite + Django 6.0.9）：只按 `-created_at` 排时，平手的两行
        恰好也按 id 倒序出来 —— `EXPLAIN QUERY PLAN` 显示这条 SELECT 走
        `accounts_audit_event_created_at_763e7054` 那根索引，次序是索引白送的。于是
        「删掉 `-id`」在本机**可观察层面**什么都改不了，除了本条没有第二条判据抓得住它
        （不变式就这么写：删掉 `order_by` 里的 `-id` ⇒ 只红本条；把它翻成 `id` ⇒ 本条与
        上面那条一起红）。白送的次序不进契约：换后端、换索引、换数据规模都可能不这么排，
        所以「排序是全序」只能钉发出的 ORDER BY 子句本身。
        """
        with CaptureQueriesContext(connection) as cap:
            resp = self.client.get(AUDIT_URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        clauses = [re.search(r'ORDER BY (.*?)\s*\bLIMIT', q['sql']).group(1)
                   for q in cap.captured_queries if 'ORDER BY' in q['sql']]
        self.assertEqual(clauses, ['"accounts_audit_event"."created_at" DESC,'
                                   ' "accounts_audit_event"."id" DESC'], clauses)

    def test_invalid_page_number_is_404_not_400(self):
        """`page` 由 DRF 分页自己判（`NotFound`），本视图不掺手 —— Task 11 按 404 处理。"""
        for page in ('abc', '999'):
            resp = self.client.get(AUDIT_URL, {'page': page})
            self.assertEqual(resp.status_code, 404, resp.content)
            self.assertEqual(set(resp.data), {'code', 'message', 'detail'}, resp.data)
            self.assertEqual(resp.data['code'], 'not_found')


class BadParamTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('bad-admin', 'a@localhost', ADMIN_PW)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.row = _seed('login_success', actor=self.admin)

    def _assert_400(self, params, message):
        resp = self.client.get(AUDIT_URL, params)
        self.assertEqual(resp.status_code, 400, resp.content)
        self.assertEqual(set(resp.data), {'code', 'message', 'detail'}, resp.data)
        self.assertEqual(resp.data['code'], 'validation_error', resp.data)
        self.assertEqual(resp.data['message'], message, resp.data)
        self.assertEqual(resp.data['detail'], [message], resp.data)

    def test_unknown_event_code(self):
        self._assert_400({'event': 'not_a_code'}, '未知审计事件码：not_a_code')

    def test_bad_dates(self):
        for raw in ('2026-13-01', '2026-02-30', '20261110', '今天'):
            self._assert_400({'date_from': raw}, f'date_from 必须是 YYYY-MM-DD：{raw}')
        self._assert_400({'date_to': '2026-13-01'}, 'date_to 必须是 YYYY-MM-DD：2026-13-01')

    def test_inverted_range(self):
        # 倒置必须在**过滤之前**判掉：先过滤的话这是一个合法的 200 空页（少一根线），
        # 用户看到的是「没有记录」而不是「日期填反了」。
        self._assert_400({'date_from': '2026-11-10', 'date_to': '2026-11-09'},
                         'date_from 不能晚于 date_to')

    def test_same_day_range_is_not_inverted(self):
        resp = self.client.get(AUDIT_URL, {'date_from': _day_str(0), 'date_to': _day_str(0)})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(_ids(resp), [self.row])

    def test_username_over_the_snapshot_column_width(self):
        self._assert_400({'username': 'u' * (SNAPSHOT_COLUMN_WIDTH + 1)},
                         f'username 最长 {SNAPSHOT_COLUMN_WIDTH} 字符')
        exact = self.client.get(AUDIT_URL, {'username': 'u' * SNAPSHOT_COLUMN_WIDTH})
        self.assertEqual(exact.status_code, 200, exact.content)
        self.assertEqual(_ids(exact), [])

    def test_page_size_that_drf_would_silently_absorb(self):
        # 上面这五个值在 DRF 3.18.3 里全部被静默吞掉（回落默认 50 或 clamp 到上限），
        # 一个 400 都不发 —— 见模块 docstring 第 5 条的探量。
        for raw in ('2.5', 'abc', '1e3'):
            self._assert_400({'page_size': raw}, 'page_size 必须是整数')
        for raw in ('0', '-5', '101', '1000000'):
            self._assert_400({'page_size': raw}, 'page_size 必须在 1–100 之间')

    def test_empty_page_size_means_the_default(self):
        # 与 DRF 同侧：`page_size=`（空值）不报错，走默认 50（探量见模块 docstring 第 5 条）。
        resp = self.client.get(AUDIT_URL, {'page_size': ''})
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(_ids(resp), [self.row])


class ReadOnlyTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('ro-admin', 'a@localhost', ADMIN_PW)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        self.row = _seed('login_success', actor=self.admin, detail={'k': 'v'})

    def _snapshot(self):
        return list(AuditEvent.objects.order_by('id').values_list('id', 'event', 'detail'))

    def test_write_methods_are_not_allowed(self):
        before = self._snapshot()
        for method in ('post', 'put', 'patch', 'delete'):
            resp = getattr(self.client, method)(
                AUDIT_URL, {'event': 'login_success', 'actor_username': 'x'}, format='json')
            with self.subTest(method=method):
                self.assertEqual(resp.status_code, 405, resp.content)
                self.assertEqual(set(resp.data), {'code', 'message', 'detail'}, resp.data)
                self.assertEqual(resp.data['code'], 'method_not_allowed')
        self.assertEqual(self._snapshot(), before)

    def test_there_is_no_row_detail_route(self):
        resp = self.client.get(AUDIT_DETAIL_URL)
        self.assertEqual(resp.status_code, 404, resp.content[:200])

    def test_reads_never_write_an_audit_row(self):
        """查询侧一行都不许产生：审计只由那十个写入点长出来，否则「谁查了审计」会把自己
        记成事件流的一部分（spec §5.2 的十个码里没有这一类）。"""
        before = self._snapshot()
        queries = ({}, {'event': 'login_success'}, {'username': 'RO'},
                   {'page_size': '0'}, {'date_from': '2026-13-01'},
                   {'page': '999'}, {'date_from': _day_str(0), 'date_to': _day_str(-1)})
        for params in queries:
            with self.subTest(params=params):
                self.client.get(AUDIT_URL, params)
        self.assertEqual(self._snapshot(), before)
        self.client.post(AUDIT_URL, {'event': 'user_deleted'}, format='json')
        self.assertEqual(self._snapshot(), before)


if __name__ == '__main__':
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=1)
    sys.exit(1 if runner.run_tests(['test.backend.test_audit_api']) else 0)
