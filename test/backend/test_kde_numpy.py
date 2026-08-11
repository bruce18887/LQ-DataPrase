"""Tests for the numpy GaussianKDE (replaces scipy.stats.gaussian_kde).

Golden fixtures below were generated with scipy 1.17.1
(``gaussian_kde(bw_method='silverman')``, fixed seed) so the test pins the
packaged app's behaviour without requiring scipy.  A live comparison
against scipy runs additionally when scipy happens to be importable.

Run directly:  python test/backend/test_kde_numpy.py
"""
import os
import sys

# test/backend/ → project root (for `import config` / `from apps...`)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')

import django  # noqa: E402

django.setup()

import numpy as np  # noqa: E402

from apps.analysis.services.statistics.kde import (  # noqa: E402
    GaussianKDE, MAX_KDE_SAMPLES,
)

# ---------------------------------------------------------------------------
# Golden fixtures (scipy 1.17.1, seed 1234)
# ---------------------------------------------------------------------------
KDE_DATA = [9.273477430826288, 12.108969853806398, 13.259515202990434,
            12.25945262906161, 13.468364615249664, 16.95226867825675,
            9.486000286870517, 13.607304056897961, 9.16756972255946,
            12.584365788469555, 11.128845694215741, 14.250390226370573,
            10.537523670905461, 12.883138438331212, 9.849255680165813,
            8.329463680796218, 12.739047714985931, 14.946591843908033,
            12.884228065600384, 10.296318150617452, 12.45618741866663,
            13.304196990816163, 14.025162445537317, 10.032401627595188,
            13.183674971934423, 12.59735226584662, 11.944894358880862,
            12.022408684501858, 10.845275051518309, 10.94509555320456,
            14.263064168165482, 12.440025471705047, 11.181477340896668,
            7.763957648892974, 10.509841584081023, 11.140634483272336,
            9.818680411083946, 9.73844167753505, 13.404187393444497,
            11.57973447490798]
KDE_GRID = np.linspace(8.0, 16.0, 21)
KDE_EXPECT = [0.040695693654, 0.056675538693, 0.075755819649, 0.096476211583,
              0.116211528226, 0.132421986009, 0.144138936302, 0.152517734512,
              0.159987367551, 0.168394836347, 0.177210364864, 0.183140042293,
              0.181764654999, 0.170205456003, 0.148868438818, 0.121161408751,
              0.091775524995, 0.064929195668, 0.043421970635, 0.028410540102,
              0.019497853126]


def test_kde_matches_scipy_golden():
    pdf = GaussianKDE(np.asarray(KDE_DATA, dtype=float), bw_method='silverman')(KDE_GRID)
    assert pdf.shape == (21,)
    assert np.max(np.abs(pdf - np.asarray(KDE_EXPECT))) < 1e-9


def test_kde_unimodal_single_peak():
    data = np.random.default_rng(7).normal(10, 2, 200)
    x = np.linspace(2, 18, 201)
    pdf = GaussianKDE(data, bw_method='silverman')(x)
    # peak sits at the sample mean (within a couple of grid steps)
    mean = float(data.mean())
    assert abs(x[np.argmax(pdf)] - mean) < 3 * (x[1] - x[0])
    peaks = sum(1 for i in range(1, len(pdf) - 1)
                if pdf[i] > pdf[i - 1] and pdf[i] > pdf[i + 1])
    assert peaks == 1


def test_kde_bimodal_two_peaks():
    rng = np.random.default_rng(42)
    data = np.concatenate([rng.normal(-3, 0.5, 300), rng.normal(3, 0.5, 300)])
    pdf = GaussianKDE(data, bw_method='silverman')(np.linspace(-6, 6, 401))
    peaks = sum(1 for i in range(1, len(pdf) - 1)
                if pdf[i] > pdf[i - 1] and pdf[i] > pdf[i + 1])
    assert peaks == 2


def test_kde_scott_and_scalar_bw():
    data = np.random.default_rng(3).normal(0, 1, 100)
    x = np.linspace(-4, 4, 50)
    for bw in ('scott', 0.7):
        pdf = GaussianKDE(data, bw_method=bw)(x)
        assert np.all(np.isfinite(pdf)) and pdf.sum() > 0


def test_kde_raises_on_degenerate():
    for bad in (np.array([1.0, 1.0, 1.0]), np.array([])):
        try:
            GaussianKDE(bad, bw_method='silverman')
        except ValueError:
            pass
        else:
            raise AssertionError('expected ValueError for degenerate input')


def _full_kde_pdf(dataset, grid):
    """与 GaussianKDE 同公式的全量计算（带宽用全量 n/variance 口径）。"""
    data = np.asarray(dataset, dtype=float)
    n = data.size
    variance = float(np.var(data, ddof=1))
    factor = (n * (1 + 2.0) / 4.0) ** (-1.0 / (1 + 4.0))
    stdev = np.sqrt(variance) * factor
    diff = (grid[:, None] - data[None, :]) / stdev
    return np.exp(-0.5 * diff * diff).mean(axis=1) / (stdev * np.sqrt(2.0 * np.pi))


def test_kde_large_sample_fidelity():
    """68k 点：内部采样后的输出与全量计算相对误差 < 5%（保形钉）。

    大样本优化只对核求和使用均匀采样数据子集；带宽（neff/variance）
    保持全量口径，曲线形状必须几乎逐点一致。窄分布（σ=0.02）是最严苛
    场景，实测 16384 点采样相对误差 ~2.5%——叠加在直方图上的密度曲线
    纵轴 2.5% 偏差肉眼不可辨；真实数据（σ≈0.05）实测 <0.6%。
    """
    vals = np.random.default_rng(123).normal(-0.48, 0.02, 68_000)
    grid = np.linspace(-0.7, -0.3, 200)
    sampled = GaussianKDE(vals, bw_method='silverman')(grid)
    full = _full_kde_pdf(vals, grid)
    rel_err = float(np.max(np.abs(sampled - full)) / np.max(full))
    assert rel_err < 0.05, f'relative error {rel_err:.4%} >= 5%'


def test_kde_at_threshold_unchanged():
    """n == MAX_KDE_SAMPLES（不触发采样）→ 与全量逐点一致（零变更钉）。"""
    vals = np.random.default_rng(321).normal(10, 2, MAX_KDE_SAMPLES)
    grid = np.linspace(2, 18, 100)
    got = GaussianKDE(vals, bw_method='silverman')(grid)
    expected = _full_kde_pdf(vals, grid)
    assert np.allclose(got, expected, atol=1e-12)


def test_kde_large_bimodal_peaks_preserved():
    """6 万点双峰：采样后仍 2 峰且峰位不变（轮廓保留钉）。"""
    rng = np.random.default_rng(7)
    data = np.concatenate([rng.normal(-3, 0.5, 30_000), rng.normal(3, 0.5, 30_000)])
    x = np.linspace(-6, 6, 401)
    pdf = GaussianKDE(data, bw_method='silverman')(x)
    peaks = [i for i in range(1, len(pdf) - 1)
             if pdf[i] > pdf[i - 1] and pdf[i] > pdf[i + 1]]
    assert len(peaks) == 2
    assert abs(x[peaks[0]] + 3) < 0.3 and abs(x[peaks[1]] - 3) < 0.3


def test_kde_live_comparison_with_scipy():
    try:
        from scipy.stats import gaussian_kde
    except ImportError:
        print('  (scipy not installed — skipping live comparison)')
        return
    rng = np.random.default_rng(99)
    for n in (5, 100, 3000):
        data = rng.normal(10, 2.5, n)
        x = np.linspace(2, 18, 200)
        mine = GaussianKDE(data, bw_method='silverman')(x)
        theirs = gaussian_kde(data, bw_method='silverman')(x)
        assert np.max(np.abs(mine - theirs)) < 1e-9, f'n={n}'
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
    print('\nAll KDE numpy tests passed')
