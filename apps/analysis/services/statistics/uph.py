"""UPH (Units Per Hour) computation."""

from typing import Dict, Any

import pandas as pd

from .helpers import get_site_column, ensure_numeric


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
    site_col = get_site_column(df)
    site_series = None
    site_count = 1
    if site_col:
        site_series = pd.to_numeric(df[site_col], errors='coerce')
        valid_sites = site_series.dropna().astype(int)
        if len(valid_sites) > 0:
            site_count = max(1, int(valid_sites.nunique()))
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
        per_unit_seconds = raw

    # Keep only rows with a positive, finite test time aligned with a valid site.
    valid_mask = per_unit_seconds.notna() & (per_unit_seconds > 0)
    if site_series is not None:
        valid_mask = valid_mask & site_series.notna()
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
    if site_series is not None:
        site_for_valid = site_series[valid_mask].astype(int)
        for site_val in sorted(site_for_valid.unique()):
            site_times = per_unit_valid[site_for_valid == site_val]
            if len(site_times) == 0:
                continue
            site_avg = float(site_times.mean())
            site_uph = (3600.0 / site_avg) if site_avg > 0 else 0.0
            by_site.append({
                'site': str(site_val),
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
