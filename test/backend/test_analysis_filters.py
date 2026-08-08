"""Tests for the analysis chart-config filter helpers (filters.py).

Runnable directly:  python test/backend/test_analysis_filters.py
Mirrors the runner style of test/backend/test_histogram_range_type.py.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
import django
django.setup()

import numpy as np
import pandas as pd

from apps.analysis.services.statistics.filters import (
    NO_TEST_VALUE_MIN_RATIO,
    filter_bin1_rows,
    has_enough_test_values,
    compute_low_cpk_test_items,
    filter_test_items,
)

# CTA8280F format → Bin column is "SW_Bin"
BIN_COL = 'SW_Bin'
PARAM_A = 'voltage_a'    # limits 8.0 ~ 14.3
PARAM_B = 'current_b'    # limits 0.5 ~ 3.5
PARAM_NOLIMIT = 'misc_c'  # no spec limits

METADATA = {
    'mins': {PARAM_A: '8.0', PARAM_B: '0.5'},
    'maxs': {PARAM_A: '14.3', PARAM_B: '3.5'},
    'units': {PARAM_A: 'V', PARAM_B: 'uA'},
    'format': 'CTA8280F',
}


def _df(**cols):
    return pd.DataFrame(cols)


# ── filter_bin1_rows ──────────────────────────────────────────────────

def test_filter_bin1_rows_int_bins():
    df = _df(**{BIN_COL: [1, 1, 2, 3, 1], PARAM_A: [10.1, 10.2, 9.0, 9.5, 10.3]})
    out = filter_bin1_rows(df, METADATA)
    assert len(out) == 3
    assert (out[BIN_COL] == 1).all()


def test_filter_bin1_rows_string_bins():
    df = _df(**{BIN_COL: ['1', 'Bin1', '2', 'BIN1', '1.0'], PARAM_A: [10.1, 10.2, 9.0, 10.4, 10.3]})
    out = filter_bin1_rows(df, METADATA)
    assert len(out) == 4  # '2' excluded, "Bin1"/"BIN1"/"1.0" all pass
    assert '2' not in out[BIN_COL].tolist()


def test_filter_bin1_rows_no_bin_column_returns_same_frame():
    df = _df(**{PARAM_A: [10.1, 10.2, 10.3]})
    out = filter_bin1_rows(df, METADATA)
    assert out is df  # ignored: same object, no copy


def test_filter_bin1_rows_all_nan_bins_returns_empty():
    df = _df(**{BIN_COL: [np.nan, np.nan], PARAM_A: [10.1, 10.2]})
    out = filter_bin1_rows(df, METADATA)
    assert len(out) == 0
    # and the cached frame is untouched
    assert len(df) == 2


# ── has_enough_test_values ────────────────────────────────────────────

def test_has_enough_test_values_all_nan_false():
    df = _df(**{PARAM_A: [np.nan] * 10})
    assert has_enough_test_values(df, PARAM_A) is False


def test_has_enough_test_values_full_true():
    df = _df(**{PARAM_A: list(range(10))})
    assert has_enough_test_values(df, PARAM_A) is True


def test_has_enough_test_values_ratio_boundary():
    df = _df(**{PARAM_A: [1.0] * 5 + [np.nan] * 5})
    assert has_enough_test_values(df, PARAM_A, min_ratio=0.5) is True   # exactly at ratio
    assert has_enough_test_values(df, PARAM_A, min_ratio=0.51) is False  # just below
    assert NO_TEST_VALUE_MIN_RATIO == 0.05  # document the shipped default


# ── compute_low_cpk_test_items ────────────────────────────────────────

def _low_cpk_frame():
    np.random.seed(42)
    return _df(
        # near lower limit, wide spread → very low CPK
        **{PARAM_A: np.random.normal(8.6, 1.0, 500),
           # centered, tight → high CPK
           PARAM_B: np.random.normal(2.0, 0.15, 500),
           # no spec limits
           PARAM_NOLIMIT: np.random.normal(100.0, 1.0, 500)})


def test_compute_low_cpk_test_items():
    df = _low_cpk_frame()
    low = compute_low_cpk_test_items(df, METADATA, threshold=1.33)
    assert PARAM_A in low          # cpk ~0.2 < 1.33
    assert PARAM_B not in low      # cpk ~3.3 > 1.33
    assert PARAM_NOLIMIT not in low  # no limits → cannot judge → excluded


def test_low_cpk_uses_filtered_cpk_when_outliers_exist():
    """低 CPK 判定无条件跟随统计卡显示口径：有异常值的列用 filtered CPK。

    Regression: 前端 CPK 卡在 filtered_cpk 非空时总是显示 ``3.19 (filtered)``
    （与异常值处理开关无关，useHistogram 无条件优先 filtered_cpk）。所以
    判定也不能依赖开关——否则默认（未开异常值处理）时剔除异常值后健康的
    参数仍会被列入低 CPK 列表。
    """
    # 14.4 超 usl 14.3 → 异常值：全量 CPK 低、filtered CPK 健康
    df = _df(**{PARAM_A: [10.9, 11.0, 11.05, 11.0, 11.02,
                          14.4, 10.98, 11.01, 10.99, 11.0]})
    low = compute_low_cpk_test_items(df, METADATA, threshold=1.33)
    assert PARAM_A not in low

    # 对照：无异常值、全量 CPK 本身低的列仍列入
    df2 = _df(**{PARAM_A: [8.5, 8.6, 8.7, 8.8, 8.9, 8.4, 8.6, 8.8, 9.0, 9.2]})
    low2 = compute_low_cpk_test_items(df2, METADATA, threshold=1.33)
    assert PARAM_A in low2


def test_compute_low_cpk_zero_std_matches_histogram():
    df = _df(**{PARAM_A: [10.45] * 20, PARAM_B: [2.0] * 20})
    low = compute_low_cpk_test_items(df, METADATA, threshold=1.33)
    # std exactly 0.0 (2.0*20 averages to exactly 2.0) → compute_cpk guard
    # returns cpk=0 → low, exactly what the histogram shows.
    assert PARAM_B in low
    # 10.45*20 leaves floating-point noise → tiny-but-positive std → huge
    # cpk, identical to the histogram endpoint, so NOT low.
    assert PARAM_A not in low


# ── filter_test_items ─────────────────────────────────────────────────

def test_filter_test_items_ignore_no_test_value():
    df = _df(**{PARAM_A: list(range(100)), PARAM_B: [np.nan] * 100,
                PARAM_NOLIMIT: list(range(100))})
    out = filter_test_items(df, METADATA,
                            [PARAM_A, PARAM_B, PARAM_NOLIMIT],
                            ignore_no_test_value=True)
    assert out == [PARAM_A, PARAM_NOLIMIT]


def test_filter_test_items_only_fail():
    # row 1 is a fail row (bin 2) where PARAM_A exceeds its spec
    df = _df(**{BIN_COL: [1, 2, 1, 1],
                PARAM_A: [10.0, 9.0, 10.1, 10.2],   # 9.0 < lsl 8.0? no; use out-of-spec above usl
                PARAM_B: [2.0, 2.1, 2.2, 2.3]})
    # PARAM_A at row 1 must exceed usl 14.3 → 15.0
    df.loc[1, PARAM_A] = 15.0
    out = filter_test_items(df, METADATA, [PARAM_A, PARAM_B],
                            only_fail_test_item=True)
    assert out == [PARAM_A]
    assert PARAM_B not in out


def test_filter_test_items_only_fail_no_bin_column_ignored():
    df = _df(**{PARAM_A: [10.0, 15.0], PARAM_B: [2.0, 2.1]})
    out = filter_test_items(df, METADATA, [PARAM_A, PARAM_B],
                            only_fail_test_item=True)
    assert out == [PARAM_A, PARAM_B]  # treated as off


def test_filter_test_items_only_low_cpk():
    df = _low_cpk_frame()
    out = filter_test_items(df, METADATA, [PARAM_A, PARAM_B, PARAM_NOLIMIT],
                            only_low_cpk=True, cpk_threshold=1.33)
    assert out == [PARAM_A]


def test_filter_test_items_fail_set_survives_bin1_filter():
    """The ordering guard: fail items must be computed from the FULL frame.
    When bin1 filtering happens first, the internal fail detection would see
    no fail rows — the precomputed fail_items argument is what keeps the
    switch working together with data_only_bin1."""
    df_full = _df(**{BIN_COL: [1, 2, 1, 1],
                     PARAM_A: [10.0, 15.0, 10.1, 10.2],
                     PARAM_B: [2.0, 2.1, 2.2, 2.3]})
    df_work = filter_bin1_rows(df_full, METADATA)  # 3 rows, all bin1
    fail_items = {PARAM_A}  # computed from df_full in the view layer

    out = filter_test_items(df_work, METADATA, [PARAM_A, PARAM_B],
                            only_fail_test_item=True, fail_items=fail_items)
    assert out == [PARAM_A]

    # Without the precomputed set the internal detection on df_work finds
    # nothing → the switch would wipe the whole list.
    out_internal = filter_test_items(df_work, METADATA, [PARAM_A, PARAM_B],
                                     only_fail_test_item=True)
    assert out_internal == []


def test_filter_test_items_combined_switches():
    # PARAM_A: 超限点（fail）+ 剩余值贴近下限（剔除异常值后 CPK 仍低）→
    # 同时通过 fail 与低 CPK 两道筛选（含超限异常值但过滤后仍低的情况）。
    df = _df(**{BIN_COL: [1, 2, 1, 2, 1, 2, 1, 2, 1, 2],
                PARAM_A: [8.1, 15.0, 8.2, 15.0, 8.1,
                          15.0, 8.2, 15.0, 8.1, 15.0],
                PARAM_B: [np.nan] * 10,                # no values
                PARAM_NOLIMIT: list(range(10))})        # no limits, has values
    out = filter_test_items(df, METADATA, [PARAM_A, PARAM_B, PARAM_NOLIMIT],
                            ignore_no_test_value=True,
                            only_fail_test_item=True,
                            only_low_cpk=True, cpk_threshold=1.33)
    assert out == [PARAM_A]


# ── runner ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
            except AssertionError as exc:
                failures += 1
                print('FAIL %s: %s' % (name, exc))
    if failures:
        print('\n%d test(s) failed' % failures)
        sys.exit(1)
    print('\nAll analysis filter tests passed')
