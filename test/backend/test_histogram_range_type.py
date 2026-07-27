"""Unit tests for histogram binning driven by ``range_type``.

Reproduces the bug from ``test/bar1.png``: a tight distribution (data span
~0.007) sitting inside wide spec limits (8.0 ~ 14.3).  Before the fix the
histogram always binned over the RowDataLimit range, collapsing all data into
a single bin and bunching the 3-sigma / limit lines together.  After the fix,
selecting ``S3`` re-bins over the ±3σ window so the data spreads across bins.

Run directly:  python test/test_histogram_range_type.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

import pandas as pd  # noqa: E402

from apps.analysis.services.data_services import compute_histogram_stats  # noqa: E402

PARAM = 'lkg_VCC_EN_float_3P6V'

# 7 samples clustered tightly around 10.45 (mirrors the screenshot data).
DATA = [10.4480, 10.4495, 10.4510, 10.4519, 10.4530, 10.4545, 10.4553]
METADATA = {
    'mins': {PARAM: '8.0'},
    'maxs': {PARAM: '14.3'},
    'units': {PARAM: 'uA'},
    'format': 'CTA8280F',
}


def _df():
    return pd.DataFrame({PARAM: DATA})


def _nonzero_normal_bins(result):
    """Count populated bins excluding the underflow (first) / overflow (last)."""
    pcts = result['bin_percentages']
    return sum(1 for p in pcts[1:-1] if p > 0)


def test_rdl_collapses_into_few_bins():
    r = compute_histogram_stats(_df(), METADATA, PARAM, None, range_type='RDL')
    centers = r['bin_centers']
    # RDL binning spans roughly the spec range (with under/overflow padding).
    assert centers[0] < 9.0, centers[0]
    assert centers[-1] > 13.0, centers[-1]
    # Tight data collapses into a single normal bin under the wide RDL range.
    assert _nonzero_normal_bins(r) <= 2, r['bin_percentages']
    print('RDL: span [%.4f, %.4f], non-zero bins=%d OK'
          % (centers[0], centers[-1], _nonzero_normal_bins(r)))


def test_s3_zooms_and_spreads_data():
    r = compute_histogram_stats(_df(), METADATA, PARAM, None, range_type='S3')
    centers = r['bin_centers']
    # X-axis must now hug the 3-sigma window, not the wide spec range.
    assert centers[0] > 10.0, centers[0]
    assert centers[-1] < 11.0, centers[-1]
    # Binning should reach close to the reported sigma3 bounds.
    assert r['sigma3_min'] >= centers[0]
    assert r['sigma3_max'] <= centers[-1]
    # Data now spreads across multiple bins instead of collapsing into one.
    assert _nonzero_normal_bins(r) >= 3, r['bin_percentages']
    # CPK stays anchored to spec limits regardless of range_type.
    assert r['lower_limit'] == 8.0 and r['upper_limit'] == 14.3
    print('S3: span [%.4f, %.4f], non-zero bins=%d OK'
          % (centers[0], centers[-1], _nonzero_normal_bins(r)))


def test_custom_limit_overrides_binning():
    r = compute_histogram_stats(
        _df(), METADATA, PARAM, None,
        range_type='CL', custom_low=10.40, custom_high=10.50)
    centers = r['bin_centers']
    assert centers[0] < 10.45 < centers[-1]
    assert centers[0] > 10.30 and centers[-1] < 10.60, (centers[0], centers[-1])
    print('CL: span [%.4f, %.4f] OK' % (centers[0], centers[-1]))


def test_zero_std_does_not_crash():
    df = pd.DataFrame({PARAM: [10.45, 10.45, 10.45]})
    r = compute_histogram_stats(df, METADATA, PARAM, None, range_type='S3')
    centers = r['bin_centers']
    assert centers[-1] > centers[0], centers
    print('zero-std S3: span [%.4f, %.4f] OK' % (centers[0], centers[-1]))


def test_outlier_values_are_included():
    """Histogram should include the actual outlier values for UI tooltips."""
    df = pd.DataFrame({PARAM: DATA + [20.0, -5.0]})
    r = compute_histogram_stats(df, METADATA, PARAM, None, range_type='RDL')
    info = r['outlier_info']
    assert info['has_outliers'] is True
    assert 'outlier_values' in info
    assert 20.0 in info['outlier_values']
    assert -5.0 in info['outlier_values']
    print('outlier_values included: %s' % info['outlier_values'])


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
    print('\nAll histogram range_type tests passed')
