"""Batch-level aggregation helpers for the batch report.

These pure functions take the already-computed per-phase structures produced by
``BatchReportViewSet.batch_yield_data`` and roll them up to batch level so the
batch report can reuse the single-file analysis components:

- ``aggregate_bin_site_table`` → ``bin_table_data`` + ``bin_site_columns``
  (matches ``apps.dashboard.views.compute_bin_site_table`` output shape, consumed
  by ``frontend/.../dashboard/components/BinSiteCrossTable.vue``).
- ``aggregate_uph`` → a single ``UphData``-shaped dict (matches
  ``apps.analysis.services.statistics.compute_uph`` output, consumed by
  ``frontend/.../dashboard/components/UphCard.vue``).

Kept as pure functions (no DB / DataFrame access) so they are trivially unit
testable.
"""
from collections import defaultdict
from typing import Any, Dict, List


def _bin_sort_key(bin_name: str):
    """Sort bins numerically when possible (Bin 1 < Bin 2 < Bin 10), else by string.

    Pass bin (1 / Bin1) is forced first to mirror the single-file ordering.
    """
    is_pass = bin_name in ('1', 'Bin1')
    try:
        return (0 if is_pass else 1, 0, float(bin_name))
    except (ValueError, TypeError):
        return (0 if is_pass else 1, 1, 0.0, str(bin_name))


def _format_bin_label(bin_name: str) -> str:
    """Format a raw bin name (e.g. '1', '12') as 'Bin 1' to match the single-file
    ``compute_bin_site_table`` output and ``BinSiteCrossTable.vue`` expectations."""
    try:
        return f'Bin {int(float(bin_name))}'
    except (ValueError, TypeError):
        return f'Bin {bin_name}'


def aggregate_bin_site_table(phases: List[Dict[str, Any]], sorted_sites: List[str]):
    """Aggregate a batch-level Bin x Site cross table across all phases.

    Sums, per (bin, site), the counts from each ``phase['bin_info'][i]['sites'][site]``.

    Returns ``(bin_table_data, bin_site_columns)`` in the SAME shape as the
    single-file ``compute_bin_site_table``:

    - ``bin_table_data``: one row per bin plus a final ``Total`` row. Each row is
      ``{'bin': 'Bin N', <site>: <count>, ..., 'all_site': <row total>}``.
    - ``bin_site_columns``: list of site column names (== ``sorted_sites``).
    """
    columns = [str(s) for s in sorted_sites]

    # bin_name -> {site -> count}
    bin_site_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for phase in phases:
        for binfo in phase.get('bin_info', []):
            bin_name = str(binfo.get('name', ''))
            sites = binfo.get('sites', {}) or {}
            for site, count in sites.items():
                bin_site_counts[bin_name][str(site)] += int(count or 0)

    if not bin_site_counts or not columns:
        return [], []

    bin_table_data: List[Dict[str, Any]] = []
    col_totals: Dict[str, int] = {col: 0 for col in columns}
    grand_total = 0

    for bin_name in sorted(bin_site_counts.keys(), key=_bin_sort_key):
        row: Dict[str, Any] = {'bin': _format_bin_label(bin_name)}
        row_total = 0
        for col in columns:
            count = int(bin_site_counts[bin_name].get(col, 0))
            row[col] = count
            row_total += count
            col_totals[col] += count
        row['all_site'] = row_total
        grand_total += row_total
        bin_table_data.append(row)

    total_row: Dict[str, Any] = {'bin': 'Total'}
    for col in columns:
        total_row[col] = col_totals[col]
    total_row['all_site'] = grand_total
    bin_table_data.append(total_row)

    return bin_table_data, columns


def aggregate_uph(phases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-phase ``uph`` dicts into a single batch-level ``UphData`` dict.

    Method (exact, no approximation — recovers the underlying serial test time from
    the values each phase already exposes):

    - Each phase's ``total_time_seconds`` is already the parallel-site wall-clock
      time (serial_seconds / site_count). Summing them yields the batch wall-clock
      time, so ``uph = total_tested / total_time_seconds * 3600`` stays consistent.
    - ``avg_test_time`` is the mean per-unit *serial* time. Per-phase serial seconds
      = ``avg_test_time * total_tested``; batch avg = sum(serial) / sum(tested).
    - Per-site: each phase ``by_site`` entry has ``uph = 3600 / site_avg``, so
      per-site serial seconds = ``tested * 3600 / uph``. Aggregate tested + serial
      per site, then recompute ``uph = 3600 * tested / serial`` — exact, not weighted.

    Adds a warning when some phases lacked UPH data (partial aggregate), and merges
    any per-phase warnings.
    """
    total_tested = 0
    total_time_seconds = 0.0
    total_serial_seconds = 0.0  # for batch avg_test_time
    merged_warnings: List[str] = []
    phases_with_data = 0
    phases_missing = 0
    sources = set()

    # site -> {'tested': int, 'serial': float}
    site_agg: Dict[str, Dict[str, float]] = defaultdict(lambda: {'tested': 0, 'serial': 0.0})

    for phase in phases:
        uph = phase.get('uph') or {}
        ph_tested = int(uph.get('total_tested', 0) or 0)
        ph_time = float(uph.get('total_time_seconds', 0) or 0)
        ph_avg = float(uph.get('avg_test_time', 0) or 0)

        for w in uph.get('warnings', []) or []:
            if w not in merged_warnings:
                merged_warnings.append(w)

        if ph_tested <= 0 or ph_time <= 0:
            phases_missing += 1
            continue

        phases_with_data += 1
        total_tested += ph_tested
        total_time_seconds += ph_time
        total_serial_seconds += ph_avg * ph_tested
        src = uph.get('source')
        if src and src not in ('unavailable', ''):
            sources.add(src)

        for site in uph.get('by_site', []) or []:
            site_id = str(site.get('site', ''))
            s_tested = int(site.get('tested', 0) or 0)
            s_uph = float(site.get('uph', 0) or 0)
            if s_tested <= 0:
                continue
            site_agg[site_id]['tested'] += s_tested
            if s_uph > 0:
                # serial seconds for this site's units = tested * 3600 / uph
                site_agg[site_id]['serial'] += s_tested * 3600.0 / s_uph

    if phases_missing > 0:
        merged_warnings.append(
            f'{phases_missing} 个文件缺少 UPH 数据，批次 UPH 为部分汇总'
        )

    if total_tested == 0 or total_time_seconds <= 0:
        return {
            'uph': 0.0,
            'avg_test_time': 0.0,
            'total_tested': 0,
            'total_time_seconds': 0.0,
            'source': 'batch',
            'by_site': [],
            'site_count': 0,
            'warnings': merged_warnings,
        }

    uph_val = total_tested / total_time_seconds * 3600.0
    avg_test_time = total_serial_seconds / total_tested if total_tested > 0 else 0.0

    def _site_sort_key(s: str):
        try:
            return (0, float(s), '')
        except (ValueError, TypeError):
            return (1, 0.0, str(s))

    by_site: List[Dict[str, Any]] = []
    for site_id in sorted(site_agg.keys(), key=_site_sort_key):
        s_tested = int(site_agg[site_id]['tested'])
        s_serial = site_agg[site_id]['serial']
        s_uph = (3600.0 * s_tested / s_serial) if s_serial > 0 else 0.0
        by_site.append({
            'site': site_id,
            'tested': s_tested,
            'uph': round(s_uph, 1),
        })

    return {
        'uph': round(uph_val, 1),
        'avg_test_time': round(avg_test_time, 3),
        'total_tested': total_tested,
        'total_time_seconds': round(total_time_seconds, 1),
        'source': 'batch',
        'by_site': by_site,
        'site_count': len(by_site),
        'warnings': merged_warnings,
    }
