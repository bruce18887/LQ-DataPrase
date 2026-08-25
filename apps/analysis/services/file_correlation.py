"""Two-file correlation computation (ATE vs Bench, aligned by serial).

Pure computation — no request dependency.  Shared by the JSON
``file_correlation`` endpoint (panel rendering) and the xlsx export
endpoint, so the two outputs always agree.

Comparison rules (mirrored by the frontend panel one-to-one):
- %Diff = (Bench − ATE) / ATE × 100, signed; |%Diff| > threshold → red.
- LSL/USL Diff columns = signed B − A; red rule selectable:
    'zero'  : pass iff both diffs are exactly 0.
    'wider' : pass iff file B's limit is no tighter than file A's
              (LSL_B ≤ LSL_A and USL_B ≥ USL_A).
- Serial cap: only the first ``max_serials`` common serials (ascending).
- No common serials → limits-only mode (no per-serial data columns).
- No common params → NoCommonParamsError (surfaced as 400 by the views).
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from apps.analysis.services.statistics.helpers import get_serial_candidates
from apps.common.constants import NON_NUMERIC_KEYWORDS

# Extra placeholders parsers may emit meaning "no limit" on top of the
# shared NON_NUMERIC_KEYWORDS list.
_NO_LIMIT_PLACEHOLDERS = {'·', '—', ''}
_NON_LIMIT_SENTINELS = set(NON_NUMERIC_KEYWORDS) | _NO_LIMIT_PLACEHOLDERS


class NoCommonParamsError(Exception):
    """The two files share no numeric test items (防呆: nothing to compare)."""


@dataclass
class FileCorrelationConfig:
    """Comparison options; the frontend panel mirrors these one-to-one."""
    threshold: float = 3.0
    diff_rule: str = 'zero'          # 'zero' | 'wider'
    max_serials: int = 30
    ignore_no_limit: bool = True
    ignore_no_data: bool = True


def _parse_limit(raw) -> Optional[float]:
    """Numeric-parse a metadata limit; None for any 'no limit' sentinel."""
    if raw is None:
        return None
    s = str(raw).strip().strip('"')
    if not s or s in _NON_LIMIT_SENTINELS:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _numeric_params(df: pd.DataFrame) -> List[str]:
    """Numeric columns in file order.

    排除序列候选列（Serial_No / Dut_No / PART_ID 等）——序列列是两文件的
    对齐键，把序列号本身当测试项对比毫无意义，还会让「无相同测试项」
    防呆（NoCommonParamsError）永远无法触发。
    """
    excluded = set(get_serial_candidates(df)) | {'__serial__'}
    return [c for c in df.columns
            if c not in excluded and df[c].dtype in ('int64', 'float64')]


def _limits_for(param: str, meta: dict) -> Tuple[Optional[float], Optional[float]]:
    """→ (lsl, usl) for a param, None where the metadata has no limit."""
    mins = meta.get('mins') or {}
    maxs = meta.get('maxs') or {}
    return _parse_limit(mins.get(param)), _parse_limit(maxs.get(param))


def _has_any_limit(param: str, meta: dict) -> bool:
    lsl, usl = _limits_for(param, meta)
    return lsl is not None or usl is not None


def _serial_frame(df: pd.DataFrame, serials: List[int],
                  params: List[str]) -> pd.DataFrame:
    """One row per serial (first occurrence) for the requested params.

    Vectorized replacement for the old per-(param, serial) scalar loop:
    groupby + first() once per file, then numeric-coerce + reindex.
    """
    sub = df[df['__serial__'].isin(serials)][['__serial__'] + params]
    agg = sub.groupby('__serial__')[params].first()
    for p in params:
        agg[p] = pd.to_numeric(agg[p], errors='coerce')
    return agg.reindex(serials)


def _evaluate_diff_rule(lsl_a: Optional[float], usl_a: Optional[float],
                        lsl_b: Optional[float], usl_b: Optional[float],
                        rule: str) -> Tuple[bool, bool]:
    """→ (lsl_fail, usl_fail).  A missing limit on either side is a fail."""
    if rule == 'wider':
        # B 的 limit 不更紧才算 pass（更宽或相等）
        lsl_fail = not (lsl_a is not None and lsl_b is not None and lsl_b <= lsl_a)
        usl_fail = not (usl_a is not None and usl_b is not None and usl_b >= usl_a)
    else:  # 'zero'（默认）：两侧差值必须恰为 0
        lsl_fail = not (lsl_a is not None and lsl_b is not None
                        and (lsl_b - lsl_a) == 0.0)
        usl_fail = not (usl_a is not None and usl_b is not None
                        and (usl_b - usl_a) == 0.0)
    return lsl_fail, usl_fail


def _jf(v) -> Optional[float]:
    """JSON-safe float: NaN/±Inf → None; 8 位小数规整去浮点噪声
    （0.10000000000000009 → 0.1，同时保留 1e-7 级小量）。"""
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return None
    return round(float(v), 8)


def compute_file_correlation(ate_df: pd.DataFrame, meta_a: dict,
                             bench_df: pd.DataFrame, meta_b: dict,
                             cfg: FileCorrelationConfig,
                             file1_name: str = '',
                             file2_name: str = '') -> dict:
    """Compare two files aligned by serial number.

    Parameters
    ----------
    ate_df / bench_df : DataFrames carrying the ``__serial__`` helper column
        (the views copy + inject it; never mutate cached frames here).
    meta_a / meta_b   : parser metadata (mins/maxs/units dicts).
    cfg               : comparison options (threshold / diff_rule / ...).
    file1_name / file2_name : filenames for display.

    Returns a JSON-ready dict::

        {file1_name, file2_name, serials, limits_only, truncated,
         params, rows: [...], totals: {...}}

    Raises
    ------
    NoCommonParamsError
        When the two files share no numeric test items (防呆).
    """
    ate_ser = pd.to_numeric(ate_df['__serial__'], errors='coerce')
    bench_ser = pd.to_numeric(bench_df['__serial__'], errors='coerce')
    common_serials = sorted(
        set(ate_ser.dropna().astype(int)) & set(bench_ser.dropna().astype(int)))

    bench_numeric = set(_numeric_params(bench_df))
    params = [p for p in _numeric_params(ate_df) if p in bench_numeric]
    if not params:
        raise NoCommonParamsError()

    # ignore no limit（默认勾选）：任一侧都没有 limit 的测试项不参与对比
    if cfg.ignore_no_limit:
        params = [p for p in params
                  if _has_any_limit(p, meta_a) and _has_any_limit(p, meta_b)]

    # 需求5：公共序列数超限时只对比前 N 个（序列号升序）
    serials = common_serials[:cfg.max_serials]
    truncated = len(common_serials) > len(serials)
    limits_only = not serials

    # 每文件一次 groupby 聚合 → 后续全部按参数向量化（需求9：导出高速）
    aggs_a = _serial_frame(ate_df, serials, params)
    aggs_b = _serial_frame(bench_df, serials, params)

    # ignore no data（默认勾选，非 limits-only 时）：所选序列上无任何
    # 有限配对数据的测试项不参与对比
    if cfg.ignore_no_data and not limits_only:
        keep = []
        for p in params:
            a = pd.to_numeric(aggs_a[p], errors='coerce').to_numpy(dtype=float)
            b = pd.to_numeric(aggs_b[p], errors='coerce').to_numpy(dtype=float)
            if (np.isfinite(a) & np.isfinite(b)).any():
                keep.append(p)
        params = keep

    n = len(serials)
    rows = []
    totals_paired = 0
    totals_fail = 0
    for param in params:
        lsl_a, usl_a = _limits_for(param, meta_a)
        lsl_b, usl_b = _limits_for(param, meta_b)
        # 有符号 B−A（规则判定用原始值，输出 8 位规整去浮点噪声）
        lsl_diff = _jf(lsl_b - lsl_a) if (lsl_a is not None and lsl_b is not None) else None
        usl_diff = _jf(usl_b - usl_a) if (usl_a is not None and usl_b is not None) else None
        lsl_fail, usl_fail = _evaluate_diff_rule(lsl_a, usl_a, lsl_b, usl_b,
                                                 cfg.diff_rule)

        cells = []
        compared = 0
        fail_count = 0
        max_diff = 0.0
        if n:
            a = pd.to_numeric(aggs_a[param], errors='coerce').to_numpy(dtype=float)
            b = pd.to_numeric(aggs_b[param], errors='coerce').to_numpy(dtype=float)
            both = np.isfinite(a) & np.isfinite(b)
            delta = np.full(n, np.nan)
            diff_pct = np.full(n, np.nan)
            delta[both] = b[both] - a[both]
            # %Diff = Δ/ATE（用户确认口径）；ATE≈0 的对无法计算 %Diff → NaN
            ok = both & (np.abs(a) > 1e-12)
            diff_pct[ok] = delta[ok] / a[ok] * 100.0
            fail = ok & (np.abs(diff_pct) > cfg.threshold)
            compared = int(ok.sum())
            fail_count = int(fail.sum())
            if compared:
                max_diff = round(float(np.nanmax(np.abs(diff_pct))), 2)
            cells = [
                {'serial': ser, 'ate': _jf(a[i]), 'bench': _jf(b[i]),
                 'delta': _jf(delta[i]), 'diff_pct': _jf(diff_pct[i]),
                 'fail': bool(fail[i])}
                for i, ser in enumerate(serials)
            ]

        pass_rate = round((compared - fail_count) / compared * 100, 2) if compared else 0.0
        rows.append({
            'param': param,
            'unit': (meta_a.get('units') or {}).get(param, ''),
            'lsl_a': lsl_a, 'usl_a': usl_a, 'lsl_b': lsl_b, 'usl_b': usl_b,
            'lsl_diff': lsl_diff, 'usl_diff': usl_diff,
            'lsl_fail': lsl_fail, 'usl_fail': usl_fail,
            'compared': compared, 'fail_count': fail_count,
            'pass_rate': pass_rate, 'max_diff': max_diff,
            'cells': cells,
        })
        totals_paired += compared
        totals_fail += fail_count

    totals = {
        'params': len(rows),
        'serials': len(serials),
        'paired_cells': totals_paired,
        'fail_cells': totals_fail,
        'overall_pass_rate': (
            round((totals_paired - totals_fail) / totals_paired * 100, 2)
            if totals_paired else 0.0),
    }
    return {
        'file1_name': file1_name,
        'file2_name': file2_name,
        'serials': serials,
        'limits_only': limits_only,
        'truncated': truncated,
        'params': [r['param'] for r in rows],
        'rows': rows,
        'totals': totals,
    }
