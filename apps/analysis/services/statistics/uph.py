"""UPH (Units Per Hour) computation."""

from typing import Dict, Any

import numpy as np
import pandas as pd

from .helpers import get_site_column, ensure_numeric, get_1d_from


# Per-unit test-time column candidates, in priority order, across supported formats.
TEST_TIME_COL_CANDIDATES = ['Test_Time', 'Test Time', 'T_TIME', 'TEST_TIME', 'TestTime']


def _detect_test_time_col(df: pd.DataFrame, preferred=None):
    """Return the name of the per-unit test-time column, or None.

    A preferred column (from the request) wins if present. Otherwise the first
    known per-unit candidate is used. We deliberately avoid the many per-test
    ``*_Time`` columns (e.g. ETS88 sub-test timings) and only match whole-unit
    test-time columns.
    """
    if preferred and preferred in df.columns:
        return preferred
    for cand in TEST_TIME_COL_CANDIDATES:
        if cand in df.columns:
            return cand
    return None


def _is_number(v) -> bool:
    """站点标签能否按数值处理（用于排序：数值站点排前、按大小）。"""
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _format_site_label(v) -> str:
    """站点标签展示：整数值的 float（1.0）渲染成 '1'，其余原样 str。

    这是向后兼容的关键：旧写法先 ``.astype(int)`` 再 ``str()``，拿到的是 '1'；
    改成不截断后可能拿到 1.0 → str 会变 '1.0'，直接改变前端展示与
    UphCard/UphDetail 的 e2e 文本断言，所以在这里显式把整数值格式回 '1'。
    """
    if _is_number(v):
        f = float(v)
        if f == int(f):
            return str(int(f))
    return str(v)


def compute_uph(df: pd.DataFrame, metadata: Dict, test_time_col=None,
                manual_test_time_sec=None) -> Dict[str, Any]:
    """Compute UPH (Units Per Hour) using the parallel-site throughput model.

    Throughput assumes ``site_count`` testers run concurrently, so wall-clock
    time ≈ (sum of per-unit test times) / site_count, and::

        UPH = total_tested / total_time_seconds * 3600
            = 3600 * site_count / avg_test_time_seconds

    Test time is read from a per-unit column (auto-detected per format) and
    normalized to seconds (metadata unit ``ms`` is divided by 1000). A manual
    per-unit time (seconds) overrides the column. Per-site UPH reflects a single
    site's throughput (3600 / that site's average test time).

    Returns the shape consumed by the frontend ``UphCard.vue``.
    """
    warnings = []
    empty = {
        'uph': 0.0, 'avg_test_time': 0.0, 'total_tested': 0,
        'total_time_seconds': 0.0, 'source': 'unavailable',
        'by_site': [], 'site_count': 0, 'warnings': warnings,
    }

    # ── Site count (parallel testers) ────────────────────────────────
    # site_series：数值化后的站点列（仅用于「该行有无站点」的掩码）
    # site_labels：分组/计数用的标签（整数站点保持 int 展示，非整数或非数值
    #   标签保留原值）——两者分开是因为旧写法用 .astype(int) 既做分组又做计数，
    #   会截断小数站点号并让字符串站点整列变 NaN。
    site_col = get_site_column(df)
    site_series = None
    site_labels = None
    site_count = 1
    if site_col:
        raw_sites = get_1d_from(df, site_col)
        site_series = pd.to_numeric(raw_sites, errors='coerce')
        if site_series.notna().any():
            numeric_sites = site_series.dropna().to_numpy()
            # .astype(int) 会截断小数站点号（1.5 → 1）把不同站点并成一个 →
            # site_count 低估、by_site 分组也错。只有确实全为整数值时才转 int
            #（保持既有 '1'/'2' 的展示口径），否则按原值区分并告警。
            if np.all(numeric_sites == np.floor(numeric_sites)):
                site_labels = site_series.astype('Int64')
            else:
                site_labels = site_series
                warnings.append('Site 列含非整数站点号，已按原值区分站点（不做整数截断）')
            site_count = max(1, int(site_labels.dropna().nunique()))
        else:
            # 站点标签是 'A'/'B' 这类字符串：to_numeric 全 NaN。旧代码此时
            # site_count **静默保持 1 且不告警**（line 64 的告警只在 site_col
            # 为 None 时触发）→ UPH = 3600 * site_count / avg_test_time 被高估
            # site_count 倍；而且下面 valid_mask & site_series.notna() 会把所有行
            # 滤掉 → 整个 UPH 变成「无有效测试时间数据」。改为回退到原始标签计数。
            site_labels = raw_sites
            site_count = max(1, int(raw_sites.dropna().nunique()))
            warnings.append(
                f'Site 列「{site_col}」不是数值，已按原始标签识别出 {site_count} 个站点')
    else:
        warnings.append('未找到 Site 列，按单站点计算')

    # ── Per-unit average test time (seconds) ─────────────────────────
    source = ''
    per_unit_seconds = None  # pd.Series aligned to df.index, seconds, >0

    if manual_test_time_sec is not None:
        try:
            manual_val = float(manual_test_time_sec)
        except (TypeError, ValueError):
            manual_val = 0.0
        if manual_val > 0:
            per_unit_seconds = pd.Series(manual_val, index=df.index, dtype='float64')
            source = f'manual ({manual_val:g}s)'
        else:
            warnings.append('手动测试时间无效，已忽略')

    if per_unit_seconds is None:
        col = _detect_test_time_col(df, test_time_col)
        if col is None:
            warnings.append('未找到测试时间列，无法计算 UPH')
            empty['warnings'] = warnings
            return empty
        raw = ensure_numeric(df, col)
        unit = str(metadata.get('units', {}).get(col, '')).strip().lower()
        if 'ms' in unit:
            raw = raw / 1000.0
            source = f'{col} (ms→s)'
        else:
            source = col
            # 单位缺失/无法识别时默认按**秒**计算。若实际是 ms，UPH 会差 1000 倍
            # ——旧代码对此完全静默，用户无从判断数字可不可信。
            if not unit:
                warnings.append(f'测试时间列「{col}」无单位信息，已按秒计算，请核对')
            elif 's' not in unit:
                warnings.append(f'测试时间列「{col}」单位「{unit}」无法识别，已按秒计算，请核对')
        per_unit_seconds = raw

    # Keep only rows with a positive, finite test time aligned with a valid site.
    # 用 site_labels（而非 site_series）判有效：字符串站点标签下 site_series 全 NaN，
    # 旧写法会把所有行滤掉 → UPH 直接不可用。
    valid_mask = per_unit_seconds.notna() & (per_unit_seconds > 0)
    if site_labels is not None:
        valid_mask = valid_mask & site_labels.notna()
    per_unit_valid = per_unit_seconds[valid_mask]

    total_tested = int(len(per_unit_valid))
    if total_tested == 0:
        warnings.append('无有效测试时间数据')
        empty['warnings'] = warnings
        empty['site_count'] = site_count
        empty['source'] = source or 'unavailable'
        return empty

    dropped = int(len(df) - total_tested)
    if dropped > 0:
        warnings.append(f'{dropped} 行缺少有效测试时间，已忽略')

    avg_test_time = float(per_unit_valid.mean())
    total_serial_seconds = float(per_unit_valid.sum())
    total_time_seconds = total_serial_seconds / site_count if site_count > 0 else total_serial_seconds
    uph = (total_tested / total_time_seconds * 3600.0) if total_time_seconds > 0 else 0.0

    # ── Per-site breakdown ───────────────────────────────────────────
    by_site = []
    if site_labels is not None:
        # 不再 .astype(int)：非整数/字符串站点号会被截断或抛异常，直接用标签值
        site_for_valid = site_labels[valid_mask]
        for site_val in sorted(site_for_valid.dropna().unique(), key=lambda v: (0, float(v)) if _is_number(v) else (1, str(v))):
            site_times = per_unit_valid[site_for_valid == site_val]
            if len(site_times) == 0:
                continue
            site_avg = float(site_times.mean())
            site_uph = (3600.0 / site_avg) if site_avg > 0 else 0.0
            by_site.append({
                'site': _format_site_label(site_val),
                'tested': int(len(site_times)),
                'uph': round(site_uph, 1),
            })

    return {
        'uph': round(uph, 1),
        'avg_test_time': round(avg_test_time, 3),
        'total_tested': total_tested,
        'total_time_seconds': round(total_time_seconds, 1),
        'source': source,
        'by_site': by_site,
        'site_count': site_count,
        'warnings': warnings,
    }
