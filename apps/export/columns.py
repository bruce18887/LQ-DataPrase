"""导出侧「可分析数值列」的唯一判定口径。

缺陷背景（此前散落在 views / export_xlsx_optimized / excel_builders 三处）::

    numeric_cols = [c for c in df.columns if df[c].dtype in ('int64', 'float64')]

* **漏列**：``int32`` / ``float32`` / ``int16`` / ``UInt8`` 等窄 dtype 的真实
  测量列被整列跳过（统计区空白、默认参数列表里没有它）。
* **pandas 3.0 语义变化**：字符串列现在是 ``str`` dtype，``dtype == object``
  恒为 False，任何依赖 object 判定字符串列的分支都已失效。
* **bool**：``pd.api.types.is_numeric_dtype`` 把 bool 当数值，但 bool 列
  （真实数据里的 ``Dut_Pass``）是 Pass/Fail 标记，不是测量值——对它算
  mean/σ/CPK 没有物理意义，必须显式排除。
"""

from typing import Iterable, List, Optional

import pandas as pd


def _as_series(df: pd.DataFrame, col) -> Optional[pd.Series]:
    """取单列；重复列名时 ``df[col]`` 是 DataFrame，退回首列。"""
    try:
        block = df[col]
    except (KeyError, TypeError):
        return None
    if isinstance(block, pd.DataFrame):
        block = block.iloc[:, 0] if block.shape[1] else None
    return block if isinstance(block, pd.Series) else None


def is_measurable_numeric(series: pd.Series) -> bool:
    """是否是「可分析的测量值」列：数值 dtype 且非 bool。"""
    if series is None:
        return False
    try:
        return bool(pd.api.types.is_numeric_dtype(series)
                    and not pd.api.types.is_bool_dtype(series))
    except TypeError:
        return False


def measurable_numeric_columns(df: pd.DataFrame,
                               exclude: Optional[Iterable[str]] = None) -> List[str]:
    """按 DataFrame 原始列序返回可分析的测量列名。

    ``exclude`` 用于剔除记录级系统列（``SW_Bin`` / ``Serial_No`` 等）——它们
    虽然是数值 dtype，但参与统计没有意义（见 ``SYSTEM_COLUMNS``）。
    """
    blocked = set(exclude or ())
    result = []
    for col in df.columns:
        if col in blocked:
            continue
        if is_measurable_numeric(_as_series(df, col)):
            result.append(col)
    return result
