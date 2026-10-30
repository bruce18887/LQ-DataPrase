"""导出侧读取用户系统设置（读库口径与 apps/common/export_naming.py 一致：
都走 `apps/accounts/services.get_user_setting` 这个单一入口，同一个 user 实例在一个请求里
只发 1 条 SELECT，后续通路命中 Django 挂在实例上的反向缓存）。

两条刻意不一样的地方：
* 本模块**只读**（不传 `create=True`）—— 通路 2 今天零 INSERT，D1 收敛后也必须零 INSERT；
  「缺失即建」只归导出文件名那条通路，理由写在 apps/accounts/services.py 文首。
* 「绝不抛」是本通路自己的契约（下面那两个 except 咽掉外部故障），helper 抛出来的东西
  在这里必须被咽回默认值，不许抬成 500。**但**「咽掉」不等于「一声不响」：
  `AttributeError`/`TypeError` 只会来自我们自己的管路（见下面 `_PLUMBING_ERRORS` 的注释），
  把它们和「用户没有设置行」混在一起咽 = 静默读错用户设置，所以那两支单独出 WARNING。

本模块**可以**依赖 Django；`apps/export/charts.py` 不行（它被 ProcessPoolExecutor
子进程 import，见 chart_workers.py 顶部约束），所以「读库 + 钳位」放这里，
钳位后的纯标量再作为参数穿进渲染函数。
"""

import logging

from apps.accounts.services import get_user_setting

from .charts import EXPORT_DPI_DEFAULT, clamp_export_dpi

logger = logging.getLogger(__name__)

# 「绝不抛」要咽的是**外部**故障（库连不上、传进来的是个替身对象、事务被中断）；
# 这两类异常则只可能来自我们自己的管路 —— 具体就是 `apps/accounts/services.py` 伸手进的
# Django 私有面（`FieldCacheMixin` 的 `cache_name` / `get_cached_value` / `set_cached_value` /
# `delete_cached_value`）。把它们一起咽掉的后果不是「报错」而是**读错值**：用户存了 300
# 却静默拿到默认 100（D1 评审 2026-10-30 把 `get_cached_value` 改名实测到的 `100 != 300`）。
# ⇒ 单列一支，仍然回退默认值（「绝不抛」是通路 2 的契约，不改），但必须点名机制留一条 WARNING。
# 钉子：test/backend/test_settings_cache_api_pin.py::SilentMisreadAlarmTests；
# 那套私有面本身另有运行时钉子 ::SettingsCacheApiPinTests（含对照组）。
_PLUMBING_ERRORS = (AttributeError, TypeError)


def get_export_dpi(user) -> int:
    """用户设置的导出图表 DPI，钳到设置页合法区间。

    user 为空 / 无 settings 行 / 值不可解析 → 回退 EXPORT_DPI_DEFAULT，绝不抛。
    管路自身断了（`_PLUMBING_ERRORS`）同样回退，但会在 WARNING 里点名是哪条机制。
    """
    try:
        setting = get_user_setting(user)
    except _PLUMBING_ERRORS as exc:
        logger.warning(
            '读取用户 chart_dpi 失败：apps/accounts/services.py 依赖的 Django 私有缓存面'
            '（FieldCacheMixin 的 cache_name / get_cached_value / set_cached_value / '
            'delete_cached_value）疑似改名或改了签名，本次按默认 DPI 出图：%r', exc)
        setting = None
    except Exception:
        setting = None
    return clamp_export_dpi(getattr(setting, 'chart_dpi', None))
