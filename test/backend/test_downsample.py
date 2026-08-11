"""Tests for large-data scatter downsampling (downsample.py + 3 endpoints).

Pins the performance optimization: qqplot / serial_distribution /
correlation must down-sample points to ≤ MAX_POINTS when the dataset
exceeds DOWN_SAMPLE_THRESHOLD, while all statistics (r² / pass-fail
counts / pearson_r) are always computed on the full data.  Inputs at or
below the threshold must be returned unchanged (zero behavior change).

Run directly:  python test/backend/test_downsample.py
"""
import os
import sys

# test/backend/ → project root (for `import config` / `from apps...`)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from apps.analysis.services.statistics.downsample import (  # noqa: E402
    uniform_indices, bucket_minmax_indices, MAX_POINTS,
    DOWN_SAMPLE_THRESHOLD,
)
from apps.analysis.services.statistics.computations import compute_qqplot  # noqa: E402
from apps.analysis.services.data_services.serial_distribution import (  # noqa: E402
    compute_serial_distribution_data,
)
from apps.analysis.services.data_services.correlation import (  # noqa: E402
    compute_correlation_scatter,
)

RNG = np.random.default_rng(42)

META = {
    'format': 'CTA8280F',
    'units': {'CON_VIN': 'V', 'CON_VCC': 'V'},
    'mins': {'CON_VIN': '-0.57', 'CON_VCC': '-0.58'},
    'maxs': {'CON_VIN': '-0.39', 'CON_VCC': '-0.40'},
}


# ---------------------------------------------------------------------------
# downsample.py primitives
# ---------------------------------------------------------------------------

def test_uniform_indices_small_returns_all():
    n = 2000
    out = uniform_indices(n)
    assert len(out) == n
    assert (out == np.arange(n)).all()


def test_uniform_indices_large_caps_at_max():
    n = 80_000
    out = uniform_indices(n)
    assert len(out) == MAX_POINTS
    assert out[0] == 0 and out[-1] == n - 1
    assert (np.diff(out) > 0).all()  # 升序去重


def test_bucket_minmax_small_returns_all():
    keys = RNG.normal(size=100)
    out = bucket_minmax_indices(keys)
    assert (out == np.arange(100)).all()


def test_bucket_minmax_large_caps_and_keeps_ends():
    keys = RNG.normal(size=80_000)
    out = bucket_minmax_indices(keys)
    assert len(out) <= MAX_POINTS
    # 返回索引按值升序；保形核心是全局极值点被保留（而非位置）
    keep = set(out.tolist())
    assert int(np.argmin(keys)) in keep
    assert int(np.argmax(keys)) in keep


def test_bucket_minmax_preserves_value_extremes():
    """全局 y 极值点（与 x 无关的位置）必须被保留——保形轮廓的核心。"""
    n = 80_000
    keys = np.arange(n, dtype=float)
    vals = RNG.normal(size=n)
    i_min, i_max = 12_345, 67_890
    vals[i_min] = -100.0
    vals[i_max] = 100.0
    keep = set(bucket_minmax_indices(keys, vals).tolist())
    assert i_min in keep and i_max in keep


def test_bucket_minmax_nan_values_skipped_for_extremes():
    """NaN（无测量值）不参与极值选择；有值点仍保极值。"""
    n = 10_000
    keys = np.arange(n, dtype=float)
    vals = np.full(n, 0.5)
    vals[::2] = np.nan  # 一半 NaN
    vals[3_333] = 42.0
    keep = set(bucket_minmax_indices(keys, vals).tolist())
    assert 3_333 in keep  # 全局 max 被保留


# ---------------------------------------------------------------------------
# compute_qqplot
# ---------------------------------------------------------------------------

def test_qqplot_downsamples_large_keeps_stats_full():
    data = pd.Series(RNG.normal(0, 1, 80_000))
    res = compute_qqplot(data, META, 'CON_VIN')
    assert res['n'] == 80_000  # 统计口径全量
    assert 0 < len(res['theoretical_quantiles']) <= MAX_POINTS
    assert len(res['observed_quantiles']) == len(res['theoretical_quantiles'])
    assert bool(res['is_normal']) is True  # 正态数据 r² 高（numpy.bool_ 兼容）
    assert res['r_squared'] > 0.9


def test_qqplot_below_threshold_unchanged():
    """3000 点 > MAX_POINTS 但 ≤ 阈值 → 不采样（零变更）。"""
    data = pd.Series(RNG.normal(0, 1, 3_000))
    res = compute_qqplot(data, META, 'CON_VIN')
    assert len(res['theoretical_quantiles']) == 3_000
    assert res['n'] == 3_000


def test_qqplot_empty_still_graceful():
    res = compute_qqplot(pd.Series([], dtype=float), META, 'CON_VIN')
    assert res['n'] == 0
    assert res['theoretical_quantiles'] == []


# ---------------------------------------------------------------------------
# serial_distribution
# ---------------------------------------------------------------------------

def _build_serial_df(n=6_000, n_out_of_range=3, n_fail=7):
    """n 颗 die：正态值（限内）+ n_out_of_range 个超界值 + n_fail 个 fail。"""
    rows = []
    fail_serials = set(RNG.choice(n, n_fail, replace=False) + 1)
    for s in range(1, n + 1):
        v = float(-0.48 + 0.005 * RNG.normal())
        if s <= n_out_of_range:  # 超上界 → anchor=2
            v = 1000.0
        rows.append({
            'Serial_No': s, 'Site_No': 1,
            'SW_Bin': 5 if s in fail_serials else 1,
            'CON_VIN': v,
        })
    return pd.DataFrame(rows)


def _all_points(result):
    return [pt for s in result['series_data'] for pt in s['data']]


def test_serial_distribution_downsamples_large_keeps_anchors_and_stats():
    df = _build_serial_df()
    result = compute_serial_distribution_data(
        df, META, 'CON_VIN', 'RDL', ['limit', 's6'])
    pts = _all_points(result)
    assert 0 < len(pts) <= MAX_POINTS + 4  # anchor 强制保留可略超
    # pass/fail 统计全量
    assert result['pass_count'] == 6_000 - 7
    assert result['fail_count'] == 7
    # 全部超界锚定点（anchor=2）必须保留
    anchors = [pt for pt in pts if len(pt) > 3 and pt[3] != 0]
    assert len(anchors) == 3
    assert all(pt[3] == 2 for pt in anchors)


def test_serial_distribution_small_unchanged():
    df = _build_serial_df(n=20)
    result = compute_serial_distribution_data(
        df, META, 'CON_VIN', 'RDL', ['limit', 's6'])
    assert len(_all_points(result)) == 20  # 20 ≤ 阈值 → 全量


# ---------------------------------------------------------------------------
# correlation
# ---------------------------------------------------------------------------

def test_correlation_downsamples_large_keeps_pearson():
    n = 6_000
    x = RNG.normal(0, 1, n)
    y = 2.0 * x + RNG.normal(0, 0.1, n)
    df = pd.DataFrame({'Site_No': 1, 'CON_VIN': x, 'CON_VCC': y})
    result = compute_correlation_scatter(df, 'CON_VIN', 'CON_VCC', META)
    pts = [pt for s in result['series_data'] for pt in s['data']]
    assert 0 < len(pts) <= MAX_POINTS
    assert result['n'] == n  # 全量
    assert result['pearson_r'] > 0.9  # 强正相关


def test_correlation_small_unchanged():
    n = 100
    x = RNG.normal(0, 1, n)
    y = 2.0 * x + RNG.normal(0, 0.1, n)
    df = pd.DataFrame({'Site_No': 1, 'CON_VIN': x, 'CON_VCC': y})
    result = compute_correlation_scatter(df, 'CON_VIN', 'CON_VCC', META)
    pts = [pt for s in result['series_data'] for pt in s['data']]
    assert len(pts) == n


if __name__ == '__main__':
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print('ok   %s' % name)
            except AssertionError as exc:
                failures += 1
                print('FAIL %s: %s' % (name, exc))
    if failures:
        print('\n%d test(s) failed' % failures)
        sys.exit(1)
    print('\nAll downsampling tests passed')
