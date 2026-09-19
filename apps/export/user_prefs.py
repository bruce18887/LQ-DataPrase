"""导出侧读取用户系统设置（读库范式与 apps/common/export_naming.py 的
render_export_filename 一致：走 manager 直读，不依赖 user.settings 描述符缓存）。

本模块**可以**依赖 Django；`apps/export/charts.py` 不行（它被 ProcessPoolExecutor
子进程 import，见 chart_workers.py 顶部约束），所以「读库 + 钳位」放这里，
钳位后的纯标量再作为参数穿进渲染函数。
"""

from apps.accounts.models import UserSetting

from .charts import EXPORT_DPI_DEFAULT, clamp_export_dpi


def get_export_dpi(user) -> int:
    """用户设置的导出图表 DPI，钳到设置页合法区间。

    user 为空 / 无 settings 行 / 值不可解析 → 回退 EXPORT_DPI_DEFAULT，绝不抛。
    """
    raw = None
    if user is not None:
        try:
            raw = UserSetting.objects.filter(user=user).values_list(
                'chart_dpi', flat=True).first()
        except Exception:
            raw = None
    return clamp_export_dpi(raw)
