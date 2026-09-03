"""CPK table computation."""

from apps.analysis.services.statistics import (
    compute_cpk,
    compute_range_statistics,
    get_1d_from,
    filter_finite,
)


def compute_cpk_table_data(df, metadata, params):
    """Compute CPK table for the given parameters.

    Returns ``{'results': {param: {...}}, 'count': N}``, matching the
    original response shape of ``AnalysisViewSet.cpk``.
    """
    results = {}
    for param in params:
        data_series = filter_finite(get_1d_from(df, param))
        if len(data_series) == 0:
            continue

        stats = compute_range_statistics(data_series, metadata, param)
        cpk_result = compute_cpk(
            stats['mean'], stats['std'], stats['rdl'][0], stats['rdl'][1]
        )
        results[param] = {
            'mean': round(stats['mean'], 6),
            'std': round(stats['std'], 6),
            'cp': round(cpk_result['cp'], 4) if cpk_result['cp'] is not None else None,
            'cpk': round(cpk_result['cpk'], 4),
            'cp_level': cpk_result['cp_level'],
            'cpk_level': cpk_result['cpk_level'],
            'cp_color': cpk_result['cp_color'],
            'cpk_color': cpk_result['cpk_color'],
        }
    return {'results': results, 'count': len(results)}
