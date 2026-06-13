"""CPK table computation."""

from apps.analysis.services.statistics import (
    compute_cpk,
    compute_range_statistics,
    get_1d_from,
)


def compute_cpk_table_data(df, metadata, params):
    """Compute CPK table for the given parameters.

    Returns ``{'results': {param: {...}}, 'count': N}``, matching the
    original response shape of ``AnalysisViewSet.cpk``.
    """
    results = {}
    for param in params:
        data_series = get_1d_from(df, param).dropna()
        data_series = data_series[
            data_series.apply(lambda x: abs(x) < float('inf'))]
        if len(data_series) == 0:
            continue

        stats = compute_range_statistics(data_series, metadata, param)
        cpk_result = compute_cpk(
            stats['mean'], stats['std'], stats['rdl'][0], stats['rdl'][1]
        )
        results[param] = {
            'mean': round(stats['mean'], 6),
            'std': round(stats['std'], 6),
            'cp': round(cpk_result['cp'], 4),
            'cpk': round(cpk_result['cpk'], 4),
            'pp': round(cpk_result['pp'], 4),
            'ppk': round(cpk_result['ppk'], 4),
            'cp_level': cpk_result['cp_level'],
            'cpk_level': cpk_result['cpk_level'],
            'pp_level': cpk_result['pp_level'],
            'ppk_level': cpk_result['ppk_level'],
            'cp_color': cpk_result['cp_color'],
            'cpk_color': cpk_result['cpk_color'],
            'pp_color': cpk_result['pp_color'],
            'ppk_color': cpk_result['ppk_color'],
        }
    return {'results': results, 'count': len(results)}
