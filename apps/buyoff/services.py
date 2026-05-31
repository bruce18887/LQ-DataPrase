"""Buyoff analysis service: statistics computation for buyoff reports."""
from apps.analysis.services.statistics import get_1d_from


def compute_buyoff_stats(df, metadata, param) -> dict:
    """Compute full buyoff statistics for a parameter.

    Returns dict with: lower_limit, upper_limit, min, max, range,
                       mean, std, mean_minus_6std, mean_minus_3std,
                       mean_plus_3std, mean_plus_6std, ca, cp, cpk.
    """
    data = get_1d_from(df, param).dropna()
    result = {}
    if len(data) == 0:
        return result

    mean_v = float(data.mean())
    std_v = float(data.std(ddof=0)) if len(data) > 1 else 0.0
    min_v = float(data.min())
    max_v = float(data.max())

    try:
        lower = float(metadata['mins'].get(param, 0))
    except (ValueError, TypeError, KeyError):
        lower = 0.0
    try:
        upper = float(metadata['maxs'].get(param, 0))
    except (ValueError, TypeError, KeyError):
        upper = 0.0

    tol = upper - lower
    ca = abs(mean_v - (upper + lower) / 2) / (tol / 2) if tol != 0 else 0.0
    cp = tol / (6 * std_v) if std_v > 0 and tol > 0 else 0.0
    cpu = (upper - mean_v) / (3 * std_v) if std_v > 0 else 0.0
    cpl = (mean_v - lower) / (3 * std_v) if std_v > 0 else 0.0
    cpk = min(cpu, cpl)

    return {
        'lower_limit': lower, 'upper_limit': upper,
        'min': min_v, 'max': max_v, 'range': max_v - min_v,
        'mean': mean_v, 'std': std_v,
        'mean_minus_6std': mean_v - 6 * std_v,
        'mean_minus_3std': mean_v - 3 * std_v,
        'mean_plus_3std': mean_v + 3 * std_v,
        'mean_plus_6std': mean_v + 6 * std_v,
        'ca': ca, 'cp': cp, 'cpk': cpk,
    }
