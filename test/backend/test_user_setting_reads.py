"""D1 · 用户设置读取收敛到单一入口（三通路合一）。

三条通路在收敛前各发各的 SELECT。这些数不是抄计划正文，是本机实测（2026-10-30，
`.venv` = Python 3.13.12 / Django 6.0.9，`python -X utf8 manage.py test`），而且**已经断言化**：

* 「单条通路各 1 次、同一个 user 实例按请求顺序跑完三条共 3 次 ⇒ 收敛后 1 次」由
  `OneSelectPerRequestTests.test_three_helpers_share_one_select` 承重（改造前红字 `3 != 1`）。
* 「同一个实例跑三轮 = **7 → 1**」那个 **7** 由 `HeadBaselineProbeTests` 现场量出来，不是回忆：
  `_head_round()` 把收敛前三段读法逐字重放（通路 1 `get_or_create` 每轮 1 条 +
  通路 2 `filter().values_list().first()` 每轮 1 条 + 通路 3 `user.settings` 描述符只在
  第一轮 1 条，之后命中 `user._state.fields_cache` ⇒ 3 + 3 + 1 = 7），断言
  `_verbs == ['SELECT'] * 7`；同口径的另一条断言走 helper 是 1 条
  （`test_the_same_three_rounds_through_the_helper_cost_one`，改造前它的红字就是 `7 != 1`）。
  想复核就把 `apps/export/user_prefs.py` 换回 manager 直读、把
  `apps/common/export_naming.py` 换回裸 `get_or_create` 再跑一次 —— 基线形状被改动时
  探针先炸，注释里的数字不许再靠「我记得」。

下面三条是**收敛前**的形状（逐条对应 `_head_round()`；收敛后三条都经由
`apps/accounts/services.py::get_user_setting`，通路 3 例外 —— 它必须留在描述符那一侧）：

* 通路 1 `apps/common/export_naming.py::render_export_filename` —— manager `get_or_create`
  （**读 + 缺行即建**，`apps/common/tests.py` 与 `test/backend/test_weight_export_api.py` 都吃着这个契约）；
* 通路 2 `apps/export/user_prefs.py::get_export_dpi` —— manager `filter().values_list().first()`
  （**只读**，缺行回退默认值，今天一条 INSERT 都不发）；
* 通路 3 `apps/common/user_settings.py::get_cpk_thresholds` —— `user.settings` 反向描述符（只读，
  且这个模块**不许** import `apps.accounts.models`：worker 侧链路要在没有 Django 的 spawn 子进程里 import 它）。

收敛口径与三个不许含糊的地方：

1. helper **先看实例缓存（这一步一条 SQL 都不发）**，未命中才读库；读到/建完都塞回
   `user._state.fields_cache` ⇒ 同实例第二次起命中 Django 那份反向缓存，三条通路合计 1 条 SELECT。
2. helper **默认只读**，`create=True` 才建行（选型 (b)）。理由：把通路 2 也接上「缺失即建」会把今天
   零写的读路径变成会 INSERT 的路径 —— 而「账号没有 settings 行」不是理论态：`standalone._bootstrap`
   用 `User.objects.create_superuser` 建首个管理员（`UserManager` 只补 `role`，全仓没有 post_save
   信号建行，`seed_users.py` 的 legacy 分支注释也写着「Legacy bootstraps never created settings rows」），
   这个管理员在第一次进设置页/导出前就是没有行的。下一个任务（D2「设置页 GET 不再写库」）要的正是
   同一条口径，这里不能反着走。
3. 实例缓存里躺着**没落库**的实例（`_state.adding`）时按「没有」处理（判据 7
   `UnsavedCacheGuardTests`，含两条错误形状的**可跑**断言）：`create=True` 不许被它短路成
   「库里 0 行也算建好了」，只读分支也不许把 `pk=None` 的对象当真实设置交出去。
   这种对象**今天就构造得出来**（本轮改掉的旧口径「树内构造不出」是错的）：Django 的
   `Model.__init__` 在 create 分支上先挂反向缓存、后发 INSERT，INSERT 一抛（并发重复建行撞
   UNIQUE）毒缓存就跟着那个 `user` 实例过完整个请求 —— 判据在
   `test_the_unsaved_cache_is_reachable_in_tree_today`。D2「设置页 GET 返回未落库的默认实例」
   只是把同一个形状从异常路径搬到正常路径，届时的口径是 **未落库那份留在调用方自己的
   局部变量里**，不挂 `user.settings`。
4. helper 伸手进的 Django 私有面（`FieldCacheMixin` 的 `cache_name`/`get_cached_value`/
   `set_cached_value`/`delete_cached_value`）按**运行时**钉子，判据在
   `test/backend/test_settings_cache_api_pin.py`（同批拆分，唯一原因是本模块的 600 行绊线）：
   round-trip 钉子 + 对照组 + 「面断了必须出声」。改名后 `get_export_dpi` 过去会被
   `except Exception` 咽成静默读默认值（评审实测 `100 != 300`），那不是一个
   「用户没有设置行」，那是一次错读。
"""
import os
import pathlib
import subprocess
import sys

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.utils import IntegrityError
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts import services
from apps.accounts.models import UserSetting
from apps.accounts.services import get_user_setting
from apps.common.export_naming import render_export_filename
from apps.common.user_settings import DEFAULT_CPK_THRESHOLDS, get_cpk_thresholds
from apps.export.charts import EXPORT_DPI_DEFAULT
from apps.export.user_prefs import get_export_dpi

User = get_user_model()

CTX = {'filename': 'gage_m_S1'}

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _verbs(captured):
    """把 CaptureQueriesContext 的结果压成语句首词表（含 `SAVEPOINT`/`RELEASE` 这类事务管线噪声）。

    判据只看**计数**（SELECT 几条、INSERT 几条）与**总条数对 HEAD 的平价**，不钉顺序：
    顺序是 Django 事务管线（atomic/savepoint 何时开、何时 release）的内部实现，
    把 `[SELECT, SAVEPOINT, INSERT, RELEASE]` 写死等于给下一次 ORM 升级埋一条假红，
    而「读路径没多出 SELECT」「建行只发一条 INSERT」这两件事本来就与顺序无关。
    """
    return [q['sql'].lstrip().split(None, 1)[0].upper() for q in captured.captured_queries]


def _captured_verbs(fn, *args, **kwargs):
    captured = CaptureQueriesContext(connection)
    with captured:
        fn(*args, **kwargs)
    return _verbs(captured)


def _head_provisioning_verbs(user):
    """HEAD 通路 1 的裸 `UserSetting.objects.get_or_create(user=…)` 现场量一遍当参照系。"""
    return _captured_verbs(UserSetting.objects.get_or_create, user=user)


def _fresh_user(pk):
    """复现一条真实请求的起点：认证中间件每次都新建 User 实例，实例缓存是空的。"""
    return User.objects.get(pk=pk)


def _poison_with_unsaved(user, **values):
    """把一条**没落库**的 `UserSetting` 挂进 `user` 的反向缓存（D2 要的那个形状）。

    走 Django 公开的 setter：`ReverseOneToOneDescriptor.__set__` 只 `set_cached_value`，
    既不 save 也不发 SQL ⇒ 缓存里躺着 `pk is None` 且 `_state.adding is True` 的对象。
    """
    user.settings = UserSetting(user=user, **values)
    return user.settings


def _head_round(user):
    """收敛前（HEAD）三条通路各自的读法，原样重放一轮 —— 只为把「7」量出来。"""
    UserSetting.objects.get_or_create(user=user)                                  # 通路 1
    UserSetting.objects.filter(user=user).values_list('chart_dpi', flat=True).first()  # 通路 2
    return getattr(user, 'settings', None)                                        # 通路 3


# 私有面（`FieldCacheMixin` 的四个成员）的运行时钉子与「断了要出声」那两支判据住在
# `test/backend/test_settings_cache_api_pin.py` —— 600 行绊线把本模块拆成两份，
# 判据一条没少，只是分家；本模块继续管「三通路收敛」的形状本身。


class _SettingsReadRaises:
    """`settings` 取值就炸的替身，用来喂通路 2 的「绝不抛」契约。"""
    pk = 1

    @property
    def settings(self):
        raise RuntimeError('模拟 DB 故障')


class OneSelectPerRequestTests(TestCase):
    """判据 1：三条通路在同一个 user 实例上只花 1 条 SELECT。"""

    def setUp(self):
        self.user = User.objects.create_user(username='d1-owner', password='x-pass-12345678')
        UserSetting.objects.create(
            user=self.user, chart_dpi=300, cpk_a_threshold=2.5, cpk_b_threshold=1.8,
            export_filename_templates={'to_excel': 'X-{filename}'})

    def test_three_helpers_share_one_select(self):
        user = _fresh_user(self.user.pk)
        with self.assertNumQueries(1):
            # 三条都断**值**，不然「helper 返回默认值」也能混过只断语句数的判据
            self.assertEqual(render_export_filename(user, 'to_excel', 'xlsx', CTX),
                             'X-gage_m_S1.xlsx')
            self.assertEqual(get_export_dpi(user), 300)
            self.assertEqual(get_cpk_thresholds(user).cpk_a, 2.5)

    def test_repeated_rounds_on_the_same_instance_still_cost_zero(self):
        """「每实例一次」不是「只有第一轮去重」：第二轮起必须整条链零查询。"""
        user = _fresh_user(self.user.pk)
        with self.assertNumQueries(1):
            for _ in range(3):
                render_export_filename(user, 'to_excel', 'xlsx', CTX)
                get_export_dpi(user)
                get_cpk_thresholds(user)

    def test_helper_itself_hits_the_instance_cache(self):
        """helper 自己的判据：第二次调用零查询，且返回的是同一个实例。"""
        user = _fresh_user(self.user.pk)
        with self.assertNumQueries(1):
            first = get_user_setting(user)
        self.assertIsNotNone(first)
        with self.assertNumQueries(0):
            second = get_user_setting(user)
        self.assertIs(first, second)
        with self.assertNumQueries(0):
            self.assertIs(user.settings, first)      # Django 挂在实例上的反向缓存就是它


class ReadOnlyDefaultTests(TestCase):
    """判据 2（选型 (b)）：helper 默认只读，通路 2 不许因为被接上 helper 而开始写库。"""

    def setUp(self):
        self.user = User.objects.create_user(username='d1-no-row', password='x-pass-12345678')

    def test_get_user_setting_is_read_only_by_default(self):
        user = _fresh_user(self.user.pk)
        captured = CaptureQueriesContext(connection)
        with captured:
            self.assertIsNone(get_user_setting(user))
        self.assertNotIn('INSERT', _verbs(captured),
                         'helper 默认读就发 INSERT ⇒ 通路 2 从「零写的读」变成「会写的读」（(a) 的坑）')
        self.assertEqual(UserSetting.objects.filter(user_id=user.pk).count(), 0)

    def test_get_export_dpi_does_not_create_a_row(self):
        """通路 2 的既有契约：缺行只回退默认值（`apps/export/tests_chart_dpi.py` 钉的是值，
        这条钉的是它今天顺带不发的那条 INSERT）。"""
        user = _fresh_user(self.user.pk)
        captured = CaptureQueriesContext(connection)
        with captured:
            self.assertEqual(get_export_dpi(user), EXPORT_DPI_DEFAULT)
        self.assertEqual(_verbs(captured).count('SELECT'), 1,
                         f'只读通路应当 1 条 SELECT，实测 {_verbs(captured)}')
        self.assertNotIn('INSERT', _verbs(captured))
        self.assertEqual(UserSetting.objects.filter(user_id=user.pk).count(), 0)

    def test_get_cpk_thresholds_stays_descriptor_only(self):
        """通路 3 不动：缺行 → 逐字段回退默认，零写。"""
        user = _fresh_user(self.user.pk)
        captured = CaptureQueriesContext(connection)
        with captured:
            self.assertEqual(get_cpk_thresholds(user), DEFAULT_CPK_THRESHOLDS)
        self.assertNotIn('INSERT', _verbs(captured))
        self.assertEqual(UserSetting.objects.filter(user_id=user.pk).count(), 0)


class ExplicitCreateTests(TestCase):
    """判据 3：唯一需要「缺失即建」语义的调用方用 `create=True`，且建行后仍然共享缓存。"""

    def setUp(self):
        self.user = User.objects.create_user(username='d1-lazy', password='x-pass-12345678')

    def test_create_true_inserts_the_missing_row_once(self):
        user = _fresh_user(self.user.pk)
        captured = CaptureQueriesContext(connection)
        with captured:
            setting = get_user_setting(user, create=True)
        self.assertIsNotNone(setting)
        self.assertEqual(_verbs(captured).count('INSERT'), 1,
                         f'缺失即建应当正好 1 条 INSERT，实测 {_verbs(captured)}')
        self.assertEqual(UserSetting.objects.filter(user_id=user.pk).count(), 1)
        with self.assertNumQueries(0):                   # 建出来的行必须挂上实例缓存
            self.assertIs(get_user_setting(user), setting)

    def test_render_export_filename_still_provisions_a_missing_row(self):
        """接线证明：通路 1 确实把 `create=True` 传下去了（只断 helper 的开关挡不住调用点漏传）。"""
        user = _fresh_user(self.user.pk)
        captured = CaptureQueriesContext(connection)
        with captured:
            name = render_export_filename(user, 'to_excel', 'xlsx', CTX)
        self.assertEqual(name, 'gage_m_S1_analysis.xlsx')
        self.assertIn('INSERT', _verbs(captured),
                      '通路 1 的 get_or_create 语义丢了 ⇒ apps/common/tests.py 那批直接调它的用例会红')
        self.assertEqual(UserSetting.objects.filter(user_id=user.pk).count(), 1)
        with self.assertNumQueries(0):                   # 建完的行同时喂给通路 2/3
            self.assertEqual(get_export_dpi(user), EXPORT_DPI_DEFAULT)
            self.assertEqual(get_cpk_thresholds(user), DEFAULT_CPK_THRESHOLDS)


class StaleNegativeCacheTests(TestCase):
    """判据 4：helper 必须把取回的行塞回实例缓存 —— 描述符对「没有」也做负缓存。

    形状是并发可达的：本请求先读到没有行（Django 把 None 缓存进 `user._state.fields_cache`），
    随后别的实例把行建了（`apps/jobs/views.py` 提交作业、`apps/sftp/views.py`、设置页 PUT 都会建）。
    不塞回去，同实例后续读取会一直吃那份陈旧负缓存 —— 通路 3 直接返回默认阈值，通路 2 改成
    描述符优先后也会跟着返回默认 DPI（今天它走 manager 直读，看不见负缓存，所以那是**新引入的**退化）。
    """

    def setUp(self):
        self.user = User.objects.create_user(username='d1-race', password='x-pass-12345678')

    def test_stash_replaces_a_negative_cache_when_the_row_turns_up(self):
        user = _fresh_user(self.user.pk)
        with self.assertNumQueries(1):
            self.assertIsNone(get_user_setting(user))        # 落负缓存
        other = _fresh_user(self.user.pk)                    # 「另一个请求」的实例
        UserSetting.objects.create(user=other, chart_dpi=300, cpk_a_threshold=2.5)

        with self.assertNumQueries(1):                       # manager 取回，不碰 user 的缓存
            setting = get_user_setting(user, create=True)
        self.assertEqual(setting.chart_dpi, 300)

        with self.assertNumQueries(0):
            self.assertIs(user.settings, setting)            # 删掉 stash ⇒ 这里抛 RelatedObjectDoesNotExist
            self.assertEqual(get_export_dpi(user), 300)      # 吃陈旧负缓存 ⇒ 会回退默认值
            self.assertEqual(get_cpk_thresholds(user).cpk_a, 2.5)   # 同上，默认值是 1.67


class UnsavedCacheGuardTests(TestCase):
    """判据 7：缓存里躺着一条**没落库**的行时，必须当它「没有」——`_state.adding` 是判据。

    **这种对象今天就在树内可达**（本轮改掉的口径，Important 4）：Django 的
    `Model.__init__` 在拿到正向 FK 值时顺手把实例挂上反向缓存（`ForwardOneToOneDescriptor.__set__`
    → `set_cached_value`），`Manager.create()` 与 `get_or_create()` 的**建分支**都走这条路，
    挂缓存的时刻 INSERT 还没成功 ⇒ 只要 INSERT 抛（并发下两个请求同时给同一个 user 建行，
    后到的那个撞 UNIQUE；或字段校验/触发器/磁盘故障），毒缓存就跟着那个 `user` 实例活完整个请求。
    `test_the_unsaved_cache_is_reachable_in_tree_today` 把这句话钉成断言。
    D2（设置页 GET 不再写库）只是把同一个形状**从异常路径搬到正常路径**上 —— 计划的正是
    「返回一个尚未落库的默认实例」，一落地就踩在这三个洞上：
    ① `create=True` 的建行被静默短路（DB 里 0 行，用户设置永远存不下来）；
    ② 通路 2/3 把这份未落库对象的默认字段当真值读走；
    ③ 调用方 `user.settings.<field> = …; user.settings.save()` 在真实行已存在时撞 UNIQUE，
       同一次写带 `update_fields=` 时是「没有 pk 不许强制 UPDATE」。
       两条错误形状由 `test_unsaved_cache_writes_raise_the_two_claimed_errors` **跑**出来
       （本轮之前那两句只在 gitignored 的 `tasks/` 日志里红过一次，规则不认那份证据）。
    """

    def setUp(self):
        self.user = User.objects.create_user(username='d1-unsaved', password='x-pass-12345678')

    def test_create_true_without_a_row_returns_a_saved_instance(self):
        """前置（今天已过）：`create=True` 交出去的对象必须已落库 —— 不是 `pk=None`。"""
        user = _fresh_user(self.user.pk)
        setting = get_user_setting(user, create=True)
        self.assertIsNotNone(setting.pk)
        self.assertFalse(setting._state.adding)
        self.assertEqual(UserSetting.objects.filter(user_id=user.pk).count(), 1)

    def test_the_unsaved_cache_is_reachable_in_tree_today(self):
        """Important 4 的事实半边：不靠 D2，Django 自己就会把未落库实例挂上反向缓存。

        两步都零「构造技巧」：① 公开构造器 `UserSetting(user=u)` 之后 `u` 的缓存里就是
        一条 `_state.adding` 的对象；② `Manager.create()` 的 INSERT 抛错（这里用并发重复行
        撞 UNIQUE 复现）之后，那份缓存**留在** `u` 上 —— 这就是「今天的树内也构造得出来」。
        """
        other = _fresh_user(self.user.pk)
        UserSetting.objects.create(user=other, chart_dpi=200)      # 行已由别的实例建好
        user = _fresh_user(self.user.pk)
        cache_key = services._SETTINGS_REL.cache_name

        UserSetting(user=user, chart_dpi=300)                      # 公开构造器，零 SQL
        self.assertTrue(user._state.fields_cache[cache_key]._state.adding,
                        '构造器不挂反向缓存了 ⇒ Django 改了这块，helper 的判据要重读')
        with self.assertRaises(IntegrityError):
            UserSetting.objects.create(user=user, chart_dpi=300)   # 建分支：先挂缓存，INSERT 再抛
        self.assertTrue(user._state.fields_cache[cache_key]._state.adding,
                        'INSERT 抛了缓存却跟着留下 ⇒ 毒缓存今天可达（helper 的判据不是理论练习）')
        # 摘掉 `_state.adding` 判据 ⇒ 下面这句就把那份未落库对象当真实设置交出去（通路 2/3 的洞 ②）
        self.assertEqual(get_export_dpi(user), EXPORT_DPI_DEFAULT,
                         '毒缓存没被摘掉 ⇒ 读到的是那条没落库的 300')

    def test_create_true_on_a_poisoned_cache_still_provisions_the_row(self):
        user = _fresh_user(self.user.pk)
        _poison_with_unsaved(user, chart_dpi=300)
        captured = CaptureQueriesContext(connection)
        with captured:
            setting = get_user_setting(user, create=True)
        self.assertFalse(setting._state.adding, '未落库的缓存值被当成「已有行」交出去了')
        self.assertIsNotNone(setting.pk)
        self.assertEqual(UserSetting.objects.filter(user_id=user.pk).count(), 1,
                         f'建行被短路：DB 里 0 行，实测语句 {_verbs(captured)}')
        self.assertEqual(UserSetting.objects.get(user_id=user.pk).pk, setting.pk)

    def test_poisoned_read_only_does_not_hand_back_an_unsaved_instance(self):
        """只读分支同样不许把未落库的缓存对象交出去（通路 2/3 会把它当真实设置）。"""
        user = _fresh_user(self.user.pk)
        _poison_with_unsaved(user, chart_dpi=300, cpk_a_threshold=2.5)
        captured = CaptureQueriesContext(connection)
        with captured:
            self.assertIsNone(get_user_setting(user), '缺行时该返回 None，而不是那条没落库的缓存')
        self.assertNotIn('INSERT', _verbs(captured), '摘毒缓存顺手建行 ⇒ 又给读路径加了写')
        self.assertEqual(UserSetting.objects.filter(user_id=user.pk).count(), 0)
        self.assertEqual(get_export_dpi(user), EXPORT_DPI_DEFAULT,
                         '通路 2 读到未落库缓存的 300 ⇒ 设置页 GET 不写库时用户会看到没存的值')

    def test_guard_replaces_poisoned_cache_with_the_real_row(self):
        user = _fresh_user(self.user.pk)
        real = UserSetting.objects.create(user=user, chart_dpi=200)
        _poison_with_unsaved(user, chart_dpi=300)
        with self.assertNumQueries(1):
            setting = get_user_setting(user, create=True)
        self.assertEqual(setting.pk, real.pk)
        self.assertEqual(setting.chart_dpi, 200, '交出去的必须是库里那行，不是缓存里那份')
        with self.assertNumQueries(0):
            self.assertIs(user.settings, setting)          # 毒缓存已被真实行替换

    def test_unsaved_cache_writes_raise_the_two_claimed_errors(self):
        """注释里那两条红字（Important 3）：本轮之前它们只在 gitignored 日志里存在过。
        这条不经过 helper，直接喂「真实行已存在 + 缓存里躺着未落库实例」那个形状，把两条
        错误各跑一遍 ⇒ 文案有出处，出处是可复跑的断言。

        口径：**只断异常类型 + 稳定子串**，不钉整句。两句都是 Django 内部文案
        （`update_fields` 那句出自 `Model.save()` 的守卫，本批实测时是
        `Cannot force an update in save() with no primary key.`），版本号一动就可能改字；
        把句子写死等于给下一次 Django 升级埋一条假红（评审 2026-10-30 的 minor）。
        类型与「没主键不许强制 UPDATE」这个语义才是判据。
        """
        user = _fresh_user(self.user.pk)
        UserSetting.objects.create(user=user, chart_dpi=200)
        poisoned = _poison_with_unsaved(user, chart_dpi=300)
        with self.assertRaises(IntegrityError) as dup:
            poisoned.save()                        # INSERT ⇒ 撞 accounts_user_setting.user_id
        self.assertIn('user_id', str(dup.exception),
                      f'UNIQUE 报错形状变了（表名/列名漂移），请重读这条判据：{dup.exception!r}')
        with self.assertRaises(ValueError) as forced:
            poisoned.save(update_fields=['chart_dpi'])
        self.assertIn('primary key', str(forced.exception),
                      f'强制 UPDATE 的守卫文案变了，请重读这条判据：{forced.exception!r}')

    def test_write_after_the_guard_is_a_plain_update(self):
        """判据 ③ 的正面：毒缓存被摘掉后，`user.settings.save()` 既撞不到 UNIQUE 也不抛。"""
        user = _fresh_user(self.user.pk)
        UserSetting.objects.create(user=user, chart_dpi=200)
        _poison_with_unsaved(user, chart_dpi=300)
        get_user_setting(user, create=True)
        user.settings.chart_dpi = 300          # D2 之后的写法：改缓存里那份，再 save
        user.settings.save()                   # 摘不掉毒缓存 ⇒ 这是 INSERT ⇒ IntegrityError（上一条钉着）
        self.assertEqual(UserSetting.objects.filter(user_id=user.pk).count(), 1)
        self.assertEqual(UserSetting.objects.get(user_id=user.pk).chart_dpi, 300)

    def test_write_with_update_fields_after_the_guard_is_the_valueerror_half(self):
        """判据 ③ 的另一半（本轮从上一条里**拆出来**的独立用例）：
        拆分前 `save()` 与 `save(update_fields=…)` 同处一条，摘掉毒缓存时第 ① 步就先撞
        `IntegrityError`，那条 `ValueError` 断言永远跑不到（`grep -c "Cannot force"` = 0）。
        这条只有 `update_fields=` 一次写 ⇒ 摘掉 `_state.adding` 判据 ⇒ 交出去的仍是
        `pk=None` 那份 ⇒ 当场抛 `ValueError: ... no primary key`，红在这里。
        """
        user = _fresh_user(self.user.pk)
        UserSetting.objects.create(user=user, chart_dpi=200)
        _poison_with_unsaved(user, chart_dpi=300)
        get_user_setting(user, create=True)    # 有判据：缓存换成库里那行（带 pk）
        user.settings.chart_dpi = 250
        user.settings.save(update_fields=['chart_dpi'])
        self.assertEqual(UserSetting.objects.get(user_id=user.pk).chart_dpi, 250)


class ProvisioningStatementShapeTests(TestCase):
    """判据 8：通路 1 的两条分支与 HEAD 的裸 `get_or_create` **逐计数**平价 —— 收敛不许在
    「建行」那条多花查询。

    HEAD 的 `render_export_filename` 就是裸 `UserSetting.objects.get_or_create(user=…)`：
    缺行 = 1 条 SELECT + 1 条 INSERT，有行 = 1 条 SELECT（参照系由
    `_head_provisioning_verbs()` 在同一轮里现场量，不写死）。收敛后必须同计数、同总条数
    （实例缓存命中时才 0 条，那是 D1 的收益不是回归）。
    """

    def setUp(self):
        self.user = User.objects.create_user(username='d1-shape', password='x-pass-12345678')
        # 参照系要用**另一个**没行的账号：同一个 user 上先跑谁谁就把行建了，另一条就变成
        # 「有行」分支，两条计数对不上（本轮踩过一次：4 != 1）。
        self.parity_user = User.objects.create_user(username='d1-shape-ref',
                                                    password='x-pass-12345678')

    def _verbs_for(self, user, **kwargs):
        return _captured_verbs(get_user_setting, user, **kwargs)

    def test_missing_row_costs_one_select_plus_one_insert(self):
        reference = _head_provisioning_verbs(_fresh_user(self.parity_user.pk))
        self.assertEqual(reference.count('INSERT'), 1, f'参照系本身得是「建行」那条分支：{reference}')
        verbs = self._verbs_for(_fresh_user(self.user.pk), create=True)
        self.assertEqual(verbs.count('SELECT'), 1,
                         f'建行路径多出来的 SELECT 来自先拿描述符探测有无行：{verbs}')
        self.assertEqual(verbs.count('INSERT'), 1, f'缺失即建应当正好 1 条 INSERT，实测 {verbs}')
        self.assertEqual(len(verbs), len(reference),
                         f'与 HEAD 的裸 get_or_create 条数不同形（helper {verbs} vs HEAD {reference}）')

    def test_existing_row_costs_exactly_one_select(self):
        UserSetting.objects.create(user=self.user, chart_dpi=300)
        verbs = self._verbs_for(_fresh_user(self.user.pk), create=True)
        self.assertEqual(verbs.count('SELECT'), 1, f'有行时该 1 条 SELECT，实测 {verbs}')
        self.assertEqual(verbs.count('INSERT'), 0, f'有行时不许写库，实测 {verbs}')
        verbs = self._verbs_for(_fresh_user(self.user.pk))
        self.assertEqual(verbs, ['SELECT'], f'只读有行时也该 1 条 SELECT，实测 {verbs}')

    def test_cache_hit_costs_no_statement_at_all(self):
        UserSetting.objects.create(user=self.user, chart_dpi=300)
        user = _fresh_user(self.user.pk)
        get_user_setting(user, create=True)
        self.assertEqual(self._verbs_for(user, create=True), [], '第二次同实例读取必须零查询')
        self.assertEqual(self._verbs_for(user), [])


class HeadBaselineProbeTests(TestCase):
    """判据 9：把「三轮 7 → 1」里那个 **7** 量出来，而不是写在注释里当「我记得」。

    口径（同一份 `user` 实例、同一个库、三轮，每轮把收敛前那三段读法各跑一次）：
    通路 1 `get_or_create` 每轮 1 条 SELECT（manager 从不碰实例反向缓存）= 3；
    通路 2 `filter().values_list().first()` 每轮 1 条 = 3；
    通路 3 `user.settings` 描述符只在第一轮 1 条，之后命中 `user._state.fields_cache` = 1；
    合计 7。收敛后同一条链是 1（承重判据在 `test_repeated_rounds_on_the_same_instance_still_cost_zero`）。
    """

    def setUp(self):
        self.user = User.objects.create_user(username='d1-baseline', password='x-pass-12345678')
        UserSetting.objects.create(user=self.user, chart_dpi=300, cpk_a_threshold=2.5)

    def test_three_rounds_of_the_head_shapes_cost_seven_selects(self):
        user = _fresh_user(self.user.pk)
        captured = CaptureQueriesContext(connection)
        with captured:
            for _ in range(3):
                _head_round(user)
        self.assertEqual(_verbs(captured), ['SELECT'] * 7,
                         f'HEAD 基线探针应当正好 7 条裸 SELECT，实测 {_verbs(captured)}'
                         f'（注释里的 7 就此作废，请改这里的数字）')

    def test_the_same_three_rounds_through_the_helper_cost_one(self):
        user = _fresh_user(self.user.pk)
        captured = CaptureQueriesContext(connection)
        with captured:
            for _ in range(3):
                get_user_setting(user, create=True)
                get_user_setting(user)
                get_user_setting(user)
        self.assertEqual(_verbs(captured), ['SELECT'], '与上一条探针同口径：7 → 1')

    def test_head_path1_provisioning_statement_shape_is_the_parity_reference(self):
        """HEAD 的通路 1 就是裸 `UserSetting.objects.get_or_create(user=…)` —— 把它的**计数**量出来。

        这两条实测就是 `ProvisioningStatementShapeTests` 的参照系：缺行 1 条 SELECT +
        1 条 INSERT，有行 1 条 SELECT（事务管线的那些 SAVEPOINT/RELEASE 只进总条数，
        不当判据，见 `_verbs()` 的口径）。收敛后的 helper 与之同计数同总条数
        ⇒ 「迁移通路 1 没让它变贵」是可复现的一句话，不是一个口径不明的百分比。
        """
        plain = User.objects.create_user(username='d1-head-ref', password='x-pass-12345678')
        verbs = _head_provisioning_verbs(plain)
        self.assertEqual(verbs.count('SELECT'), 1, f'HEAD 缺行参照系该 1 条 SELECT，实测 {verbs}')
        self.assertEqual(verbs.count('INSERT'), 1, f'HEAD 缺行参照系该 1 条 INSERT，实测 {verbs}')
        existing = _fresh_user(plain.pk)          # 取实例的那条 SELECT 必须在上下文之外
        verbs = _head_provisioning_verbs(existing)
        self.assertEqual(verbs.count('SELECT'), 1, f'HEAD 有行参照系该 1 条 SELECT，实测 {verbs}')
        self.assertEqual(verbs.count('INSERT'), 0, f'HEAD 有行参照系不该写库，实测 {verbs}')


class NoneUserTests(TestCase):
    """判据 5：`user=None` 必须继续可用（`apps/export/tests_chart_dpi.py` 的 None 用例钉着它）。"""

    def test_get_user_setting_returns_none_for_none_user(self):
        self.assertIsNone(get_user_setting(None))
        self.assertIsNone(get_user_setting(None, create=True),
                          '建行开关也不许把 None 变成异常：通路 2 之外也要吃得下匿名/空用户')

    def test_get_export_dpi_none_costs_zero_queries(self):
        with self.assertNumQueries(0):
            self.assertEqual(get_export_dpi(None), EXPORT_DPI_DEFAULT)

    def test_get_export_dpi_still_swallows_a_broken_settings_read(self):
        """通路 2 的「绝不抛」是它自己的契约，helper 不许把它抬成会抛。
        同时它**不许响**成私有面告警：那条 WARNING 只归「我们自己的管路断了」，
        把库故障也一起响等于把信号稀释成噪音（`user_prefs` 的分支口径）。
        """
        with self.assertNumQueries(0), \
                self.assertNoLogs('apps.export.user_prefs', level='WARNING'):
            self.assertEqual(get_export_dpi(_SettingsReadRaises()), EXPORT_DPI_DEFAULT)
        with self.assertRaises(RuntimeError):
            get_user_setting(_SettingsReadRaises())


class WorkerIsolationProbeTests(SimpleTestCase):
    """判据 6：`apps/common/user_settings.py` 链路仍然能在没有 Django 的子进程里 import。

    按**运行时**判据（形状取自 `test/backend/test_norm_ppf_memo.py::WorkerDjangoFreeImportTests`
    与 `test/backend/test_exit_pool_shutdown.py::RunnerChainProbeTests`）：源码文本 grep 抓不到
    函数内延迟 import，也无法证明「没有 Django」；这里清空 `DJANGO_SETTINGS_MODULE` 起子进程，
    再看 `sys.modules`。`apps/jobs/tests_jobs.py::WorkerModuleIsolationTests` 是同一条约束的
    既有钉子，它 846 行冻住不能加，故判据落在这里。
    """

    def _probe(self, code):
        env = dict(os.environ)
        env.pop('DJANGO_SETTINGS_MODULE', None)
        self.assertTrue((_ROOT / 'manage.py').is_file(),
                        f'{_ROOT} 不是仓根 —— cwd 错了这条会假绿')
        return subprocess.run([sys.executable, '-X', 'utf8', '-c', code],
                              cwd=str(_ROOT), capture_output=True, text=True,
                              encoding='utf-8', errors='replace', env=env, timeout=180)

    def test_user_settings_chain_imports_with_zero_django_modules(self):
        code = (
            'import sys;'
            'import apps.common.user_settings as m;'
            'assert m.get_cpk_thresholds(None).cpk_a == 1.67;'
            'print([n for n in sys.modules if n == "django" or n.startswith("django.")],'
            ' "accounts.services" if "apps.accounts.services" in sys.modules else "-accounts.services")'
        )
        proc = self._probe(code)
        self.assertEqual(proc.returncode, 0,
                         f'apps/common/user_settings 链路带上 Django 依赖，worker 起不来：\n'
                         f'{proc.stderr[-1500:]}')
        self.assertEqual(proc.stdout.strip(), '[] -accounts.services',
                         '无 Django 子进程里 sys.modules 必须一个 django 都没有（上面那条钉子的形状）')

    def test_probe_itself_can_see_django(self):
        """上一条的对照组：探针确实能抓到 Django 依赖，否则「[]」可能只是探针没跑起来。"""
        code = ('import sys; import django.conf;'
                'print([n for n in sys.modules if n == "django" or n.startswith("django.")])')
        proc = self._probe(code)
        self.assertEqual(proc.returncode, 0, proc.stderr[-1500:])
        self.assertNotEqual(proc.stdout.strip(), '[]',
                            '探针看不见 django 模块 ⇒ 上一条判据已失效')
