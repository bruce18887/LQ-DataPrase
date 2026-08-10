"""Tests for numpy normal/Student-t helpers (replaces scipy.stats).

Golden fixtures generated with scipy 1.17.1 (fixed inputs); live
comparisons run when scipy is importable.  ``norm_probplot`` / ``t_cdf``
must stay within 1e-9 of scipy because the API rounds osm to 6 decimals
and r_squared to 4.

Run directly:  python test/backend/test_distributions.py
"""
import os
import sys

# test/backend/ → project root (for `import config` / `from apps...`)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

import numpy as np  # noqa: E402

from apps.analysis.services.statistics.distributions import (  # noqa: E402
    norm_ppf, norm_probplot, t_cdf,
)

# ---------------------------------------------------------------------------
# Golden fixtures (scipy 1.17.1)
# ---------------------------------------------------------------------------
PPF_AT_025 = -1.9599639845400536
PPF_AT_975 = 1.9599639845400536
PPF_AT_0013 = -3.0114537584997843
PPF_AT_FILLIBEN_ENDPOINT = 0.5449521356173603  # ppf(0.5 ** (1/2))

PROBPLOT_DATA = [9.2, 10.1, 10.4, 11.0, 11.3, 11.7, 12.0, 12.4, 12.9, 13.5, 14.2, 15.1]
PROBPLOT_OSM = [-1.588154642966, -1.098149754686, -0.782559268059, -0.530691128617,
                -0.308923525477, -0.101534002506, 0.101534002506, 0.308923525477,
                0.530691128617, 0.782559268059, 1.098149754686, 1.588154642966]
PROBPLOT_OSR = PROBPLOT_DATA[:]
PROBPLOT_R = 0.9968258689933353

T_GRID = [-10.0, -3.0, -1.0, -0.3, 0.0, 0.3, 1.0, 3.0, 10.0]
T_CDF_DF7 = [1.0697101e-05, 0.009971063066, 0.17530833141, 0.386445025201, 0.5,
             0.613554974799, 0.82469166859, 0.990028936934, 0.999989302899]
T_CDF_DF100 = [0.0, 0.001703957672, 0.159862077892, 0.38239994015, 0.5,
               0.61760005985, 0.840137922108, 0.998296042328, 1.0]


def test_norm_ppf_golden():
    assert abs(norm_ppf(0.025) - PPF_AT_025) < 1e-12
    assert abs(norm_ppf(0.975) - PPF_AT_975) < 1e-12
    assert abs(norm_ppf(0.0013) - PPF_AT_0013) < 1e-12
    assert abs(norm_ppf(0.5 ** 0.5) - PPF_AT_FILLIBEN_ENDPOINT) < 1e-12
    # vectorised
    out = norm_ppf(np.array([0.025, 0.975]))
    assert out.shape == (2,) and abs(out[0] - PPF_AT_025) < 1e-12


def test_norm_ppf_symmetry_and_bounds():
    q = np.linspace(1e-9, 1 - 1e-9, 501)
    # Acklam's algorithm uses separate p < 0.5 / p > 0.5 branches, so the
    # tails match only to ~1e-8; mid-range is symmetric to ~1e-12.
    assert np.max(np.abs(norm_ppf(q) - (-norm_ppf(q[::-1])))) < 1e-8
    mid = np.linspace(1e-6, 1 - 1e-6, 501)
    assert np.max(np.abs(norm_ppf(mid) - (-norm_ppf(mid[::-1])))) < 1e-10
    assert np.all(np.diff(norm_ppf(q)) > 0)  # strictly increasing


def test_norm_probplot_golden():
    (osm, osr), (slope, intercept, r) = norm_probplot(np.asarray(PROBPLOT_DATA))
    assert np.max(np.abs(osm - np.asarray(PROBPLOT_OSM))) < 1e-9
    assert np.array_equal(osr, np.asarray(PROBPLOT_OSR))
    assert abs(r - PROBPLOT_R) < 1e-9
    assert abs(slope * float(osm.mean()) + intercept - float(osr.mean())) < 1e-9
    # r**2 is the API value used by the normality check
    assert round(r * r, 4) == 0.9937


def test_norm_probplot_normal_data_r_squared():
    rng = np.random.default_rng(5)
    data = rng.normal(0, 1, 500)
    (osm, osr), (_, _, r) = norm_probplot(data)
    assert r * r > 0.99
    # osm is strictly increasing (Filliben medians in (0, 1))
    assert np.all(np.diff(osm) > 0)


def test_t_cdf_golden():
    assert np.max(np.abs(t_cdf(np.asarray(T_GRID), 7) - np.asarray(T_CDF_DF7))) < 1e-9
    assert np.max(np.abs(t_cdf(np.asarray(T_GRID), 100) - np.asarray(T_CDF_DF100))) < 1e-9


def test_t_cdf_edges_and_extremes():
    df = 7
    assert abs(float(t_cdf(0.0, df)) - 0.5) < 1e-12
    assert float(t_cdf(np.inf, df)) == 1.0
    assert float(t_cdf(-np.inf, df)) == 0.0
    assert np.isnan(float(t_cdf(np.nan, df)))
    # monotone in t for a fixed df
    t = np.linspace(-8, 8, 65)
    cdf = t_cdf(t, df)
    assert np.all(np.diff(cdf) > 0)
    # large df approaches the standard normal CDF (within 1e-3 at df=10000)
    assert abs(float(t_cdf(1.96, 10000)) - 0.975) < 1e-3
    assert abs(float(t_cdf(-1.96, 10000)) - 0.025) < 1e-3


def test_correlation_p_value_relation():
    """p = 2*(1 - t_cdf(|t|, df)) must equal I_{df/(df+t^2)}(df/2, 1/2)."""
    from apps.analysis.services.statistics.distributions import _betainc
    t = np.array([0.3, 1.0, 3.0, 7.5])
    df = 7
    p_mine = 2 * (1 - t_cdf(np.abs(t), df))
    p_beta = _betainc(df / 2, 0.5, df / (df + t * t))
    assert np.max(np.abs(p_mine - p_beta)) < 1e-12


def test_live_comparison_with_scipy():
    try:
        from scipy import stats as sp_stats
    except ImportError:
        print('  (scipy not installed — skipping live comparison)')
        return
    # probplot
    rng = np.random.default_rng(11)
    for n in (3, 50, 2000):
        data = rng.normal(2, 0.8, n)
        pp = sp_stats.probplot(data, dist='norm', fit=True)
        mine = norm_probplot(data)
        assert np.max(np.abs(mine[0][0] - pp[0][0])) < 1e-9, f'osm n={n}'
        assert np.max(np.abs(mine[0][1] - pp[0][1])) < 1e-9, f'osr n={n}'
        assert abs(mine[1][2] - pp[1][2]) < 1e-9, f'r n={n}'
    # t.cdf over a wide df range
    t = np.array([-30.0, -3.0, -1.0, -0.3, 0.0, 0.3, 1.0, 3.0, 30.0])
    for df in (1, 3, 10, 100, 5000, 10000):
        assert np.max(np.abs(t_cdf(t, df) - sp_stats.t.cdf(t, df))) < 1e-9, f'df={df}'
    print('  live scipy comparison OK')


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
    print('\nAll distribution tests passed')
