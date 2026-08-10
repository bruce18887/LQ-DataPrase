"""
Helper utilities and constants for statistical analysis.

Provides column lookup functions, data accessors, and basic numeric helpers
used across the statistics sub-modules.
"""
from typing import Optional, Dict, List, Tuple
import numpy as np
import pandas as pd

from apps.common.constants import NON_NUMERIC_KEYWORDS

BIN_COLUMN_MAPPING = {
    'CTA8290D': 'SW_Bin',
    'CTA8280F': 'SW_Bin',
    'ETS88': 'Bin',
    'STS8200': 'SOFT_BIN',
}


def get_bin_column_name(format_type: str) -> str:
    return BIN_COLUMN_MAPPING.get(format_type, 'SW_Bin')


def find_column_by_pattern(df: pd.DataFrame, patterns: List[str]) -> Optional[str]:
    for col in df.columns:
        col_lower = col.lower()
        for pattern in patterns:
            if pattern in col_lower:
                return col
    return None


def get_site_column(df: pd.DataFrame) -> Optional[str]:
    return find_column_by_pattern(df, ['site'])


def get_serial_column(df: pd.DataFrame) -> Optional[str]:
    return find_column_by_pattern(df, ['serial'])


def get_coord_columns(df: pd.DataFrame) -> Tuple[Optional[str], Optional[str]]:
    x_col = None
    y_col = None
    for col in df.columns:
        col_lower = col.lower()
        if 'x' in col_lower and 'coord' in col_lower:
            x_col = col
        elif 'y' in col_lower and 'coord' in col_lower:
            y_col = col
    return x_col, y_col


def get_bin_column(df: pd.DataFrame, metadata: Dict) -> Optional[str]:
    """Return the Bin column name based on metadata format type, if it exists in df."""
    format_type = metadata.get('format', '')
    target_col = get_bin_column_name(format_type)
    if target_col and target_col in df.columns:
        return target_col
    return None


def get_1d(series_or_df):
    if isinstance(series_or_df, pd.DataFrame):
        return series_or_df.iloc[:, 0]
    return series_or_df


def get_1d_from(df: pd.DataFrame, col: str) -> pd.Series:
    s = df[col]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return s


def _dense_x_grid(x_min: float, x_max: float, n_points: int,
                  center: float, spread: float) -> np.ndarray:
    """等距网格；分布宽度远小于网格间距时在 ``[center±6*spread]`` 加密。

    窄分布（σ 或数据范围 << bin 宽度）下，等距采样点会全部落在数据密集
    区之外，曲线取整后整条消失（此前前端用 ``std < binGap`` 补 ±6σ 点，
    #17 后端化后此逻辑下沉到这里，屏幕/导出统一）。返回排序去重网格。
    """
    x = np.linspace(x_min, x_max, n_points)
    step = (x_max - x_min) / (n_points - 1)
    if spread < step:
        extra = np.linspace(center - 6 * spread, center + 6 * spread, 60)
        x = np.union1d(x, extra)
    return x


def normal_pdf_curve(mean: float, std: float, x_min: float, x_max: float,
                     n_points: int = 200) -> Optional[List[List[float]]]:
    """正态 PDF 曲线采样，与 ``kde_curve`` 同格式 ``[[x, y], ...]``。

    公式单一来源：前端 ECharts 与导出 matplotlib 都消费本函数的结果
    （此前三处各自实现高斯公式，改一处漏一处必然分叉）。
    ``std <= 0``（退化数据）返回 None，调用方静默跳过曲线。
    """
    if std <= 0:
        return None
    x = _dense_x_grid(x_min, x_max, n_points, mean, std)
    scale = 1.0 / (std * np.sqrt(2.0 * np.pi))
    y = scale * np.exp(-0.5 * ((x - mean) / std) ** 2)
    return [[round(float(xi), 6), round(float(yi), 6)] for xi, yi in zip(x, y)]


def filter_finite(series: pd.Series) -> pd.Series:
    """移除 NaN 与 ±inf（向量化）。

    等价于 ``pd.to_numeric(errors='coerce').dropna()`` 后再滤 inf，一步完成；
    替代历史 ``series.apply(lambda x: abs(x) < float('inf'))`` 逐行模式
    （依赖 NaN 比较语义且慢）。返回 Series（索引为原索引子集）。
    """
    clean = pd.to_numeric(series, errors='coerce')
    return clean[np.isfinite(clean.values)]


def site_sort_key(site_name):
    """站点名排序：纯数字站点排前面（按数值），非数字按字符串。"""
    try:
        return (0, float(site_name), '')
    except (ValueError, TypeError):
        return (1, 0, str(site_name))


def ensure_numeric(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.to_numeric(get_1d_from(df, col), errors='coerce')


def safe_gap(min_val: float, max_val: float) -> float:
    gap = (max_val - min_val) / 20
    return max(gap, 1e-9)
