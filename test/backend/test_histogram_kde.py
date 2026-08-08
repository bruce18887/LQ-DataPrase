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
    # Curve spans the RDL binning range; density is non-negative and the
    # tails (far from the data) may legitimately round to 0.0 at 6 decimals.
    xs = _xs(curve)
    assert min(xs) >= 8.0 and max(xs) <= 14.3, (min(xs), max(xs))
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
    """Small-but-valid samples (7 points, span ~0.007) still produce a curve."""
    vals = [10.4480, 10.4495, 10.4510, 10.4519, 10.4530, 10.4545, 10.4553]
    r = compute_histogram_stats(_df(vals), METADATA, PARAM, None, range_type='RDL')
    curve = r['kde_curve']
    assert curve is not None
    assert len(curve) == 200
    assert all(p[1] >= 0 for p in curve)
    assert max(p[1] for p in curve) > 0
    print('tight data: curve produced OK')


def test_degenerate_inputs_return_none():
    # Zero variance (all identical values) → no curve, no crash.
    r = compute_histogram_stats(_df([10.45] * 50), METADATA, PARAM, None, range_type='RDL')
    assert r['kde_curve'] is None
    # Fewer than 3 samples → no curve, no crash.
    r = compute_histogram_stats(_df([10.45, 10.46]), METADATA, PARAM, None, range_type='RDL')
    assert r['kde_curve'] is None
    print('degenerate: kde_curve=None OK')


def test_cl_mode_curve_spans_custom_range():
    vals = RNG.normal(11.0, 0.8, 500)
    r = compute_histogram_stats(
        _df(vals), METADATA, PARAM, None,
        range_type='CL', custom_low=9.0, custom_high=13.0)
    curve = r['kde_curve']
    assert curve is not None
    xs = _xs(curve)
    assert min(xs) == 9.0 and max(xs) == 13.0, (min(xs), max(xs))
    print('CL: curve spans [9.0, 13.0] OK')


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
