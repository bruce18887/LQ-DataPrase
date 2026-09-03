# DEAD CODE — not wired into any view; the live path is
# gage_legacy_builder.build_gage_summary_excel (re-exported via
# excelize_layout). views.py used to import compute_rr_statistics but never
# called it. Kept only as a reference implementation — do NOT bug-fix here
# expecting it to change the exported report; fix gage_legacy_builder instead.
"""R&R (Repeatability & Reproducibility) analysis service for Gage R&R reports."""

import numpy as np
from apps.analysis.services.statistics import ensure_numeric

# Column indices for summary sheet (1-based)
COL_FILE_NAME = 1
COL_TESTER_ID = 2
COL_TEST_NAME = 3
COL_TEST_NUM = 4
COL_LOW_LIMIT = 5
COL_HIGH_LIMIT = 6
COL_UNIT = 7
COL_MEAN = 8
COL_STD = 9
COL_MIN = 10
COL_MAX = 11
COL_CP = 12
COL_CPK = 13
COL_G_MEAN = 15
COL_G_STD = 16
COL_G_6STD = 17
COL_G_MIN_CPK = 18
COL_G_MAX_CPK = 19
COL_TOTAL_CP = 20
COL_TOTAL_CPK = 21
COL_REPEAT = 22
COL_REPROD = 23
COL_RR = 24
COL_RR_PCT = 25
COL_FAIL = 26
COL_COMMENTS = 27
SUMMARY_COLS = 27


def _calc_d2(n):
    """d2* lookup for R&R calculations."""
    d2_map = {1: 1.0, 2: 1.41421, 3: 1.91155, 4: 2.23887, 5: 2.48124,
              6: 2.67253, 7: 2.82981, 8: 2.96288, 9: 3.07794, 10: 3.17905,
              11: 3.26909, 12: 3.35016, 13: 3.42378, 14: 3.49116, 15: 3.55333,
              16: 3.61071, 17: 3.66422, 18: 3.71424, 19: 3.76118}
    return d2_map.get(n, 3.80537)


def _safe_float(val, default=0.0):
    if isinstance(val, (int, float)):
        return val
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _limit_or_none(val):
    """Parse a spec limit into float, or None when missing/non-numeric.

    Never falls back to a magic 0/4 — a legitimate limit of 0 or 4 must be
    distinguishable from an absent one (defect #3).
    """
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def compute_file_statistics(df, test_name, metadata) -> dict:
    """Compute per-file statistics for a test item. Returns {mean, std, min, max, cp, cpk}."""
    data = ensure_numeric(df, test_name).dropna()
    if len(data) == 0:
        return {'has_data': False, 'mean': 0, 'std': 0, 'min': 0, 'max': 0, 'cp': 0, 'cpk': 0}
    arr = data.values.astype(np.float64)
    mean_v = float(arr.mean())
    std_v = float(arr.std(ddof=0)) if len(arr) > 1 else 0
    min_v = float(arr.min())
    max_v = float(arr.max())
    ll = _limit_or_none(metadata.get('mins', {}).get(test_name))
    hl = _limit_or_none(metadata.get('maxs', {}).get(test_name))
    cp = cpk = 0
    if std_v > 0 and ll is not None and hl is not None:
        tol = hl - ll
        cp = tol / (6 * std_v) if tol > 0 else 0
        cpl = (mean_v - ll) / (3 * std_v)
        cpu = (hl - mean_v) / (3 * std_v)
        cpk = min(cpl, cpu)
    return {'has_data': True, 'mean': mean_v, 'std': std_v, 'min': min_v, 'max': max_v, 'cp': cp, 'cpk': cpk}


def compute_rr_statistics(file_datasets, test_name, num_sigma=6) -> dict:
    """Compute full R&R statistics for a test item across all files."""
    # Collect values per file
    test_values, test_mins, test_maxs, test_units = {}, {}, {}, {}
    for ds in file_datasets:
        fn = ds['filename']
        test_mins[fn] = _limit_or_none(ds['metadata'].get('mins', {}).get(test_name))
        test_maxs[fn] = _limit_or_none(ds['metadata'].get('maxs', {}).get(test_name))
        test_units[fn] = ds['metadata'].get('units', {}).get(test_name, '')
        if test_name in ds['df'].columns:
            try:
                test_values[fn] = [float(v) for v in ensure_numeric(ds['df'], test_name).dropna().tolist()]
            except Exception:
                test_values[fn] = []
        else:
            test_values[fn] = []

    # Compute file-level and global stats
    filenames = [ds['filename'] for ds in file_datasets]
    file_means, file_stds, all_values = np.array([]), np.array([]), []
    file_stats = []
    for idx, fn in enumerate(filenames):
        vals = test_values.get(fn, [])
        if vals:
            arr = np.array(vals, dtype=np.float64)
            all_values.extend(vals)
            f_mean = float(arr.mean())
            f_std = float(arr.std(ddof=0) if len(arr) > 1 else 0)
            f_min, f_max = float(arr.min()), float(arr.max())
            file_means = np.append(file_means, f_mean)
            file_stds = np.append(file_stds, f_std)
            ll, hl = test_mins[fn], test_maxs[fn]
            cp = cpk = 0
            if f_std > 0 and ll is not None and hl is not None:
                tol = hl - ll
                cp = tol / (6 * f_std) if tol > 0 else 0
                cpl, cpu = (f_mean - ll) / (3 * f_std), (hl - f_mean) / (3 * f_std)
                cpk = min(cpl, cpu)
            file_stats.append(dict(has_data=True, mean=f_mean, std=f_std, min=f_min, max=f_max, cp=cp, cpk=cpk))
        else:
            file_stats.append(dict(has_data=False, mean=0, std=0, min=0, max=0, cp=0, cpk=0))

    all_arr = np.array(all_values, dtype=np.float64) if all_values else np.array([])
    global_mean = float(all_arr.mean()) if len(all_arr) > 0 else 0
    global_std = float(all_arr.std(ddof=0)) if len(all_arr) > 0 else 0

    # Tolerance from first file with valid, non-equal numeric limits (defect #3:
    # a missing limit stays None and never defaults to a magic 0/4).
    low_limit = high_limit = None
    tolerance = 0
    for fn, lv in test_mins.items():
        hv = test_maxs[fn]
        if lv is not None and hv is not None and hv != lv:
            low_limit, high_limit, tolerance = lv, hv, hv - lv
            break

    num_files = len(file_datasets)
    overall_cp = tolerance / (6 * global_std) if global_std > 0 and tolerance > 0 else 0
    if global_std > 0 and low_limit is not None and high_limit is not None:
        cpk_low = (global_mean - low_limit) / (3 * global_std)
        cpk_high = (high_limit - global_mean) / (3 * global_std)
        overall_cpk = min(cpk_low, cpk_high)
    else:
        overall_cpk = 0

    sumsq = np.sum(np.square(file_stds))
    repeatability = num_sigma * (sumsq / num_files) ** 0.5 if len(file_stds) > 0 and file_stds.sum() > 0 else 0
    reproducibility = num_sigma * file_means.std(ddof=0) if len(file_means) > 1 else 0
    r_r = (repeatability ** 2 + reproducibility ** 2) ** 0.5
    r_r_pct = r_r / tolerance if tolerance > 0 else (r_r / abs(global_mean) if global_mean != 0 else 0)
    r_r_pct_display = r_r_pct * 100
    fail_level = 'Bad1' if r_r_pct_display >= 30 else ('Bad2' if r_r_pct_display >= 10 else 'Good')
    is_bad = r_r_pct_display >= 30

    return {
        'file_stats': file_stats,
        'test_mins': test_mins, 'test_maxs': test_maxs, 'test_units': test_units,
        'global_mean': global_mean, 'global_std': global_std, 'tolerance': tolerance,
        'overall_cp': overall_cp, 'overall_cpk': overall_cpk,
        'repeatability': repeatability, 'reproducibility': reproducibility,
        'r_r': r_r, 'r_r_pct': r_r_pct, 'fail_level': fail_level, 'is_bad': is_bad,
    }
