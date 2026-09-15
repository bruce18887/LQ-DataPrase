"""Gage 工位（Site）筛选。

Gage Summary 的 8 个槽位分别对应工位编号（槽位 S1 → Site 1 … S8 → Site 8）。
用户为每个槽位分配文件后，只导出该文件中对应工位的数据，统计也仅基于该工位。

工位列名因格式而异（CTA `Site_No` / ETS88 `Site #` / STS8200 `SITE_NUM`），
统一走 analysis 的共享探测函数 `get_site_column`（首个含 'site' 的列）与
`site_sort_key`，与「查看数据」页的 site 过滤保持一致语义。
"""
from typing import List, Optional, Tuple

import pandas as pd

from apps.analysis.services.statistics.helpers import get_site_column, site_sort_key

_MISSING = ('', 'nan', 'NaN', 'None')


def normalize_site_value(value) -> str:
    """工位值归一化为可比较字符串：数字值去掉 `.0`，字符串仅去空白。"""
    if value is None:
        return ''
    try:
        if pd.isna(value):
            return ''
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        return value.strip()
    try:
        f = float(value)
        return str(int(f)) if f.is_integer() else str(value)
    except (TypeError, ValueError):
        return str(value).strip()


def available_sites(df: pd.DataFrame, site_col: str) -> List[str]:
    """文件中出现过的工位（归一化、去重、数字优先排序）。"""
    uniq = {normalize_site_value(v) for v in df[site_col]}
    return sorted((v for v in uniq if v not in _MISSING), key=site_sort_key)


def select_site(
    df: pd.DataFrame, site
) -> Tuple[Optional[pd.DataFrame], Optional[str], List[str]]:
    """把 df 过滤到单个工位。

    返回 ``(filtered_df, site_col, available)``：

    * ``site_col is None``  —— 文件不含工位列，``filtered_df`` 也为 None；
    * ``filtered_df`` 为空  —— 文件不含该工位的数据；
    * 否则 ``filtered_df`` 只含该工位行，``available`` 为该文件全部工位。
    """
    site_col = get_site_column(df)
    if site_col is None:
        return None, None, []
    available = available_sites(df, site_col)
    target = normalize_site_value(site)
    mask = df[site_col].map(normalize_site_value) == target
    return df[mask], site_col, available
