"""Normal / Student-t distribution helpers — standard library + NumPy only.

Replaces the remaining scipy.stats entry points used by the packaged app
(see kde.py for the KDE side of the same change):

  - ``norm.ppf``     -> ``norm_ppf`` (statistics.NormalDist.inv_cdf,
                        Acklam's algorithm, ~16 decimal digits)
  - ``probplot``     -> ``norm_probplot`` (Filliben order-statistic medians
                        + least-squares fit, mirroring scipy 1.17.1)
  - ``t.cdf``        -> ``t_cdf`` (regularised incomplete beta, series /
                        Lentz continued fraction)

``t.cdf`` in scipy is ``scipy.special.stdtr`` — the same incomplete-beta
relation implemented here; golden fixtures pin the equivalence.
"""

import math
import statistics

import numpy as np

_TINY = 1e-300
_CF_EPS = 1e-12
_CF_MAXIT = 2000
_SERIES_EPS = 1e-13
_SERIES_MAXIT = 2000


# ---------------------------------------------------------------------------
# Normal distribution
# ---------------------------------------------------------------------------

def norm_ppf(q):
    """Quantile function of the standard normal distribution (vectorised)."""
    arr = np.asarray(q, dtype=float)
    flat = arr.reshape(-1)
    if flat.size == 0:
        return arr.copy()
    inv = statistics.NormalDist().inv_cdf
    out = np.array([inv(float(p)) for p in flat], dtype=float)
    return out.reshape(arr.shape)


def _filliben_medians(n):
    """Filliben's approximation of uniform order-statistic medians.

    Port of scipy's ``_calc_uniform_order_statistic_medians``
    (scipy/stats/_morestats.py) — used unchanged by scipy's probplot.
    """
    v = np.empty(n, dtype=np.float64)
    v[-1] = 0.5 ** (1.0 / n)
    v[0] = 1 - v[-1]
    i = np.arange(2, n)
    v[1:-1] = (i - 0.3175) / (n + 0.365)
    return v


def norm_probplot(x):
    """Normal probability plot, mirroring ``scipy.stats.probplot(x, dist='norm', fit=True)``.

    Returns the same nested structure as scipy: ``((osm, osr),
    (slope, intercept, r))`` — theoretical quantiles, sorted observed
    values, least-squares fit and the Pearson correlation ``r`` (``r**2``
    is the R^2 used by the normality check).
    """
    values = np.asarray(x, dtype=float)
    if values.size == 0:
        return ((values, values), (np.nan, np.nan, 0.0))
    n = values.size
    osm = norm_ppf(_filliben_medians(n))
    osr = np.sort(values)

    # Least-squares fit (equivalent to scipy's linregress on (osm, osr)).
    x_mean = osm.mean()
    y_mean = osr.mean()
    sxx = float(np.sum((osm - x_mean) ** 2))
    if sxx == 0:
        return ((osm, osr), (np.nan, np.nan, np.nan))
    sxy = float(np.sum((osm - x_mean) * (osr - y_mean)))
    slope = sxy / sxx
    intercept = y_mean - slope * x_mean
    syy = float(np.sum((osr - y_mean) ** 2))
    r = sxy / np.sqrt(sxx * syy) if syy > 0 else np.nan
    return ((osm, osr), (slope, intercept, r))


# ---------------------------------------------------------------------------
# Student-t distribution (via the regularised incomplete beta function)
# ---------------------------------------------------------------------------

def _betainc(a, b, x):
    """Regularised incomplete beta I_x(a, b) (vectorised over ``x``).

    Branch routing keeps every case well-conditioned for the app's shape
    (b = 1/2, arbitrary a = df/2):

      - x <= 0.5:            power series (term ratio -> x <= 0.5, geometric)
      - x > 0.5 and x below
        the swap threshold:  Lentz continued fraction (NR betacf, no swap —
        converges in ~15 terms for large a near x ~ 1)
      - x above threshold:   I_x(a,b) = 1 - I_{1-x}(b, a) power series, whose
        argument <= (b+1)/(a+b+2) makes the first terms bounded (~1) and
        the tail geometric at y -> 0.

    The series is the Pfaff-transformed hypergeometric form
    ``x^a (1-x)^b / (a B(a,b)) * _2F_1(1, a+b; a+1; x)`` (A&S 26.5.4) with
    term ratio ``x * (a+b+n-1) / (a+n)`` — verified bit-for-bit against
    scipy.special.betainc on the parameter ranges used here.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    x = np.asarray(x, dtype=float)
    if x.size and np.any((x < 0) | (x > 1)):
        raise ValueError('x must lie in [0, 1]')

    swap = x > (a + 1.0) / (a + b + 2.0)
    aa = np.where(swap, b, a)
    bb = np.where(swap, a, b)
    xx = np.where(swap, 1.0 - x, x)

    # math.lgamma is correctly rounded; arrays here are small (<= a few k cells).
    _lgamma = np.vectorize(math.lgamma, otypes=[float])
    log_beta = _lgamma(aa) + _lgamma(bb) - _lgamma(aa + bb)
    bt = np.exp(aa * np.log(np.maximum(xx, _TINY)) + bb * np.log1p(-xx)
                - np.log(aa) - log_beta)

    # Series for the swapped branch (small argument) and for x <= 0.5;
    # continued fraction for the no-swap upper half (large a, x -> 1).
    use_series = swap | (xx <= 0.5)
    result = np.where(use_series, _beta_series(bt, aa, bb, xx),
                      _betacf(aa, bb, xx))
    # I_x(a, b) = bt * series  (series)  |  bt * cf  (CF)
    # (bt already carries the 1/a factor and log B(a, b))
    result = bt * result
    return np.where(swap, 1.0 - result, result)


def _beta_series(bt, a, b, x):
    """Power series of I_x(a, b) — _2F_1(1, a+b; a+1; x) terms (A&S 26.5.4)."""
    apb = a + b
    s = np.ones_like(x)
    t = np.ones_like(x)
    active = np.ones_like(x, dtype=bool)
    for n in np.arange(1, _SERIES_MAXIT + 1):
        t = t * x * (apb + n - 1.0) / (a + n)
        s = np.where(active, s + t, s)
        active &= np.abs(t / s) > _SERIES_EPS
        if not active.any():
            break
    return np.where(active, np.nan, s)


def _betacf(a, b, x):
    """Lentz continued fraction for I_x(a, b) / bt (NR betacf)."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = np.ones_like(x)
    d = 1.0 - qab * x / qap
    d = np.where(np.abs(d) < _TINY, _TINY, d)
    d = 1.0 / d
    h = d
    converged = np.zeros_like(x, dtype=bool)
    for m in np.arange(1, _CF_MAXIT + 1):
        m2 = 2.0 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = np.where(np.abs(d) < _TINY, _TINY, d)
        c = 1.0 + aa / c
        c = np.where(np.abs(c) < _TINY, _TINY, c)
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = np.where(np.abs(d) < _TINY, _TINY, d)
        c = 1.0 + aa / c
        c = np.where(np.abs(c) < _TINY, _TINY, c)
        d = 1.0 / d
        delta = d * c
        h *= delta
        newly = ~converged & (np.abs(delta - 1.0) < _CF_EPS)
        converged |= newly
        if converged.all():
            break
    return np.where(converged, h, np.nan)


def t_cdf(t, df):
    """CDF of Student's t with ``df`` degrees of freedom (scipy stdtr semantics).

    P(T <= t) = 1 - 1/2 * I_x(df/2, 1/2)  for t >= 0,
    P(T <= t) = 1/2 * I_x(df/2, 1/2)      for t <  0,
    with x = df / (df + t^2).
    """
    t = np.asarray(t, dtype=float)
    df = float(df)
    if not np.isfinite(df) or df <= 0:
        raise ValueError('df must be a positive finite number')
    with np.errstate(divide='ignore', invalid='ignore'):
        x = df / (df + t * t)
        half_i = 0.5 * _betainc(0.5 * df, 0.5, x)
    return np.where(t >= 0, 1.0 - half_i, half_i)
