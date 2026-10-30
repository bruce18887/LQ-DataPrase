"""D2 · 设置页 GET 不再写库、PUT 只写变更列（登录路径另见同目录 `test_login_path_statements.py`）。

下面每个数都是本机现量（2026-10-30，`.venv` = Python 3.13.12 / Django 6.0.9，
`python -X utf8 manage.py test`），不是照抄计划正文 —— 计划正文里有两处被实测改判：
一处是本模块的 PUT 段（SET 列数），另一处（`get`→`first` 省不掉语句）在登录模块。
本批 20 条在**两台解释器**上各跑一遍同形同绿（`.venv` = Django 6.0.9，
PATH 上那套系统 Python = Django 6.0.5）⇒ 上面那些语句表不是某个 Django 小版本的偶然形状。
本文件与 `test_login_path_statements.py` **合计 20 条用例**（这里 15 + 那边 5），
2026-10-30 把 `LoginPathTests` 拆出去是为了让「设置页写形状」和「登录计数写形状」各自一份账。

**GET**：HEAD 对缺行账号的形状是 `SELECT + SAVEPOINT + INSERT + RELEASE`（4 条，一个读请求在写库），
改后 1 条 SELECT、零写（判据 `SettingsGetWriteFreeTests.test_get_without_row_performs_zero_writes`，
`assertNumQueries` 与行前后计数双钉）；有行时（1 SELECT）与 HEAD 同形。
缺行时的默认实例用 `UserSetting(user_id=request.user.pk)` 构造，**不是**计划正文的
`UserSetting(user=request.user)`：实测（`SettingsGetCacheShapeTests.test_get_leaves_no_unsaved_row_on_the_user_instance`）
传 `user` 对象会让 `Model.__init__` 把这条未落库实例挂进 `request.user` 的反向缓存 —— D1 在
`test_user_setting_reads.py::UnsavedCacheGuardTests` 里叫它毒缓存，而计划 Step 3 要的正是把它
从异常路径搬到正常路径；`user_id=` 形状不碰这份缓存（两种形状的挂缓存差异同一轮量出，见该用例）。
GET 交出去的 JSON 与 HEAD「先建行再序列化」逐字节等价（`test_get_without_row_serializes_the_head_row_body`：
同轮给孪生账号走 HEAD 原形状 —— 建行 + 同一个序列化器 —— 与视图响应整体比对，含
`export_filename_templates` 的默认合并表与 `default_hidden_columns` 的空表回退）。

**PUT**：HEAD 的 `serializer.save()` 对任何部分载荷都发**全行** UPDATE —— SET 子句实测
**26 列** = `user_id` + 25 个设置列（含 5 个 `sftp_last_*`），`chart_dpi` 改一个值也要重写这 26 列。
**26 是列数、20 是序列化器字段数，不是同一个量**（原先两处注释写的「21 列」就是把 20 个字段
当成了列数）；这个数现量在同文件
`SettingsPutWriteShapeTests.test_head_full_row_update_sets_26_columns_not_the_20_serializer_fields`，
加一列就会把那条和注释一起拽红。改后 SET 只含变更列
（`SettingsPutWriteShapeTests.test_put_partial_writes_only_the_changed_column`，正反都钉：
变更列在、未变更列与 `user_id` 不在）。缺行时这里仍建行（写通路，建行合法）：走 D1 的
`get_user_setting(create=True)`，HEAD 实测 5 条（SELECT+SAVEPOINT+INSERT+RELEASE+UPDATE），
现形状 7 条 = 同样那 5 条 + 原子块的一对簿记，最后那条 UPDATE 从全行收窄到变更列。
`PUT {}`（空变更集）HEAD 仍发一条全行 UPDATE，改后零写 ——「只写变更的」的直接推论，单独钉一条
（零写靠的是 Django 对空 `update_fields` 的早退，不是视图里另有一句守卫）。
该条现在连**整表形状**一起钉（`['SAVEPOINT', 'SELECT', 'RELEASE']`，本机现量）：原先只钉动词计数，
而「1 SELECT / 0 UPDATE / 0 INSERT」对「有人把原子块摘了」毫无反应 —— 那正是这条通路最可能被
「优化」坏的方式，簿记那两条反而是它的指纹。

**PUT 的原子性**（2026-10-30 复审 Minor 2 补）：建行与补写包在同一层
`transaction.atomic()` 里 ⇒ UPDATE 失败或载荷不合法时，刚建的那条行一起回滚，库里 0 行
（口径选「不留半成品行」而不是「行留着但值不变」，因为 HEAD 根本没这层保证：本仓 DRF 3.18.3
的 `BaseSerializer.save()` 不带原子块、`ATOMIC_REQUESTS` 也没开，同轮实测的 HEAD 有行 PUT
是 `['SELECT', 'UPDATE']` 零 SAVEPOINT —— 所以这不是「D2 弄丢了 DRF 的包裹」，是补一个
HEAD 就有的洞）。判据 `SettingsPutAtomicityTests` 三条：注入失败的第二次写、越界 DPI 的 400、
以及与 HEAD 正文同轮对照的代价（净 +2 条簿记语句，SELECT/INSERT/UPDATE 计数不变）。

**登录**：不在本模块 —— 成功路径 4 → 3、`get`→`first` 省不掉语句、过期 `lockout_until`
那半句为什么不许删，全部连同实测数字搬到了 `test/backend/test_login_path_statements.py`。
"""
import json
import re

from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts import services
from apps.accounts.models import UserSetting
from apps.accounts.serializers import UserSettingSerializer
from apps.common.user_settings import DEFAULT_CPK_THRESHOLDS, get_cpk_thresholds

User = get_user_model()

# 反向 OneToOne 的实例缓存键（与 services 用同一个来源，不写死字符串）。
CACHE_KEY = services._SETTINGS_REL.cache_name

# 响应键集合**故意写死**（与 apps/accounts/tests.py 钉模板键集合同一条理由）：
# 从 serializer.Meta.fields 现取会让「加/删/改名一个键」这条判据恒真。
SETTINGS_KEYS = [
    'aggrid_header_font_size', 'analysis_chart_memory', 'analysis_chart_state',
    'chart_dpi', 'chart_engine', 'chart_height', 'chart_renderer',
    'cpk_a_threshold', 'cpk_b_threshold', 'cpk_c_threshold',
    'default_hidden_columns', 'export_filename_templates', 'export_timeout',
    'filename_wrap', 'histogram_label_offset', 'max_recent_files',
    'page_size', 'recent_files', 'sftp_download_timeout', 'table_height',
]


def _verbs(captured):
    return [q['sql'].lstrip().split(None, 1)[0].upper() for q in captured.captured_queries]


def _sqls(captured):
    return [q['sql'] for q in captured.captured_queries]


def _update_sqls(captured):
    return [s for s in _sqls(captured) if s.lstrip().upper().startswith('UPDATE')]


def _set_columns(sql):
    """取 UPDATE 的 SET 子句里被写的列名（按 SQL 顺序）。

    锚点用 Django 自己生成的 `WHERE "accounts_user_setting".`，不是裸 `WHERE`：
    JSON 列的值理论上可能含 “WHERE” 字样，裸切会截断（列名数就会少算）。
    """
    m = re.search(r'\bSET\b(.*?)\bWHERE "accounts_user_setting"\.', sql, re.S)
    return re.findall(r'"([a-z_]+)"\s*=', m.group(1))


def _fresh_user(pk):
    """复现真实请求的起点：认证通路每次都新建 User 实例，实例缓存是空的。"""
    return User.objects.get(pk=pk)


def _head_put_body(user, payload):
    """**对照基准**：commit `8478390`（本批的 HEAD，D1 收口那笔）的 `UserSettingsView.put()`
    正文**重建**，不是「HEAD 自动就是它」。重建的出处写在这里，便于读者去核而不是信这段散文：
    `git show 8478390:apps/accounts/views.py` 里那五是 `get_or_create(user=request.user)`
    → `UserSettingSerializer(settings, data=request.data, partial=True)`
    → `is_valid(raise_exception=True)` → `serializer.save()` → `Response(serializer.data)`，
    本函数按同序逐句抄下（本轮 2026-10-30 逐句对过）。

    只在一个用途里出现：与视图现形状**同轮**量出两边的语句表（原子块的代价），
    平价与否以这轮的数为准。视图的 `put()` 以后再被改，这里**不会**跟着变 —— 它是基准。
    """
    settings, _ = UserSetting.objects.get_or_create(user=user)
    serializer = UserSettingSerializer(settings, data=payload, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return serializer.data


def _client_for(user):
    """force_authenticate 直接吃**这个实例** ⇒ 请求结束后可在外面读它的 fields_cache。"""
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _body(resp):
    """视图响应与「序列化器.data」整体比：前者是渲染后的 JSON，后者是 python 对象，
    用 json 往返归一（键序两边同源，比较本身不依赖顺序的是 dict 语义）。"""
    return json.loads(resp.content.decode('utf-8'))


class SettingsGetWriteFreeTests(TestCase):
    """GET /auth/settings/ 是读请求：缺行时零写（任务口径第 1 条），响应与 HEAD 逐字节等价（第 2 条）。"""

    def setUp(self):
        self.user = User.objects.create_user(username='d2-get-norow', password='x-pass-12345678')

    def test_get_without_row_performs_zero_writes(self):
        user = _fresh_user(self.user.pk)
        self.assertEqual(UserSetting.objects.filter(user_id=user.pk).count(), 0)
        with self.assertNumQueries(1):
            resp = _client_for(user).get(reverse('settings'))
        self.assertEqual(resp.status_code, 200)
        # 语句计数之外必须再点行数：assertNumQueries 挡不住「藏在长事务里的写」，
        # 行数才是「库里到底多没多一行」的事实。
        self.assertEqual(UserSetting.objects.filter(user_id=user.pk).count(), 0,
                         'GET 建了行 ⇒ 读路径又回去写库了（get_or_create 复活）')

    def test_get_without_row_is_one_select_no_insert(self):
        """同一场景的语句**形状**：1 条 SELECT，动词表里没有 INSERT。"""
        user = _fresh_user(self.user.pk)
        client = _client_for(user)
        with CaptureQueriesContext(connection) as cap:
            resp = client.get(reverse('settings'))
        verbs = _verbs(cap)
        self.assertEqual(verbs, ['SELECT'], f'缺行 GET 应当恰好 1 条 SELECT，实测 {verbs}')
        self.assertEqual(verbs.count('INSERT'), 0)
        self.assertEqual(resp.status_code, 200)

    def test_get_without_row_serializes_the_head_row_body(self):
        """逐字节等价：孪生账号走 HEAD 原形状（get_or_create 建行 + 同一序列化器），
        与视图对无行账号的响应整体比对 —— 含 merged 模板表与 default_hidden_columns 回退。"""
        twin = User.objects.create_user(username='d2-get-twin', password='x-pass-12345678')
        row, _created = UserSetting.objects.get_or_create(user=twin)
        head_body = json.loads(json.dumps(UserSettingSerializer(row).data))

        user = _fresh_user(self.user.pk)
        resp = _client_for(user).get(reverse('settings'))
        got = _body(resp)

        self.assertEqual(got, head_body, '无行账号的 GET 响应与 HEAD「建行后序列化」不等价')
        self.assertEqual(sorted(got.keys()), SETTINGS_KEYS, '响应键集合被增删/改名')
        # 两条 HEAD 序列化里最容易走偏的合并/回退，显式点名（整体相等已覆盖，这里是出处）：
        self.assertEqual(got['export_filename_templates'],
                         head_body['export_filename_templates'])
        self.assertTrue(got['default_hidden_columns'], '空列表必须回退到默认隐藏列，不能交出 []')

    def test_get_with_row_is_unchanged_and_single_select(self):
        u = User.objects.create_user(username='d2-get-row', password='x-pass-12345678')
        row = UserSetting.objects.create(user=u, chart_dpi=150, page_size=60,
                                         default_hidden_columns=['lot_id'])
        user = _fresh_user(u.pk)
        with CaptureQueriesContext(connection) as cap:
            resp = _client_for(user).get(reverse('settings'))
        self.assertEqual(_verbs(cap), ['SELECT'], f'有行 GET 与 HEAD 同形（1 SELECT），实测 {_verbs(cap)}')
        self.assertEqual(_body(resp), json.loads(json.dumps(UserSettingSerializer(row).data)))
        self.assertEqual(sorted(_body(resp).keys()), SETTINGS_KEYS)


class SettingsGetCacheShapeTests(TestCase):
    """构造形状的决定（任务口径第 3 条）：GET 之后，`user.settings` 的直接读者看不到半成品。"""

    def setUp(self):
        self.user = User.objects.create_user(username='d2-cache', password='x-pass-12345678')

    def test_get_leaves_no_unsaved_row_on_the_user_instance(self):
        """计划正文 `UserSetting(user=request.user)` 会在这里留下 `_state.adding` 的毒缓存
        （D1 `UnsavedCacheGuardTests` 的可达性探针钉的就是这条构造路径）；`user_id=` 形状不会。
        把视图构造换回 `UserSetting(user=request.user)` ⇒ 这条红。"""
        user = _fresh_user(self.user.pk)
        _client_for(user).get(reverse('settings'))
        cached = user._state.fields_cache.get(CACHE_KEY)
        self.assertNotIsInstance(cached, UserSetting,
                                 f'GET 后缓存里出现了 UserSetting：落库行 = 读通路又在写库，'
                                 f'未落库行 = 毒缓存，两种都不许。实得 {cached!r}')
        # helper 的只读分支同样不许把它交出去（摘毒 + 回 DB 真实状态的判据在 D1，这里接线）。
        self.assertIsNone(services.get_user_setting(user))

    def test_default_readers_match_the_row_backed_outcome(self):
        """缺行 GET 后，同请求内直读 `user.settings` 的两条通路（`get_cpk_thresholds`、
        `ExportViewSet.to_excel` 的 `getattr(request.user, 'settings', None)` 形状）读到的
        结果，与 HEAD「先建行」后读行的结果逐字段相等 —— 默认实例的字段就是 model 默认值，
        建行建出来的也是，两边都走到同一组默认。"""
        user = _fresh_user(self.user.pk)
        _client_for(user).get(reverse('settings'))
        cpk_no_row = get_cpk_thresholds(user)
        self.assertIsNone(
            getattr(user, 'settings', None),
            'export 通路的读法在 GET 之后必须仍是「没有行」——读到 UserSetting 就说明 '
            'GET 写了库（HEAD）或挂了未落库实例（毒缓存形状），两者都改变本断言')

        twin = User.objects.create_user(username='d2-cache-twin', password='x-pass-12345678')
        UserSetting.objects.get_or_create(user=twin)          # HEAD 的形状
        cpk_with_row = get_cpk_thresholds(_fresh_user(twin.pk))
        self.assertEqual(cpk_no_row, cpk_with_row)
        self.assertEqual(cpk_no_row, DEFAULT_CPK_THRESHOLDS)

    def test_row_provisioned_later_in_same_instance_is_not_shadowed(self):
        """GET 落下的负缓存不许遮住随后出现的真实行：D1 的 `_prime_settings_cache` 必须
        覆盖它（本流程里「摘 adding」那条守卫不会被触发 —— GET 从不挂 adding 对象，
        这条钉的是另一支：负缓存被真实行替换后，通路 2/3 的形状立刻回到行值）。"""
        user = _fresh_user(self.user.pk)
        _client_for(user).get(reverse('settings'))            # 负缓存 = None
        other = _fresh_user(self.user.pk)
        row = UserSetting.objects.create(user=other, chart_dpi=300, cpk_a_threshold=2.5)

        with self.assertNumQueries(1):                        # get_or_create 的 get 分支
            got = services.get_user_setting(user, create=True)
        self.assertEqual(got.pk, row.pk)
        with self.assertNumQueries(0):
            self.assertIs(user.settings, got)                 # 负缓存已被行覆盖
            self.assertEqual(get_cpk_thresholds(user).cpk_a, 2.5)


class SettingsPutWriteShapeTests(TestCase):
    """PUT 只写变更列（任务口径第 4 条）：条数与 SET 子句内容都钉，正反两面。"""

    def setUp(self):
        self.user = User.objects.create_user(username='d2-put', password='x-pass-12345678')

    def test_put_partial_writes_only_the_changed_column(self):
        UserSetting.objects.create(user=self.user, chart_dpi=150, page_size=60)
        user = _fresh_user(self.user.pk)
        with CaptureQueriesContext(connection) as cap:
            resp = _client_for(user).put(reverse('settings'), {'chart_dpi': 200}, format='json')
        self.assertEqual(resp.status_code, 200)
        # 外层那对 SAVEPOINT/RELEASE 是视图的原子块（`SettingsPutAtomicityTests` 负责它的
        # 理由与代价），真实语句就是 1 SELECT + 1 UPDATE。
        self.assertEqual(_verbs(cap), ['SAVEPOINT', 'SELECT', 'UPDATE', 'RELEASE'],
                         f'有行 PUT 应 1 SELECT + 1 UPDATE（+ 原子块那对簿记），实测 {_verbs(cap)}')
        sql = _update_sqls(cap)[0]
        self.assertIn('"chart_dpi"', sql, f'SET 里必须有变更列：{sql}')
        self.assertIn('"chart_dpi" = 200', sql)
        self.assertNotIn('"page_size"', sql, f'未变更列不许进 SET（HEAD 是全行 UPDATE）：{sql}')
        self.assertNotIn('"user_id"', sql, f'FK 列不许进 SET：{sql}')
        row = UserSetting.objects.get(user_id=user.pk)
        self.assertEqual((row.chart_dpi, row.page_size), (200, 60))
        self.assertEqual(_body(resp)['chart_dpi'], 200)

    def test_put_two_columns_set_exactly_those(self):
        UserSetting.objects.create(user=self.user, chart_dpi=150, page_size=60)
        user = _fresh_user(self.user.pk)
        with CaptureQueriesContext(connection) as cap:
            _client_for(user).put(reverse('settings'),
                                  {'chart_dpi': 200, 'page_size': 80}, format='json')
        sql = _update_sqls(cap)[0]
        self.assertIn('"chart_dpi"', sql)
        self.assertIn('"page_size"', sql)
        self.assertNotIn('"table_height"', sql)
        self.assertNotIn('"cpk_a_threshold"', sql)
        self.assertEqual(UserSetting.objects.get(user_id=user.pk).page_size, 80)

    def test_put_without_row_provisions_and_narrows_the_update(self):
        """写通路建行合法：HEAD 实测 5 条（SELECT+SAVEPOINT+INSERT+RELEASE+UPDATE），
        现形状 7 条 = 那 5 条 + 视图原子块的一对 SAVEPOINT/RELEASE；最后那条 UPDATE 收窄到变更列。
        逐条对照在 `SettingsPutAtomicityTests.test_atomic_wrapper_costs_two_extra_savepoint_statements`。"""
        user = _fresh_user(self.user.pk)
        self.assertEqual(UserSetting.objects.filter(user_id=user.pk).count(), 0)
        with CaptureQueriesContext(connection) as cap:
            resp = _client_for(user).put(reverse('settings'), {'chart_dpi': 200}, format='json')
        verbs = _verbs(cap)
        self.assertEqual(len(verbs), 7,
                         f'缺行 PUT = HEAD 的 5 条 + 原子块那对簿记（实测 7），动词表 {verbs}')
        self.assertEqual(verbs.count('SELECT'), 1)
        self.assertEqual(verbs.count('INSERT'), 1)
        self.assertEqual(verbs.count('UPDATE'), 1)
        sql = _update_sqls(cap)[0]
        self.assertIn('"chart_dpi"', sql)
        self.assertNotIn('"page_size"', sql, f'建行后的补写也不许全行 UPDATE：{sql}')
        self.assertEqual(resp.status_code, 200)
        row = UserSetting.objects.get(user_id=user.pk)
        self.assertEqual(row.chart_dpi, 200)

    def test_put_empty_body_writes_nothing(self):
        """空变更集 ⇒ 空 update_fields ⇒ 一条 UPDATE 都不发（HEAD 会重写整行）。

        不发 UPDATE 的原因是 Django 6.0.9 `db/models/base.py:843` 对空 `update_fields` 直接早退。
        原先本条还自称「视图里没有 `if changed:` 守卫」的判据 —— **那句撤回**：把守卫加回去
        本类照样 `Ran 20 / OK`（两轮各量一次：`tasks/d2f/mut_guard_readd.log`、
        `tasks/d2q/mut_guard_readd.log`），它压根测不出守卫的有无。守卫确实是死码
        （复评审 Minor 1，已删），但判据不在这条。
        把这句还原成 `settings.save()`（全行写）⇒ 本条与
        `test_put_partial_writes_only_the_changed_column` 一起红，那才是本条的判据。
        """
        UserSetting.objects.create(user=self.user, chart_dpi=150)
        user = _fresh_user(self.user.pk)
        with CaptureQueriesContext(connection) as cap:
            resp = _client_for(user).put(reverse('settings'), {}, format='json')
        verbs = _verbs(cap)
        # 整表形状也钉（2026-10-30 收尾轮 Minor）。原来这里只钉动词计数，理由写的是
        # 「原子块那对 SAVEPOINT/RELEASE 只是事务簿记、承诺的内容是零写」—— 那个理由现在
        # 反过来成立：簿记恰是「有人把 `transaction.atomic()` 摘了」的**唯一**指纹，
        # 而三条动词计数（1 SELECT / 0 UPDATE / 0 INSERT）对摘原子块毫无反应。
        # 本轮实测到的红（`tasks/d2r/mut_noatomic.log`，逐字）：
        #   AssertionError: Lists differ: ['SELECT'] != ['SAVEPOINT', 'SELECT', 'RELEASE']
        # 另外两种「优化」由这条同形状拦住（是断言的直接推论，本轮未另跑变异）：
        # 不读行直接交出载荷 ⇒ 少那条 SELECT；换回全行 `save()` ⇒ 多一条 UPDATE。
        self.assertEqual(verbs, ['SAVEPOINT', 'SELECT', 'RELEASE'],
                         f'PUT {{}} 的形状 = 原子块那对簿记 + 1 条 SELECT，实测 {verbs}')
        # 语义承诺单独写一行，别让形状替它说话：零写。
        self.assertEqual(verbs.count('UPDATE'), 0, f'PUT {{}} 不许发 UPDATE（HEAD 会重写整行），实测 {verbs}')
        self.assertEqual(verbs.count('INSERT'), 0, f'PUT {{}} 不许建行，实测 {verbs}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_body(resp)['chart_dpi'], 150)
        self.assertEqual(UserSetting.objects.get(user_id=user.pk).chart_dpi, 150)

    def test_head_full_row_update_sets_26_columns_not_the_20_serializer_fields(
            self):
        """视图 docstring 里那个列数的唯一出处（复评审 Important：原来写的 21 是错的）。

        两个量别混，原来就是把序列化器字段数当成了 SET 列数：
        * 全行 UPDATE 的 SET 列数 = model 的非 pk concrete 列 = **26**
          （`user_id` + 25 个设置列，含 5 个 `sftp_last_*`），实测自下面这条 SQL；
        * `UserSettingSerializer.Meta.fields` = **20**（5 个 `sftp_last_*` 不在白名单，
          由 `apps.sftp` 直接 ORM 读写）。
        HEAD 那句 `serializer.save()` 写的是前者 ⇒ 「改一个值重写 26 列」才是 PUT 收窄的依据；
        按 20 记账会把收益说小一半，而这个数一旦有人加列就会变 ⇒ 这里从 SQL 现量，
        并和 `_meta` 交叉核对（加一列 ⇒ 本条红 ⇒ 逼着改注释，而不是让注释漂着）。
        """
        UserSetting.objects.create(user=self.user, chart_dpi=150)
        row = UserSetting.objects.get(user_id=self.user.pk)
        with CaptureQueriesContext(connection) as cap:
            row.chart_dpi = 200          # 只改一个值
            row.save()                   # HEAD 的形状：不带 update_fields 的全行写
        cols = _set_columns(_update_sqls(cap)[0])
        self.assertEqual(
            len(cols), 26,
            f'全行 UPDATE 的 SET 列数实测 {len(cols)}：注释里的数字必须跟这个走，{cols}')
        self.assertEqual(len(cols), len(UserSetting._meta.concrete_fields) - 1,
                         'SET 列数应等于 model 非 pk concrete 列数（pk 只进 WHERE）')
        self.assertIn('user_id', cols, 'FK 列也在 SET 里 —— 这正是收窄要摘掉的')
        self.assertEqual([c for c in cols if c.startswith('sftp_last_')],
                         ['sftp_last_path', 'sftp_last_config', 'sftp_last_host',
                          'sftp_last_port', 'sftp_last_username'],
                         '26 列里含 5 个序列化器不暴露的 sftp_last_*')
        self.assertEqual(len(UserSettingSerializer.Meta.fields), 20)
        self.assertFalse(set(UserSettingSerializer.Meta.fields) & set(
            c for c in cols if c.startswith('sftp_last_')))
        # 同一实例收窄后：SET 只剩变更列 —— 26 → 1 就是这条通路省下的写。
        with CaptureQueriesContext(connection) as narrow:
            row.chart_dpi = 210
            row.save(update_fields=['chart_dpi'])
        self.assertEqual(_set_columns(_update_sqls(narrow)[0]), ['chart_dpi'])


class SettingsPutAtomicityTests(TestCase):
    """PUT 的建行与补写必须在同一个原子块里（复评审 Minor 2）。

    先更正这条 finding 的前提：本仓锁的 DRF 3.18.3 里 `BaseSerializer.save()`
    **没有** `transaction.atomic()`（`.venv/Lib/site-packages/rest_framework/serializers.py`
    177-211 行只有 `update`/`create` 分派；整个 rest_framework 包只剩 `views.py:68` 读
    `ATOMIC_REQUESTS`，而 `config/settings/*.py` 没开这个开关）。同轮实测量在
    `test_atomic_wrapper_costs_two_extra_savepoint_statements`：HEAD 的有行 PUT 是
    `['SELECT', 'UPDATE']`，零 SAVEPOINT ⇒ 「D2 弄丢了 DRF 的包裹」不成立，
    HEAD 本来就没包裹。

    但洞是真的，而且不是「半行的列」那种洞（一条 UPDATE 自身就是原子的）：
    缺行 PUT 的 INSERT 先落，随后那条收窄 UPDATE 若失败，库里就留下一条**只有默认值**的行 ——
    请求失败了、账号却凭空多了设置行；400（校验不过）走的是同一条路。
    加 `atomic()` 把这两句都收进同一事务 ⇒ 要么都落要么都不落。
    """

    def setUp(self):
        self.user = User.objects.create_user(username='d2-put-tx', password='x-pass-12345678')

    def test_put_update_failure_rolls_back_the_provisioned_row(self):
        """缺行 PUT：INSERT 落了、随后那条 UPDATE 失败 ⇒ 库里 **0 行**（口径：不留半成品行）。

        注入点选在「第二次写」：`get_or_create` 的建行走 `Manager.create` →
        `save(force_insert=True, using=...)`，**不带** `update_fields`；视图那句
        `save(update_fields=list(changed))` 才带 ⇒ 只炸后者，INSERT 保持真实。
        摘掉视图的 `atomic()` ⇒ 本条红（数到 1：那条默认值行活下来了）。
        """
        user = _fresh_user(self.user.pk)
        original_save = UserSetting.save

        def save_then_explode(instance, *args, **kwargs):
            if kwargs.get('update_fields') is not None:
                raise DatabaseError('注入：收窄后的那条 UPDATE 失败')
            return original_save(instance, *args, **kwargs)

        # 还原走 `addCleanup`，不走 `try/finally`（lessons **R6③**：monkey-patch 必须
        # addCleanup 还原）。两种形状分开登记，别一路 `delattr` 走到底：
        # 今天 `UserSetting`（`apps/accounts/models.py:56`）**没有** `save()` 覆写 ——
        # 类里只有 `Meta` 与 `__str__`，所以 `UserSetting.save` 是继承来的 `Model.save`，
        # 遮蔽只是往子类 `__dict__` 塞了个属性，`delattr` 恰好把它摘掉、回到继承。
        # **但这条只在「模型没有 `save()` 覆写」时成立**：哪天有人给 `UserSetting` 加了
        # `save()`，`delattr` 会把那条覆写一起删掉，本用例就此变成后续用例的污染源
        # （而且污染的是生产行为）。所以按 `'save' in UserSetting.__dict__` 分流 ——
        # 有覆写就 `setattr` 还原成覆写本身，这条判据对未来那次改动是**免维护**的。
        if 'save' in UserSetting.__dict__:
            self.addCleanup(setattr, UserSetting, 'save', original_save)
        else:
            self.addCleanup(delattr, UserSetting, 'save')
        UserSetting.save = save_then_explode

        resp = _client_for(user).put(reverse('settings'), {'chart_dpi': 200},
                                     format='json')
        # 失败以 **响应 500** 的形式 observable，不是抛回客户端：`config/settings/unit.py:34`
        # 是 DEBUG=True，Django 把视图异常转成 500 页（本仓注入类用例同此约定）。
        # 回滚发生在视图内那层 `atomic().__exit__`，早于异常被转换，所以两种档都成立。
        self.assertEqual(resp.status_code, 500, '注入的那条 UPDATE 必须真的失败掉这次 PUT')
        self.assertEqual(
            UserSetting.objects.filter(user_id=user.pk).count(), 0,
            '失败的 PUT 在库里留了一条只有默认值的行 ⇒ 建行那条 INSERT 没被回滚')

    def test_put_invalid_payload_rolls_back_the_provisioned_row(self):
        """400 也不许在库里留下东西：`is_valid(raise_exception=True)` 在原子块内。

        HEAD 是 `get_or_create` 先落行、再校验 ⇒ 一个越界 DPI 的 400 给无行账号凭空建一条
        设置行（本条在 HEAD 上红）。这也是本批**有意**偏离 HEAD 的一处：写请求返回 400
        时数据库不该有新行。
        """
        user = _fresh_user(self.user.pk)
        resp = _client_for(user).put(reverse('settings'), {'chart_dpi': 99999},
                                     format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(UserSetting.objects.filter(user_id=user.pk).count(), 0,
                         '无效载荷的 PUT 建了行：400 应当零写（校验在原子块内）')

    def test_atomic_wrapper_costs_two_extra_savepoint_statements(self):
        """代价只有一对 SAVEPOINT/RELEASE：与 HEAD 正文同轮对照，三类真实语句一字不差。

        TestCase 自己包了一层原子块 ⇒ 视图那句 `atomic()` 落成 SAVEPOINT；
        真请求在 autocommit 下它是 BEGIN/COMMIT，把「INSERT 一条隐式事务 + UPDATE 一条」
        合成一条事务，不是额外往返。所以这条不是「D2 的 PUT 变慢了 2 条 SQL」，
        而是把新增保证的账面写死：谁再把原子块摘掉，这里给的数就会漂。

        两边的行都由**另一个** User 实例建出来：`UserSetting.objects.create(user=u)` 会把
        新实例挂进 `u` 的反向缓存，用同一个实例去发请求就量不到那条 SELECT（D1 的缓存形状）。
        """
        head_owner = User.objects.create_user(username='d2-put-tx-head',
                                              password='x-pass-12345678')
        UserSetting.objects.create(user=head_owner, chart_dpi=150)
        head_user = _fresh_user(head_owner.pk)
        with CaptureQueriesContext(connection) as head_cap:
            _head_put_body(head_user, {'chart_dpi': 200})

        UserSetting.objects.create(user=self.user, chart_dpi=150)
        user = _fresh_user(self.user.pk)
        with CaptureQueriesContext(connection) as new_cap:
            resp = _client_for(user).put(reverse('settings'), {'chart_dpi': 200},
                                         format='json')
        self.assertEqual(resp.status_code, 200)

        head, new = _verbs(head_cap), _verbs(new_cap)
        self.assertEqual(head.count('SELECT'), 1, f'对照基准自己也要成立：head={head}')
        for verb in ('SELECT', 'INSERT', 'UPDATE'):
            self.assertEqual(new.count(verb), head.count(verb),
                             f'{verb} 计数不许因原子块而变：head={head} new={new}')
        self.assertEqual(new.count('SAVEPOINT'), head.count('SAVEPOINT') + 1)
        self.assertEqual(new.count('RELEASE'), head.count('RELEASE') + 1,
                         f'原子块的净代价只有一对 SAVEPOINT/RELEASE：head={head} new={new}')
        self.assertEqual(len(new), len(head) + 2,
                         f'原子块的净代价应为 2 条：head={head} new={new}')
        self.assertEqual(UserSetting.objects.get(user_id=user.pk).chart_dpi, 200)
        self.assertEqual(UserSetting.objects.get(user_id=head_user.pk).chart_dpi, 200)
