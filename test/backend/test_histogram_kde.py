"""Unit tests for the histogram KDE curve (``kde_curve``).

The normal distribution overlay is a poor fit for non-normal / bimodal data
(mixed sites or process populations).  ``compute_histogram_stats`` now also
returns a non-parametric Gaussian KDE curve sampled over the binning range;
these tests pin its shape semantics:

  - unimodal data → single peak, 200 points inside the bin range;
  - bimodal data (two overlapping gaussians) → two distinct local maxima;
  - degenerate input (< 3 samples, zero variance) → ``kde_curve`` is None,
    never a crash;
  - CL mode → curve spans the user-supplied custom range.

Run directly:  python test/backend/test_histogram_kde.py
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

from apps.analysis.services.data_services import compute_histogram_stats  # noqa: E402

PARAM = 'lkg_VCC_EN_float_3P6V'
METADATA = {
    'mins': {PARAM: '8.0'},
    'maxs': {PARAM: '14.3'},
    'units': {PARAM: 'uA'},
    'format': 'CTA8280F',
}
RNG = np.random.default_rng(42)


def _df(vals):
    return pd.DataFrame({PARAM: vals})


def _num_peaks(y):
    """Count strict local maxima (y[i] greater than both neighbours)."""
    return sum(1 for i in range(1, len(y) - 1) if y[i] > y[i - 1] and y[i] > y[i + 1])


def _xs(curve):
    return [p[0] for p in curve]


def test_unimodal_data_single_peak():
    vals = RNG.normal(11.0, 0.8, 500)
    r = compute_histogram_stats(_df(vals), METADATA, PARAM, None, range_type='RDL')
    curve = r['kde_curve']
    assert curve is not None
    assert len(curve) == 200, len(curve)
    # Curve spans the full visible X-axis: bin_centers extend one gap past
    # the binning range to the underflow/overflow bin centres, and the curve
    # must fill the axis edge to edge.  Density stays non-negative; the tails
    # (far from the data) may legitimately round to 0.0 at 6 decimals.
    xs = _xs(curve)
    assert min(xs) == r['bin_centers'][0], (min(xs), r['bin_centers'][0])
    assert max(xs) == r['bin_centers'][-1], (max(xs), r['bin_centers'][-1])
    assert all(p[1] >= 0 for p in curve)
    assert max(p[1] for p in curve) > 0
    # A single gaussian → exactly one local maximum.
    peaks = _num_peaks([p[1] for p in curve])
    assert peaks == 1, peaks
    print('unimodal: 200 points, 1 peak OK')


def test_bimodal_data_two_peaks():
    """Two well-separated gaussians must surface as two KDE peaks, which the
    single-mode normal curve can never represent."""
    vals = np.concatenate([
        RNG.normal(9.5, 0.35, 300),
        RNG.normal(12.0, 0.35, 300),
    ])
    r = compute_histogram_stats(_df(vals), METADATA, PARAM, None, range_type='RDL')
    curve = r['kde_curve']
    assert curve is not None
    peaks = _num_peaks([p[1] for p in curve])
    assert peaks == 2, peaks
    print('bimodal: 2 peaks OK')


def test_tight_data_still_yields_curve():
    """Tiny-span data (7 points, span ~0.007 << RDL bin width) still produce
    a curve: the evenly spaced grid would miss the data entirely, so the
    dense-grid fallback must kick in (regression: curve was all zeros after
    the backend merge dropped the front-end's std < binGap extra points)."""
    vals = [10.4480, 10.4495, 10.4510, 10.4519, 10.4530, 10.4545, 10.4553]
    r = compute_histogram_stats(_df(vals), METADATA, PARAM, None, range_type='RDL')
    curve = r['kde_curve']
    assert curve is not None
    # Dense grid adds ~60 extra points inside the data region.
    assert len(curve) >= 200, len(curve)
    assert all(p[1] >= 0 for p in curve)
    # Peak must sit inside the data span (dense sampling actually hit it).
    peak_x = max(curve, key=lambda p: p[1])[0]
    assert 10.44 < peak_x < 10.47, peak_x
    print('tight data: curve produced OK (peak at %.6f)' % peak_x)


def test_degenerate_inputs_return_none():
    # Zero variance (all identical values) → no curve, no crash.
    r = compute_histogram_stats(_df([10.45] * 50), METADATA, PARAM, None, range_type='RDL')
    assert r['kde_curve'] is None
    # Fewer than 3 samples → no curve, no crash.
    r = compute_histogram_stats(_df([10.45, 10.46]), METADATA, PARAM, None, range_type='RDL')
    assert r['kde_curve'] is None
    print('degenerate: kde_curve=None OK')


def test_kde_curves_split_by_outlier_inclusion():
    """「KDE含超限」数据源：``kde_curve`` 含超限 fail 峰（全量），
    ``filtered_kde_curve`` 剔除 IQR 异常值（主峰保真）。"""
    vals = np.concatenate([RNG.normal(11.0, 0.8, 500), [30.0] * 20])
    # DR 模式：X 轴覆盖数据范围，fail=30 落在可见轴内
    r = compute_histogram_stats(_df(vals), METADATA, PARAM, None, range_type='DR')
    assert r['outlier_info']['has_outliers'] is True

    full = r['kde_curve']
    filtered = r['filtered_kde_curve']
    assert full is not None and filtered is not None

    # 全量曲线在 fail=30 附近有密度峰
    tail_y = [y for x, y in full if 29.0 <= x <= 31.0]
    assert tail_y, 'full curve should sample the fail region'
    assert max(tail_y) > 0.001, max(tail_y)

    # 剔除曲线在 fail 区域为 0（超限数据被 IQR 判为异常值剔除）
    filt_tail = [y for x, y in filtered if 29.0 <= x <= 31.0]
    assert all(y == 0 for y in filt_tail)

    # 剔除曲线主峰高于全量：fail 归一化压低主峰（scipy silverman 非 IQR 鲁棒）
    assert max(p[1] for p in filtered) > max(p[1] for p in full), (
        max(p[1] for p in filtered), max(p[1] for p in full))
    print('kde/filtered split: fail peak %.4f, filtered main %.4f > full main %.4f OK'
          % (max(tail_y), max(p[1] for p in filtered), max(p[1] for p in full)))


def test_no_outliers_filtered_kde_none():
    """无异常值时 filtered_kde_curve 为 None（与 filtered_normal_curve 对称）。"""
    vals = [10.4480, 10.4495, 10.4510, 10.4519, 10.4530, 10.4545, 10.4553]
    r = compute_histogram_stats(_df(vals), METADATA, PARAM, None, range_type='RDL')
    assert r['outlier_info']['has_outliers'] is False
    assert r['kde_curve'] is not None
    assert r['filtered_kde_curve'] is None
    print('no outliers: filtered_kde_curve=None OK')


def test_cl_mode_curve_spans_custom_range():
    vals = RNG.normal(11.0, 0.8, 500)
    r = compute_histogram_stats(
        _df(vals), METADATA, PARAM, None,
        range_type='CL', custom_low=9.0, custom_high=13.0)
    curve = r['kde_curve']
    assert curve is not None
    xs = _xs(curve)
    # CL binning range [9.0, 13.0] plus one gap on each side (underflow /
    # overflow bin centres) — the curve must cover the full visible X-axis.
    assert min(xs) == r['bin_centers'][0], (min(xs), r['bin_centers'][0])
    assert max(xs) == r['bin_centers'][-1], (max(xs), r['bin_centers'][-1])
    print('CL: curve spans [%.4f, %.4f] OK' % (min(xs), max(xs)))


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
    print('\nAll histogram KDE tests passed')
