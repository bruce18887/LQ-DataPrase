"""Unit tests for tiny-percentage preservation in statistics responses.

Regression for the bug: a bin / fail item with 1 count out of 50000 rows
(0.002%) used to be rounded to 0.0 by ``round(x * 100, 2)``, so the
front-end histogram drew a zero-height bar — the fail bin was invisible.

The fix keeps ≥6 decimal places on every percentage so values down to
~1/100000 (0.001%) survive; zero counts still yield 0.0.

Run directly:  python test/backend/test_tiny_percentage.py
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
from apps.analysis.services.statistics.limits import (  # noqa: E402
    calculate_fail_bin_statistics,
    calculate_fail_test_item_statistics,
    compute_pass_yield,
)
from apps.analysis.services.statistics.trends import compute_bin_trend  # noqa: E402

PARAM = 'KELVIN_VIN'
METADATA = {
    'mins': {PARAM: '0.0'},
    'maxs': {PARAM: '2.0'},
    'units': {PARAM: 'V'},
    'format': 'ETS88',  # bin column name = 'Bin'
}


def _hist_df(n_rows):
    """n_rows in-spec values + 1 out-of-spec (2.5 > max 2.0) → overflow bin."""
    vals = np.linspace(0.5, 1.99, n_rows)
    return pd.DataFrame({PARAM: np.append(vals, 2.5)})


def _test_histogram_tiny_bin(n_rows):
    r = compute_histogram_stats(_hist_df(n_rows), METADATA, PARAM, None, range_type='RDL')
    pcts = r['bin_percentages']
    expected = 100.0 / (n_rows + 1)  # 1 fail / (n + 1) rows

    min_nonzero = min(v for v in pcts if v > 0)
    assert min_nonzero > 0, 'tiny percentage must not round to 0.0'
    assert min_nonzero == np.round(expected, 6), (min_nonzero, expected)
    # Only the single-fail (overflow) bin is tiny; the main distribution
    # bins each hold thousands of rows.
    assert sum(1 for v in pcts if 0 < v < 0.005) == 1

    counts = r['bin_counts']
    assert sum(counts) == n_rows + 1, sum(counts)
    assert 1 in counts, 'overflow bin must carry count 1'
    assert max(counts) > n_rows / 50, max(counts)
    print('histogram %d rows: tiny bin %.6f%% (count 1) preserved OK' % (n_rows, min_nonzero))


def test_histogram_tiny_bin_1_in_50000():
    _test_histogram_tiny_bin(50000)


def test_histogram_tiny_bin_1_in_100000():
    _test_histogram_tiny_bin(100000)


def _test_fail_bin_statistics(n_rows):
    df = pd.DataFrame({'Bin': [1] * n_rows + [99], PARAM: [1.0] * (n_rows + 1)})
    stats = calculate_fail_bin_statistics(df, METADATA)
    assert stats[99]['count'] == 1
    expected = 100.0 / (n_rows + 1)
    assert stats[99]['percentage'] == np.round(expected, 6), stats[99]
    print('fail bin statistics: bin 99 percentage %.6f%% preserved OK' % stats[99]['percentage'])


def test_fail_bin_statistics_1_in_50000():
    _test_fail_bin_statistics(50000)


def test_fail_bin_statistics_1_in_100000():
    _test_fail_bin_statistics(100000)


def _test_fail_test_item_share(n_rows):
    """P_A fails on every row, P_B fails once → P_B share must stay > 0."""
    df = pd.DataFrame({
        'Bin': [99] * (n_rows + 1),            # all rows fail-eligible
        'P_A': [3.0] * (n_rows + 1),           # over limit 2.0 → n+1 fails
        'P_B': [1.0] * n_rows + [3.0],         # 1 fail
    })
    meta = {'format': 'ETS88',
            'mins': {'P_A': '0.0', 'P_B': '0.0'},
            'maxs': {'P_A': '2.0', 'P_B': '2.0'}}
    stats = calculate_fail_test_item_statistics(df, meta)
    expected = 100.0 / (n_rows + 2)  # 1 / (P_A n+1 + P_B 1)
    assert stats['P_B']['fail_count'] == 1
    assert stats['P_B']['percentage'] == np.round(expected, 6), stats['P_B']
    print('fail test item: P_B share %.6f%% preserved OK' % stats['P_B']['percentage'])


def test_fail_test_item_tiny_share_1_in_50000():
    _test_fail_test_item_share(50000)


def test_fail_test_item_tiny_share_1_in_100000():
    _test_fail_test_item_share(100000)


def test_yield_rounding_keeps_tiny_fail():
    """yield 99.998% must not round up to a misleading 100.0 (0.002% fail
    swallowed). Old code: round(99.998, 2) → 100.0."""
    y = compute_pass_yield({1: {'count': 49999, 'percentage': 99.998},
                            99: {'count': 1, 'percentage': 0.002}}, 50000)
    assert y['yield_pct'] == 99.998, y
    assert y['yield_pct'] < 100.0, y
    print('yield: 49999/50000 → %.6f%% (not 100.0) OK' % y['yield_pct'])


def _test_bin_trend(n_rows):
    df = pd.DataFrame({'Bin': [1] * n_rows + [99], PARAM: [1.0] * (n_rows + 1)})
    r = compute_bin_trend([{'df': df, 'metadata': METADATA, 'file_id': 1,
                            'filename': 'f.csv', 'timestamp': ''}])
    pcts = r['trend_data'][0]['bin_percentages']
    expected = 100.0 / (n_rows + 1)
    assert pcts[99] == np.round(expected, 6), pcts
    print('bin trend: bin 99 percentage %.6f%% preserved OK' % pcts[99])


def test_bin_trend_1_in_50000():
    _test_bin_trend(50000)


def test_bin_trend_1_in_100000():
    _test_bin_trend(100000)


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
    print('\nAll tiny-percentage tests passed')
