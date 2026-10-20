"""Gage R&R 汇总的纯统计部分。

从 `gage_legacy_builder` 迁出：测试项筛选、逐文件统计与组级 R&R。这里不碰
excelize、也不写单元格，所以数值口径可以脱离 Excel 直接断言。
"""
from typing import List, NamedTuple, Optional

import numpy as np

from apps.analysis.services.statistics import ensure_numeric
from apps.common.constants import NON_NUMERIC_KEYWORDS
from apps.datafiles.parsers.base import SYSTEM_COLUMNS

# R&R% 分档：≥ 30% = Bad1（红），≥ 10% = Bad2（橙）。
# 同一组阈值既决定 Fail Level / 分组折叠，也是 R&R% 列条件格式的分档。
RR_PCT_BAD1 = 0.30
RR_PCT_BAD2 = 0.10

# Repeatability/Reproducibility 的 σ 倍数（Excel 侧公式与这里必须同口径）。
NUM_SIGMA = 6


def safe_float_or_none(val):
    """Parse a spec-limit cell into float, or None when missing/non-numeric.

    Returning None (never a magic 0/4) is what lets the caller distinguish a
    legitimate limit of 0 or 4 from an absent one (defect #3).
    """
    if val is None:
        return None
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def select_test_columns(file_datasets, ignore_no_limit=False):
    """Build the list of test columns (defect #7).

    System columns (Serial_No / QR_Code / Start_T / Dut_Pass / SW_Bin …) and
    non-numeric columns are ALWAYS excluded regardless of ignore_no_limit;
    ignore_no_limit only decides whether to further drop items without a valid
    numeric limit.
    """
    first_metadata = file_datasets[0]['metadata']
    first_df = file_datasets[0]['df']
    system_cols = set(SYSTEM_COLUMNS.get(first_metadata.get('format', ''), []))

    def _col_has_numeric(col):
        for ds in file_datasets:
            dfx = ds['df']
            if col in dfx.columns:
                try:
                    if len(ensure_numeric(dfx, col).dropna()) > 0:
                        return True
                except Exception:
                    pass
        return False

    all_test_cols = []
    for col in first_df.columns:
        if col in system_cols:
            continue
        if not _col_has_numeric(col):
            continue
        if ignore_no_limit:
            min_raw = first_metadata.get('mins', {}).get(col)
            max_raw = first_metadata.get('maxs', {}).get(col)
            if min_raw is None or max_raw is None:
                continue
            min_str = str(min_raw).strip()
            max_str = str(max_raw).strip()
            if not min_str or not max_str:
                continue
            if min_str.lower() in NON_NUMERIC_KEYWORDS or max_str.lower() in NON_NUMERIC_KEYWORDS:
                continue
            try:
                float(min_str)
                float(max_str)
            except (ValueError, TypeError):
                continue
        all_test_cols.append(col)
    return all_test_cols


class TestItemStats(NamedTuple):
    """一个测试项的组级统计 + 逐文件行数据（写表所需的 everything）。"""

    test_name: str
    per_file: List[dict]
    global_mean: float
    global_std: float
    tolerance: float
    tol_idx: Optional[int]
    overall_cp: float
    overall_cpk: float
    repeatability: float
    reproducibility: float
    r_r_pct: Optional[float]
    fail_level: str
    is_bad_group: bool
    min_cpk: float
    max_cpk: float


def analyze_test_item(test_name, file_datasets, num_files) -> TestItemStats:
    """Compute one test item across all files.

    ``num_files`` 是文件总数（Repeatability 的分母沿用旧口径：除全部文件，
    不是只除有数据的那些）。
    """
    test_values_by_file = {}
    test_units_by_file = {}
    test_mins_by_file = {}
    test_maxs_by_file = {}

    for file_info in file_datasets:
        fn = file_info['filename']
        df = file_info['df']
        metadata = file_info['metadata']

        # Missing limit stays None (never magic 0/4) — defect #3.
        test_mins_by_file[fn] = metadata.get('mins', {}).get(test_name)
        test_maxs_by_file[fn] = metadata.get('maxs', {}).get(test_name)
        test_units_by_file[fn] = metadata.get('units', {}).get(test_name, '')

        if test_name in df.columns:
            try:
                vals = ensure_numeric(df, test_name).dropna().tolist()
            except Exception:
                vals = []
            test_values_by_file[fn] = vals
        else:
            test_values_by_file[fn] = []

    # ── Per-file statistics, computed once and shared by every consumer
    # (per-file row, Min/Max CPK, group stats) so they cannot diverge.
    # `fs` is always initialized inside the n>0 branch (defect #2): a
    # single-value file gets std 0.0 instead of inheriting the previous
    # test item's std or raising UnboundLocalError.
    per_file = []
    for file_info in file_datasets:
        fn = file_info['filename']
        vals = test_values_by_file.get(fn, [])
        low_l = safe_float_or_none(test_mins_by_file.get(fn))
        high_l = safe_float_or_none(test_maxs_by_file.get(fn))
        unit = test_units_by_file.get(fn, '')
        arr = np.array(vals, dtype=np.float64) if vals else np.array([], dtype=np.float64)
        n = len(arr)
        entry = {'fn': fn, 'vals': vals, 'low_l': low_l, 'high_l': high_l,
                 'unit': unit, 'has_data': n > 0, 'mean': None, 'std': None,
                 'min': None, 'max': None, 'cp': None, 'cpk': None}
        if n > 0:
            fm = float(arr.mean())
            fs = float(arr.std(ddof=0)) if n > 1 else 0.0
            entry['mean'] = fm
            entry['std'] = fs
            entry['min'] = float(arr.min())
            entry['max'] = float(arr.max())
            # Legit limits of 0 or 4 are honoured; only None means missing
            # (defect #3 — no `!= 0` / `!= 4` sentinel).
            if fs > 0 and low_l is not None and high_l is not None:
                tol_f = high_l - low_l
                entry['cp'] = tol_f / (6 * fs) if tol_f > 0 else 0.0
                cpk_low_f = (fm - low_l) / (3 * fs)
                cpk_high_f = (high_l - fm) / (3 * fs)
                entry['cpk'] = min(cpk_low_f, cpk_high_f)
        per_file.append(entry)

    # ── Group statistics over files that actually have data (defect #1):
    # an empty file contributes nothing instead of a 0.0 / uninitialized
    # garbage mean that would pollute reproducibility.
    all_values = []
    file_means_list = []
    file_stds_list = []
    for entry in per_file:
        if entry['has_data']:
            all_values.extend(entry['vals'])
            file_means_list.append(entry['mean'])
            file_stds_list.append(entry['std'])

    all_arr = np.array(all_values, dtype=np.float64) if all_values else np.array([], dtype=np.float64)
    global_mean = float(all_arr.mean()) if len(all_arr) > 0 else 0.0
    global_std = float(all_arr.std(ddof=0)) if len(all_arr) > 0 else 0.0

    # Tolerance from the first file with valid, non-equal numeric limits.
    low_limit = None
    high_limit = None
    tolerance = 0.0
    tol_idx = None
    for idx, entry in enumerate(per_file):
        lv, hv = entry['low_l'], entry['high_l']
        if lv is not None and hv is not None and hv != lv:
            low_limit, high_limit = lv, hv
            tolerance = hv - lv
            tol_idx = idx
            break

    overall_cp = 0.0
    overall_cpk = 0.0
    if global_std > 0 and tolerance > 0 and low_limit is not None and high_limit is not None:
        overall_cp = tolerance / (6 * global_std)
        cpk_low = (global_mean - low_limit) / (3 * global_std)
        cpk_high = (high_limit - global_mean) / (3 * global_std)
        overall_cpk = min(cpk_low, cpk_high)

    means_arr = np.array(file_means_list, dtype=np.float64) if file_means_list else np.array([], dtype=np.float64)
    stds_arr = np.array(file_stds_list, dtype=np.float64) if file_stds_list else np.array([], dtype=np.float64)

    # Repeatability keeps the existing 6*sqrt(sum(std^2)/num_files) formula.
    if len(stds_arr) > 0 and float(np.sum(stds_arr)) > 0:
        repeatability_val = NUM_SIGMA * (float(np.sum(np.square(stds_arr))) / num_files) ** 0.5
    else:
        repeatability_val = 0.0

    # Reproducibility = 6*std(file_means) over data-bearing files only.
    if len(means_arr) > 1:
        reproducibility_val = NUM_SIGMA * float(means_arr.std(ddof=0))
    else:
        reproducibility_val = 0.0

    r_r_val = (repeatability_val ** 2 + reproducibility_val ** 2) ** 0.5

    # R&R% and Fail Level share one source (defect #5). Missing tolerance
    # → both N/A, and the item is NOT counted as a Bad1 failure. No silent
    # fallback to r_r/|global_mean| (different dimension).
    r_r_pct = (r_r_val / tolerance) if tolerance > 0 else None

    if r_r_pct is None:
        fail_level = 'N/A'
        is_bad_group = False
    else:
        fail_level = ('Bad1' if r_r_pct >= RR_PCT_BAD1
                      else 'Bad2' if r_r_pct >= RR_PCT_BAD2 else 'Good')
        is_bad_group = r_r_pct >= RR_PCT_BAD1

    # Min/Max CPK across files with a valid CPK (defect #4 — not overall_cpk).
    valid_cpks = [e['cpk'] for e in per_file if e['cpk'] is not None]
    min_cpk = min(valid_cpks) if valid_cpks else 0.0
    max_cpk = max(valid_cpks) if valid_cpks else 0.0

    return TestItemStats(
        test_name=test_name,
        per_file=per_file,
        global_mean=global_mean,
        global_std=global_std,
        tolerance=tolerance,
        tol_idx=tol_idx,
        overall_cp=overall_cp,
        overall_cpk=overall_cpk,
        repeatability=repeatability_val,
        reproducibility=reproducibility_val,
        r_r_pct=r_r_pct,
        fail_level=fail_level,
        is_bad_group=is_bad_group,
        min_cpk=min_cpk,
        max_cpk=max_cpk,
    )
