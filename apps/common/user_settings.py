"""跨 app 共用的「用户系统设置」读取入口。

先例：`apps/common/export_naming.py` 同样在请求上下文里读 `request.user.settings`。
放在 common 是因为 CPK 阈值同时被 analysis（直方图/多批次/CPK 表）、dashboard（总览
与低 CPK 警报）、export（批量图表等级色）三条链路消费，任何一条都不该 owns 它。

读法用 `user.settings` 描述符 + 逐字段 `getattr` 容错：既兼容真实 User，也兼容
测试里只挂部分字段的 SimpleNamespace 替身（见 apps/analysis/tests_chart_config.py）。
"""
from typing import NamedTuple

from apps.accounts.models import UserSetting  # noqa: F401  (类型与 DoesNotExist 来源)


class CpkThresholds(NamedTuple):
    """CPK 分级阈值（A/B/C 三档，D = 低于 C）。字段名与 compute_cpk 的形参一致。"""
    cpk_a: float
    cpk_b: float
    cpk_c: float

    def as_kwargs(self) -> dict:
        """供 ``compute_cpk(..., **thresholds.as_kwargs())`` 展开。"""
        return {'cpk_a': self.cpk_a, 'cpk_b': self.cpk_b, 'cpk_c': self.cpk_c}


DEFAULT_CPK_THRESHOLDS = CpkThresholds(cpk_a=1.67, cpk_b=1.33, cpk_c=1.0)


def _field(settings_obj, name: str, fallback: float) -> float:
    try:
        return float(getattr(settings_obj, name, None))
    except (TypeError, ValueError):
        return fallback


def get_cpk_thresholds(user) -> CpkThresholds:
    """读取用户的三级 CPK 阈值。

    user 为空 / 无 settings 行 / 单字段缺失或不可解析 → 该字段回退默认值，绝不抛
    （沿用 apps/analysis/views/_helpers.py get_cpk_b_threshold 的容错口径）。
    """
    try:
        settings_obj = user.settings
    except Exception:
        return DEFAULT_CPK_THRESHOLDS
    return CpkThresholds(
        cpk_a=_field(settings_obj, 'cpk_a_threshold', DEFAULT_CPK_THRESHOLDS.cpk_a),
        cpk_b=_field(settings_obj, 'cpk_b_threshold', DEFAULT_CPK_THRESHOLDS.cpk_b),
        cpk_c=_field(settings_obj, 'cpk_c_threshold', DEFAULT_CPK_THRESHOLDS.cpk_c),
    )
