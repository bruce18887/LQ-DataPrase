"""NumPy-only Gaussian KDE — drop-in replacement for scipy.stats.gaussian_kde (1D).

The packaged app uses exactly four scipy.stats entry points (gaussian_kde
here + histogram, t.cdf + probplot in computations) yet bundles the whole
~91 MB scipy tree.  This module replaces the KDE ones with an equivalent
vectorised NumPy implementation.

Math mirrors scipy 1.17.1 ``gaussian_kde``:
  - bandwidth factor:  silverman ``(neff * (d+2) / 4) ** (-1 / (d+4))``,
    scott ``neff ** (-1 / (d+4))`` (unweighted: neff == n)
  - kernel covariance: ``np.cov(dataset, bias=False)`` (sample var, ddof=1)
  - pdf(x) = mean_k exp(-0.5 * ((x - x_k) / h)^2) / (h * sqrt(2 pi)),
    h = sqrt(variance) * factor

Call sites guard degenerate input (< 3 samples, zero ptp) and wrap in
try/except, mirroring the scipy behaviour for the remaining edge cases.
"""

import numpy as np

_SQRT_2PI = np.sqrt(2.0 * np.pi)

# 核求和的数据点上限：超过时均匀采样（KDE 是密度估计，相邻点高度相关，
# 均匀采样求和与全量几乎逐点一致——16384 点实测相对误差 <0.6%）。
# 带宽（neff/variance）保持全量口径，因此曲线形状不变——只是 68k 行文件
# histogram 的 KDE 从 ~186ms 降到 ~20ms（原实现 O(n×m) 广播生成
# 200×67760 矩阵 ≈ 108MB 分配 + exp）。
# 小数据（≤ 上限）完全不走采样路径，输出逐点一致（零变更）。
MAX_KDE_SAMPLES = 16384


class GaussianKDE:
    """One-dimensional Gaussian kernel density estimate.

    Only the 1D, unweighted subset of the scipy API that the app uses:
    ``GaussianKDE(data, bw_method='silverman')`` then ``kde(x)`` for a
    1-D sample grid.
    """

    def __init__(self, dataset, bw_method='silverman'):
        data = np.asarray(dataset, dtype=float).reshape(1, -1)
        self.d, self.n = data.shape
        if self.n < 1:
            raise ValueError('dataset must contain at least one sample')
        # 大样本保真采样：neff / variance 用全量口径（带宽不变），
        # 仅核求和使用均匀采样的数据子集。
        n_full = self.n
        # scipy: covariance = np.cov(dataset, rowvar=1, bias=False) (ddof=1)
        variance = float(np.var(data, ddof=1))
        if n_full > MAX_KDE_SAMPLES:
            idx = np.linspace(0, n_full - 1, MAX_KDE_SAMPLES).astype(int)
            data = data[:, idx]
        self.dataset = data
        self.neff = float(n_full)

        if bw_method == 'silverman':
            factor = (self.neff * (self.d + 2.0) / 4.0) ** (-1.0 / (self.d + 4.0))
        elif bw_method == 'scott':
            factor = self.neff ** (-1.0 / (self.d + 4.0))
        elif bw_method is None:
            factor = self.neff ** (-1.0 / (self.d + 4.0))
        elif np.isscalar(bw_method) and bw_method > 0:
            factor = float(bw_method)
        else:
            raise ValueError(f"unknown bw_method: {bw_method!r}")

        if not np.isfinite(variance) or variance <= 0:
            raise ValueError('dataset has zero variance')
        self.factor = factor
        self.covariance = variance * factor * factor

    def __call__(self, points):
        pts = np.asarray(points, dtype=float).reshape(-1)
        if pts.size == 0:
            return np.empty((0,), dtype=float)
        stdev = np.sqrt(self.covariance)
        data = self.dataset[0]
        diff = (pts[:, None] - data[None, :]) / stdev
        pdf = np.exp(-0.5 * diff * diff).mean(axis=1) / (stdev * _SQRT_2PI)
        return pdf
