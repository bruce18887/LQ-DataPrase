"""D1 · `apps/accounts/services.py` 伸手进的 Django 私有面：运行时钉子 + 「不许静默读错值」。

从 `test/backend/test_user_setting_reads.py` 拆出来（600 行绊线：那个模块装着三通路收敛的
全部判据，本批加到 681 行；拆分的唯一原因是行数闸，判据本身一条没少）。
读侧收敛的其余判据（`7 → 1`、只读默认、`create=True`、毒缓存守卫）仍在那个字里行多的
`test_user_setting_reads.py` 里，本模块只钉「私有面」这一件事。

为什么这件事值得单独一条运行时判据：helper 不 import 任何 Django 公开 API 就能读到的东西
其实读不到 —— 它吃的是 `django.db.models.fields.mixins.FieldCacheMixin` 的四个成员
（`cache_name` / `get_cached_value` / `set_cached_value` / `delete_cached_value`）。
哪天改名或改签名，`_cached_setting()` 抛 `AttributeError`，而通路 2 历史上把它和
「用户没有 settings 行」一起咽掉 ⇒ 用户明明存了 300 却静默拿到默认 100
（D1 评审 2026-10-30 实测的 `100 != 300`）。⇒ 两支分工：

* `SettingsCacheApiPinTests` —— 私有面**在场且可用**（round-trip 真跑一遍，不是 `hasattr`），
  带一个「没有这套面的对象」对照组，免得探针自己空转到恒绿。
  形状先例：`test/backend/test_shutdown_closes_pools.py::ManagerThreadAttributePinTests`。
* `SilentMisreadAlarmTests` —— 私有面断了必须**出声**（通路 2 留 WARNING，通路 1 直接抛），
  咽回默认值这件事只许发生在「外部故障」那半边。

今天这两台解释器都安全（本机 2026-10-30 实测，不是推断）：`.venv` = Python 3.13.12 /
Django 6.0.9 与系统 `D:\\Program Files\\Python\\Python313` = Django 6.0.5 的
`db/models/fields/mixins.py`、`db/models/fields/related_descriptors.py` **逐字节相同**
（sha256 前缀 `7b028f3e` / `42407d23`；复核：对两个路径各跑一次
`python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()[:8], sys.argv[1])"`
—— 证据在磁盘上的 Django 包里，不依赖任何 gitignored 日志）。
「逐字节相同」只说这两个版本，不许外推成「Django 不会改」—— 那正是这两支判据存在的理由。

跑法：`python -X utf8 manage.py test test.backend.test_settings_cache_api_pin`
"""

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from apps.accounts import services
from apps.accounts.models import UserSetting
from apps.common.export_naming import render_export_filename
from apps.export.charts import EXPORT_DPI_DEFAULT
from apps.export.user_prefs import get_export_dpi

User = get_user_model()

CTX = {'filename': 'gage_m_S1'}

# 与 test_user_setting_reads.py 同名的两件小道具在这里**重新声明**而不是跨测试模块 import：
# 测试模块之间互相 import 会让「跑哪个文件」依赖收集顺序，本仓的先例是道具进 `*_fixtures.py`，
# 但为三行代码再起一个模块不值得。


def _fresh_user(pk):
    """复现一条真实请求的起点：认证中间件每次都新建 User 实例，实例缓存是空的。"""
    return User.objects.get(pk=pk)


def _cache_api_roundtrip(rel):
    """把 `apps/accounts/services.py` 真正消费的四个私有面各用一次（零 SQL）。

    `set` → `cache_name` 槽位核对 → `get` → `delete` → `get`。任一名字改了、签名变了、
    或被摘掉，这里就抛 `AttributeError`/`TypeError`；**不**返回「缺失清单」，因为
    `hasattr` 一类的形状挡不住「名字还在、行为变了」。
    探针喂的是未落库的 `User()` —— 只为拿一个空的 `fields_cache`，不碰库。
    """
    holder = User(username='d1-pin-probe')
    marker = object()
    rel.set_cached_value(holder, marker)
    if holder._state.fields_cache.get(rel.cache_name) is not marker:
        raise AssertionError('set_cached_value 写的槽位与 cache_name 不是同一个 ⇒ 摘缓存会摘错键')
    if rel.get_cached_value(holder, None) is not marker:
        raise AssertionError('get_cached_value 读不回 set_cached_value 刚写进去的值')
    rel.delete_cached_value(holder)
    if rel.get_cached_value(holder, None) is not None:
        raise AssertionError('delete_cached_value 没把缓存摘掉')


class _DescriptorWithoutCacheApi:
    """对照组成员：一个压根没有 `FieldCacheMixin` 那套私有面的描述符替身。"""


def _shadow_cache_api(rel, name):
    """把描述符实例上的某个私有方法「改名」掉（调用即 `AttributeError`）。

    装的是**实例阴影**（继承来的实现原封不动），配套 `_unshadow_cache_api` 摘掉阴影即还原。
    这是「Django 哪天把 `get_cached_value` 换名」在不改 site-packages 的前提下唯一能在测试里
    复现的形状。
    """
    def _renamed(*args, **kwargs):
        raise AttributeError(f"'{name}' is not available (模拟 Django 改名)")

    setattr(rel, name, _renamed)


def _unshadow_cache_api(rel, name):
    if name in vars(rel):
        delattr(rel, name)


class SettingsCacheApiPinTests(SimpleTestCase):
    """私有面必须在**运行时**可用（模块头列的那四个名字就是 `services` 消费面的全集）。"""

    def test_the_private_cache_api_round_trips_on_the_real_descriptor(self):
        """变异（改名 / 摘掉任一个面，或改签名）⇒ 这里直接抛 `AttributeError`/`TypeError`。

        红证据：本条在干净树上是**绿**的（钉子类判据本来就该如此），它的红来自变异 ——
        「真·改名」的复现办法写在用例里，不靠日志：起一个 Django 进程后
        `del django.db.models.fields.mixins.FieldCacheMixin.get_cached_value`
        （只在内存里删，不动 site-packages），再跑本模块 ⇒ 本条 ERROR：
        `AttributeError: 'OneToOneRel' object has no attribute 'get_cached_value'.`
        下面 `SilentMisreadAlarmTests` 用的实例阴影是同一次变异的免改库写法，常驻用例。
        """
        _cache_api_roundtrip(services._SETTINGS_REL)

    def test_control_arm_a_descriptor_without_the_api_fails_the_probe(self):
        """对照组（哨兵类判据必须带的那条）：同一个探针喂没有私有面的对象**必须抛** ——
        否则上面那条的「没抛」可能只是探针压根什么都没做。
        """
        with self.assertRaises(AttributeError):
            _cache_api_roundtrip(_DescriptorWithoutCacheApi())


class SilentMisreadAlarmTests(TestCase):
    """私有面断了必须**出声**：通路 2 咽回默认值时留一条点名机制的 WARNING。

    红证据（TDD）：本类第一条在 `apps/export/user_prefs.py` 还是整块 `except Exception` 时跑红
    （`AssertionError: no logs of level WARNING or higher triggered on apps.export.user_prefs`，
    值仍是 100 —— 正是「静默读错用户设置」的形状），把 `AttributeError`/`TypeError` 拆成
    单独分支并 `logger.warning` 后转绿。
    """

    def setUp(self):
        self.user = User.objects.create_user(username='d1-alarm', password='x-pass-12345678')
        UserSetting.objects.create(user=self.user, chart_dpi=300)

    def _rename(self, name):
        rel = services._SETTINGS_REL
        _shadow_cache_api(rel, name)
        self.addCleanup(_unshadow_cache_api, rel, name)

    def test_a_renamed_cache_api_warns_instead_of_reading_the_default_silently(self):
        user = _fresh_user(self.user.pk)
        self._rename('get_cached_value')
        with self.assertLogs('apps.export.user_prefs', level='WARNING') as captured:
            # 「绝不抛」仍然成立（这条不是让通路 2 变成 500），但必须有人知道机制断了
            self.assertEqual(get_export_dpi(user), EXPORT_DPI_DEFAULT)
        self.assertTrue(any('get_cached_value' in line for line in captured.output),
                        f'私有面改名却一声不响 ⇒ 静默读错用户设置：{captured.output}')

    def test_the_provisioning_path_raises_rather_than_skipping_the_row(self):
        """通路 1（`create=True`）不吞私有面故障：直接抛 ⇒ 视图 500，
        不会「导出成功但用户的模板没读到」。

        这条写下来就是绿的（`get_user_setting` 从不吞异常，吞的是通路 2 自己），
        它钉的是「咽异常只许发生在 `user_prefs` 那一侧，helper 保持会抛」这条边界 ——
        哪天有人在 helper 里也加一层 `except Exception`，这里先红。
        """
        user = _fresh_user(self.user.pk)
        self._rename('get_cached_value')
        with self.assertRaises(AttributeError):
            render_export_filename(user, 'to_excel', 'xlsx', CTX)
