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

「缺失即建」有**两个**公开入口，选哪个看你要不要 `created` 和要不要往 INSERT 里带值：
`get_user_setting(user, create=True)` 只要那一行（值用默认），`provision_user_setting(user,
defaults)` 给「建行时把这几个值一起写进去」的通路（D4 的 SFTP 记录）。两个入口都先只看
`_cached_setting`，所以同实例第二次调用是零 SQL；建行入口还把行钉回 `user` 的反向缓存 ——
那份缓存的负缓存形状（`created=False` 的 `.get()` 分支不挂缓存）只在这个入口里处理，
别在调用方各写一遍。
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
        # 建行整条交给 `provision_user_setting`，而它自己先看一次 `_cached_setting`
        # （含 `_state.adding` 守卫）⇒ 缺行分支只付 `get_or_create` 那 1 条 SELECT，
        # 与 HEAD 的裸 `get_or_create` 同数，不额外拿描述符去探「有没有行」。
        # 判据 `test/backend/test_user_setting_reads.py::ProvisioningStatementShapeTests`。
        setting, _created = provision_user_setting(user)
        return setting
    return getattr(user, 'settings', None)


def provision_user_setting(user, defaults=None):
    """「缺失即建」的**公开**入口：缺行就建行并带上 `defaults`，返回 `(setting, created)`。

    为什么要一个公开 helper，而不是让调用方自己写 `get_or_create`：两个返回分支的**缓存后果
    不一样**，而 `created` 的含义调用方必须知道。

    **先看实例缓存再看库**（`_cached_setting`，含 `_state.adding` 毒缓存守卫）：缓存里躺着
    真实行时整条入口零 SQL，并返回 `(那一行, False)` —— 此时 `defaults` **一律不生效**
    （既不进 INSERT 也不 UPDATE），要落值的调用方必须自己按 `created` 决定后续收敛。
    缓存没命中（没条目、负缓存、或毒缓存被摘掉）才发 `get_or_create` 那 1 条 SELECT，
    所以「缺行」这一支总共是 **1 条 SELECT + 1 条 INSERT**（实测：`get_or_create` 自己会
    SELECT 一次，描述符那次探测不再付第二次）。

    - `created=True`：这一条 INSERT 带上 `defaults`；`Model.__init__` 顺手把新实例挂上 `user`
      的反向缓存 —— 那是副作用不是承诺，这里按 `_prime_settings_cache` 的口径再钉一次，
      把它变成承诺。
    - `created=False`（行已在、或并发抢建）：走的是 manager 的 `.get()`，**既不应用 `defaults`、
      也不碰那份缓存** ⇒ 只返回不处理就等于把调用方这次的值静默丢掉。本函数保证缓存里换成了
      那行真实对象（覆盖描述符的「没有行」负缓存），**调用方拿到 `created=False` 必须自己把
      值收敛到那一行**，别 `return` 了事。
      判据：`test/backend/test_sftp_last_visit_writes.py::MissingRowRaceTests`。

    只读通路请用 `get_user_setting(user)`；只有契约是「缺失即建」的调用方才用这里。
    `user is None` 不在本入口的契约里（「给不存在用户建行」没有意义，会直接把 `None` 递给
    `get_or_create` 抛错）—— 那条判断归调用方，`get_user_setting(None)` 仍然返回 `None`。
    """
    setting = _cached_setting(user)
    if setting is not None:
        return setting, False
    setting, created = UserSetting.objects.get_or_create(user=user, defaults=defaults or {})
    _prime_settings_cache(user, setting)
    return setting, created


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
