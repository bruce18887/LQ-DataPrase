"""用户设置读取的单一入口（波次 D1 · 三通路合一）。

为什么住在 `apps/accounts` 而不是 `apps/common`：本模块必须 import `apps.accounts.models`，
而 `apps/common/user_settings.py` **不许**这么做 —— 它被 `apps/export/export_batch_charts_xlsx`
→ `apps/jobs/runner.py` 那条链带着，要在没有 `django.setup()` 的 spawn 子进程里 import 得起来
（钉子：`apps/jobs/tests_jobs.py::WorkerModuleIsolationTests` 与
`test/backend/test_user_setting_reads.py::WorkerIsolationProbeTests`，后者是运行时子进程判据）。
`apps/accounts/serializers.py` 已经在模块层 import `apps.common.export_naming`，所以那边只能在
函数内 import 本模块（沿用 `render_export_filename` 原有的延迟 import 位置）。

**缺失即建不是默认行为**（选型 (b)，判据在 `test/backend/test_user_setting_reads.py`）：
`UserSetting` 行只在四处自动建行（API 建用户 `serializers.py`、`seed_users.py`、设置页
GET/PUT、SFTP 与作业提交侧的 `get_or_create`），**没有** post_save 信号，而
`standalone._bootstrap` 用 `User.objects.create_superuser` 建的首个管理员不建行 ——
「账号没有 settings 行」是打包桌面版首次启动的真实可达态。把只读通路（通路 2
`get_export_dpi`）接上一个会建行的 helper，等于给一条今天零 SQL 写、零 INSERT 的读路径加写，
方向与同波次的 D2（设置页 GET 不写库）相反 ⇒ helper 默认只读，唯一契约就是「缺失即建」的
调用方（通路 1 导出文件名渲染）显式传 `create=True`。
"""

from apps.accounts.models import UserSetting

# 反向 OneToOne 的实例缓存通道：`UserSetting.user` 的 related_name='settings' 决定键名，
# 这里按关系对象取 `cache_name`（写死字符串的话 Django 改口径就静默失效）。
# 本模块伸手进的私有面共四个：`cache_name`、`get_cached_value`、`set_cached_value`、
# `delete_cached_value`，全在 `django.db.models.fields.mixins.FieldCacheMixin` 上。
# 今天两台解释器都安全（本机 2026-10-30 实测，不是推断）：`.venv` = Python 3.13.12 /
# Django 6.0.9，系统 `D:\Program Files\Python\Python313` = Django 6.0.5，两处 site-packages 的
# `db/models/fields/mixins.py` 与 `db/models/fields/related_descriptors.py` **逐字节相同**
# （sha256 前缀 7b028f3e / 42407d23；复核：对那两个文件各跑一次
# `python -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()[:8], sys.argv[1])"`
# —— 证据在磁盘上的 Django 包里，不依赖任何 gitignored 日志）。
# 「逐字节相同」只说这两个版本，不许外推成「Django 不会改」：改名/改签名一旦落地，
# 判据是 test/backend/test_settings_cache_api_pin.py::SettingsCacheApiPinTests（运行时 round-trip
# + 对照组）与 ::SilentMisreadAlarmTests（通路 2 出声），`user_prefs.py` 的 `_PLUMBING_ERRORS`
# 是配套的「不许静默读错值」那半边。
_SETTINGS_REL = UserSetting._meta.get_field('user').remote_field


def get_user_setting(user, *, create: bool = False):
    """返回 `user` 的 `UserSetting`；同一个 user 实例在一个请求里只发 1 条 SELECT。

    - `user is None` → `None`（通路 2 的 `get_export_dpi(None)` 契约）。
    - 行缺失：默认返回 `None`（只读，不写库）；`create=True` 才按 `get_or_create` 的
      「缺失即建」语义建行并返回。
    - 无论读到的还是新建的，都塞回 `user._state.fields_cache`，同实例后续读取（含直接
      写 `user.settings` 的通路 3）零查询。
    - 缓存里躺着**没落库**的实例（`_state.adding`）时按「没有」处理，见 `_cached_setting`。
    """
    if user is None:
        return None
    setting = _cached_setting(user)
    if setting is not None:
        return setting
    if create:
        # 先只看缓存、不拿描述符去探测「有没有行」：描述符那次 SELECT 在缺行时是纯浪费
        # （通路 1 建行会付 2 条 SELECT，比它收敛前的 `get_or_create` 还多一条）。
        # 判据 `test/backend/test_user_setting_reads.py::ProvisioningStatementShapeTests`。
        setting, _created = UserSetting.objects.get_or_create(user=user)
        _prime_settings_cache(user, setting)
        return setting
    return getattr(user, 'settings', None)


def _cached_setting(user):
    """只读 `user` 实例上的反向缓存，**一条 SQL 都不发**；顺带摘掉「没落库」的毒缓存。

    三种落进这份缓存、但**不等于「有行」**的值：
    * 描述符对缺行的负缓存 —— 存的就是 `None`，返回 `None` 让调用方去查/去建；
    * 没落库的实例（`pk is None` / `_state.adding`）—— **今天就在树内可达**，不必等 D2：
      `Manager.create()` / `get_or_create()` 的建分支先由 `Model.__init__` 把新实例挂上
      `user` 的反向缓存、**之后**才发 INSERT，所以只要 INSERT 抛（并发下两个请求同时给同一
      user 建行 ⇒ 后到的撞 UNIQUE；或字段/触发器/磁盘故障），那份 `pk=None` 的对象就跟着
      `user` 实例活完整个请求。D2「设置页 GET 返回未落库的默认实例」只是把同一个形状从异常
      路径搬到正常路径。放着不管的代价是三件事：`create=True` 的建行被静默短路（DB 里 0 行，
      设置永远存不下来）、通路 2/3 把这份对象的默认字段当真值、调用方随后
      `user.settings.<field> = …; user.settings.save()` 在真实行已存在时撞
      `accounts_user_setting.user_id` 的 UNIQUE 约束（`IntegrityError`），同一次写带
      `update_fields=` 时是「没有 pk 不许强制 UPDATE」（`ValueError`）。两句都**不是**从日志里
      抄的：`test/backend/test_user_setting_reads.py::UnsavedCacheGuardTests`
      里 `test_unsaved_cache_writes_raise_the_two_claimed_errors` 直接把这个形状跑成断言
      （只断异常类型 + 稳定子串，Django 改文案不该假红）。这里当作「没有」，
      并用描述符自己的 `delete_cached_value()` 摘掉缓存，让下一次读取回到 DB 的真实状态。
      判据：`UnsavedCacheGuardTests`（可达性探针 + 上面两条错误形状 + 守卫本身的行为）。
      ⇒ 给 D2 的口径：**未落库的实例留在你自己的局部变量里**，别挂上 `user.settings`。
    * 鸭子类型的替身 user（测试里只挂 `settings` 字段、没有 `_state`）—— 视作未缓存，
      读侧行为整个交给描述符，`get_export_dpi` 的「绝不抛」契约就是靠这条路。
    """
    if getattr(user, '_state', None) is None:
        return None
    cached = _SETTINGS_REL.get_cached_value(user, None)
    if cached is None:
        return None
    if cached._state.adding:
        _SETTINGS_REL.delete_cached_value(user)
        return None
    return cached


def _prime_settings_cache(user, setting) -> None:
    """把行钉在 user 实例的反向缓存上 —— 描述符对「没有这一行」也做负缓存，必须能覆盖它。

    `get_or_create` 命中已有行时（并发：本请求先读到「没有」，别的请求随后建行）走的是
    manager `.get()`，不会碰 `user` 的缓存；不覆盖就会让整个请求一直吃那份陈旧负缓存，
    通路 2/3 静默回退默认值。Django 在 `create()` 分支上顺手写这份缓存是 `Model.__init__`
    的副作用，不是承诺 ⇒ 这里自己钉一次。
    """
    if _SETTINGS_REL.get_cached_value(user, None) is not setting:
        _SETTINGS_REL.set_cached_value(user, setting)
