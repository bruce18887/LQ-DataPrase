import math
import os

import numpy as np
import pandas as pd
from django.shortcuts import get_object_or_404
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.datafiles.models import DataFile
from apps.datafiles.parsers import get_parser
from apps.analysis.services.statistics import (
    compute_cpk,
    compute_range_statistics,
    compute_site_stats,
    detect_fail_data,
    calculate_fail_bin_statistics,
    calculate_fail_test_item_statistics,
    compute_correlation_matrix,
    compute_bin_trend,
    compute_boxplot_stats,
    compute_param_trend,
    get_site_column,
    get_serial_column,
    get_columns_with_limits,
    get_1d_from,
    safe_gap,
)


def clean_data(data):
    if isinstance(data, list):
        return [clean_data(item) for item in data]
    elif isinstance(data, dict):
        return {k: clean_data(v) for k, v in data.items()}
    elif isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return 0.0
        return data
    else:
        return data


def _load_df_from_request(request):
    file_id = request.data.get('file_id') or request.query_params.get('file_id')
    if not file_id:
        return None, None, None, 'file_id_required'
    datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)
    if not os.path.exists(datafile.file_path):
        return None, datafile, None, 'file_not_found'

    parser = get_parser(datafile.format_type)
    df, metadata = parser.parse(datafile.file_path)
    if df is None:
        return None, datafile, None, 'parse_failed'
    return df, datafile, metadata, None


class AnalysisViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def histogram(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        params = request.data.get('params')
        ignore_no_limit = request.data.get('ignore_no_limit', False)

        if not params:
            numeric_cols = [c for c in df.columns if df[c].dtype in ('int64', 'float64')]
            if ignore_no_limit:
                params = get_columns_with_limits(df, metadata)
            else:
                params = numeric_cols
            # Fast path: only return param names, no heavy computation
            return Response({
                'file_id': datafile.id,
                'filename': datafile.filename,
                'format_type': datafile.format_type,
                'results': {p: {} for p in params},
            })

        if ignore_no_limit:
            cols_with_limits = set(get_columns_with_limits(df, metadata))
            params = [p for p in params if p in cols_with_limits]

        results = {}
        site_col = get_site_column(df)
        for param in params:
            data_series = get_1d_from(df, param).dropna()
            data_series = data_series[data_series.apply(lambda x: abs(x) < float('inf'))]
            if len(data_series) == 0:
                continue

            stats = compute_range_statistics(data_series, metadata, param)
            cpk_result = compute_cpk(
                stats['mean'], stats['std'], stats['rdl'][0], stats['rdl'][1]
            )

            site_data = None
            if site_col:
                site_series = get_1d_from(df, param)
                site_idx = get_1d_from(df, site_col)
                site_data = compute_site_stats(
                    site_series, site_idx, stats['rdl'][0], stats['rdl'][1],
                    None, None, False
                )

            rdl_min = stats['rdl'][0]
            rdl_max = stats['rdl'][1]
            data_gap = safe_gap(rdl_min, rdl_max)
            bin_start = rdl_min - 2.5 * data_gap
            all_bins = np.array([bin_start + j * data_gap for j in range(26)])
            hist_counts, _ = np.histogram(data_series.dropna(), bins=all_bins)
            bin_centers = [(all_bins[i] + all_bins[i + 1]) / 2 for i in range(25)]
            bin_percentages = [round(c / len(data_series) * 100, 2) if len(data_series) > 0 else 0 for c in hist_counts]

            site_histograms = None
            if site_col and len(site_idx.unique()) > 1:
                site_histograms = {}
                site_idx_aligned = site_idx[data_series.index]

                def site_sort_key(s):
                    try:
                        return (0, float(s), '')
                    except (ValueError, TypeError):
                        return (1, 0, str(s))

                for site in sorted(site_idx_aligned.unique(), key=site_sort_key):
                    mask = (site_idx_aligned == site).values if hasattr(site_idx_aligned, 'values') else (site_idx_aligned == site)
                    if isinstance(mask, pd.Series):
                        mask = mask.values
                    vals = data_series[mask]
                    if len(vals) > 0:
                        site_hist, _ = np.histogram(vals, bins=all_bins)
                        total = len(vals)
                        site_histograms[str(site)] = [
                            round(c / total * 100, 2) if total > 0 else 0
                            for c in site_hist
                        ]

            results[param] = {
                'mean': round(stats['mean'], 6),
                'std': round(stats['std'], 6),
                'unit': stats['unit'],
                'lower_limit': round(stats['rdl'][0], 6),
                'upper_limit': round(stats['rdl'][1], 6),
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
                'data_min': round(stats['dr'][0], 6),
                'data_max': round(stats['dr'][1], 6),
                'sigma3_min': round(stats['s3'][0], 6),
                'sigma3_max': round(stats['s3'][1], 6),
                'sigma6_min': round(stats['s6'][0], 6),
                'sigma6_max': round(stats['s6'][1], 6),
                'site_stats': site_data,
                'site_histograms': site_histograms,
                'bin_centers': [round(c, 6) for c in bin_centers],
                'bin_percentages': bin_percentages,
                'total_count': len(data_series),
            }

        return Response(clean_data({
            'file_id': datafile.id,
            'filename': datafile.filename,
            'format_type': datafile.format_type,
            'results': results,
        }))

    @action(detail=False, methods=['post'])
    def wafer_map(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        from apps.analysis.services.statistics import (
            get_coord_columns, compute_wafer_fail_data,
            get_bin_column,
        )

        x_col, y_col = get_coord_columns(df)
        if not x_col or not y_col:
            return Response({'error': 'no_coord_columns'})

        param = request.data.get('param')
        color_by = request.data.get('color_by', 'result')
        fail_mask, wafer_stats = compute_wafer_fail_data(df, metadata, param)

        site_col = get_site_column(df)
        serial_col = get_serial_column(df)
        # STS8200 fallback: look for columns with 'part' and 'id' in name
        if not serial_col:
            for col in df.columns:
                col_lower = col.lower()
                if 'part' in col_lower and 'id' in col_lower:
                    serial_col = col
                    break
        bin_col = get_bin_column(df, metadata)

        points = []
        for idx in df.index:
            try:
                x_val = float(df.loc[idx, x_col])
                y_val = float(df.loc[idx, y_col])
            except (ValueError, TypeError):
                continue
            point = {
                'x': x_val,
                'y': y_val,
                'status': 'Fail' if fail_mask.loc[idx] else 'Pass',
            }
            if serial_col:
                point['serial'] = str(df.loc[idx, serial_col])
            if bin_col:
                point['bin'] = str(df.loc[idx, bin_col])
            if site_col:
                point['site'] = str(df.loc[idx, site_col])
            if color_by == 'site' and site_col:
                point['color_group'] = f'Site {df.loc[idx, site_col]}'
            points.append(point)

        # Compute wafer boundary circle
        x_vals = [p['x'] for p in points]
        y_vals = [p['y'] for p in points]
        if not x_vals:
            return Response({'file_id': datafile.id, 'x_col': x_col, 'y_col': y_col,
                             'points': [], 'stats': wafer_stats})

        center_x = (min(x_vals) + max(x_vals)) / 2
        center_y = (min(y_vals) + max(y_vals)) / 2
        radius = max(max(x_vals) - min(x_vals), max(y_vals) - min(y_vals)) / 2 * 1.08

        # Compute die size
        unique_x = sorted(set(x_vals))
        die_x = 1
        if len(unique_x) > 1:
            gaps = [abs(unique_x[i + 1] - unique_x[i]) for i in range(len(unique_x) - 1)]
            die_x = min(gaps)

        return Response(clean_data({
            'file_id': datafile.id,
            'x_col': x_col,
            'y_col': y_col,
            'points': points,
            'stats': wafer_stats,
            'wafer': {
                'center_x': round(center_x, 2),
                'center_y': round(center_y, 2),
                'radius': round(radius, 2),
                'die_size': round(die_x, 2),
            },
        }))

    @action(detail=False, methods=['post'])
    def multi_lot(self, request):
        file_ids = request.data.get('file_ids', [])
        param = request.data.get('param')
        if not file_ids or len(file_ids) < 2:
            return Response({'error': 'need_at_least_2_files'}, status=400)

        datasets = {}
        all_series = []
        for fid in file_ids:
            df_obj = get_object_or_404(DataFile, pk=fid, owner=request.user)
            parser = get_parser(df_obj.format_type)
            df, metadata = parser.parse(df_obj.file_path)
            if df is None:
                continue
            if param and param in df.columns:
                s = get_1d_from(df, param).dropna()
                s = s[abs(s) < float('inf')]
                if len(s) > 0:
                    datasets[str(fid)] = {'df': df, 'metadata': metadata, 'series': s}
                    all_series.append(s)

        if not all_series:
            return Response({'error': 'no_data'}, status=400)

        combined = pd.concat(all_series)
        global_mean = float(combined.mean())
        global_std = float(combined.std(ddof=0)) if len(combined) > 1 else 0
        min_val = float(combined.min())
        max_val = float(combined.max())
        bin_count = 25
        bin_width = (max_val - min_val) / bin_count if max_val != min_val else 1
        bins = np.linspace(min_val - bin_width / 2, max_val + bin_width / 2, bin_count + 1)
        bin_centers = [float((bins[i] + bins[i + 1]) / 2) for i in range(bin_count)]

        lot_data = []
        colors = ['#E53935', '#1E88E5', '#43A047', '#F9A825', '#8E24AA', '#00ACC1', '#F57C00', '#D81B60']
        for idx, (fid, ds) in enumerate(datasets.items()):
            hist, _ = np.histogram(ds['series'], bins=bins)
            pcts = [round(c / len(ds['series']) * 100, 2) if len(ds['series']) > 0 else 0 for c in hist]
            bar_data = [[bin_centers[i], pcts[i]] for i in range(bin_count)]
            obj = DataFile.objects.get(pk=int(fid), owner=request.user)
            mean_v = float(ds['series'].mean())
            std_v = float(ds['series'].std(ddof=0)) if len(ds['series']) > 1 else 0
            fail = int(((ds['series'] < ds['metadata'].get('mins', {}).get(param, -1e9)) | (ds['series'] > ds['metadata'].get('maxs', {}).get(param, 1e9))).sum())
            lot_data.append({
                'name': obj.filename[:20],
                'color': colors[idx % len(colors)],
                'bar_data': bar_data,
                'mean': round(mean_v, 6),
                'std': round(std_v, 6),
                'count': len(ds['series']),
                'fail': fail,
                'yield_pct': round((len(ds['series']) - fail) / len(ds['series']) * 100, 2),
                'min_v': round(float(ds['series'].min()), 6),
                'max_v': round(float(ds['series'].max()), 6),
            })

        return Response(clean_data({
            'param': param,
            'global_mean': round(global_mean, 6),
            'global_std': round(global_std, 6),
            'chart_min': round(float(bins[0]), 6),
            'chart_max': round(float(bins[-1]), 6),
            'bin_centers': bin_centers,
            'lot_data': lot_data,
        }))

    @action(detail=False, methods=['post'])
    def correlation(self, request):
        """Return raw data for two selected parameters, organized by Site for scatter plot."""
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        param_x = request.data.get('param_x')
        param_y = request.data.get('param_y')
        if not param_x or not param_y:
            return Response({'error': 'param_x_and_param_y_required'}, status=400)

        if param_x not in df.columns or param_y not in df.columns:
            return Response({'error': 'param_not_found'}, status=400)

        x_series = get_1d_from(df, param_x)
        y_series = get_1d_from(df, param_y)

        # remove inf/nan
        mask = (x_series.apply(lambda v: abs(float(v)) < float('inf')) if hasattr(x_series, 'apply') else True) & \
               (y_series.apply(lambda v: abs(float(v)) < float('inf')) if hasattr(y_series, 'apply') else True)
        x_series = x_series[mask].dropna()
        y_series = y_series[mask].dropna()
        common_idx = x_series.index.intersection(y_series.index)
        x_vals = x_series.loc[common_idx].astype(float)
        y_vals = y_series.loc[common_idx].astype(float)

        site_col = get_site_column(df)

        series_data = []
        if site_col:
            site_idx = get_1d_from(df, site_col).loc[common_idx]
            for site in sorted(site_idx.unique()):
                smask = site_idx == site
                pts = [[float(x_vals[i]), float(y_vals[i])] for i in x_vals.index[smask] if not np.isnan(x_vals[i]) and not np.isnan(y_vals[i])]
                if pts:
                    series_data.append({'name': f'Site {site}', 'data': pts})
        else:
            pts = [[float(x_vals[i]), float(y_vals[i])] for i in x_vals.index if not np.isnan(x_vals[i]) and not np.isnan(y_vals[i])]
            if pts:
                series_data.append({'name': 'Data', 'data': pts})

        # Pearson r
        n = len(common_idx)
        pearson_r = 0.0
        if n > 2:
            x_arr = x_vals.values
            y_arr = y_vals.values
            mx = np.mean(x_arr)
            my = np.mean(y_arr)
            sx = np.std(x_arr, ddof=0)
            sy = np.std(y_arr, ddof=0)
            if sx > 0 and sy > 0:
                pearson_r = float(np.corrcoef(x_arr, y_arr)[0, 1])

        return Response(clean_data({
            'param_x': param_x,
            'param_y': param_y,
            'n': n,
            'pearson_r': round(pearson_r, 6),
            'series_data': series_data,
        }))

    @action(detail=False, methods=['post'])
    def serial_distribution(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        param = request.data.get('param')
        if not param:
            return Response({'error': 'param_required'}, status=400)

        # Chart config from frontend (same as histogram)
        chart_config = request.data.get('chart_config', [])
        range_type = request.data.get('range_type', 'RDL')

        serial_col = get_serial_column(df)
        if not serial_col:
            return Response({'error': 'no_serial_column'})

        # Ensure numeric and clean data
        serial_site_data = df[[serial_col, param]].copy()
        serial_site_data[param] = pd.to_numeric(serial_site_data[param], errors='coerce')
        serial_site_data = serial_site_data.dropna(subset=[param])
        serial_site_data = serial_site_data.iloc[np.isfinite(serial_site_data[param].values)]
        serial_site_data = serial_site_data.reset_index(drop=True)
        serial_site_data[serial_col] = pd.to_numeric(serial_site_data[serial_col], errors='coerce')

        site_col = get_site_column(df)

        # Build grouped data
        if site_col:
            sws = df[[serial_col, site_col, param]].copy()
            sws[site_col] = get_1d_from(sws, site_col)
            sws[param] = pd.to_numeric(sws[param], errors='coerce')
            sws = sws.dropna(subset=[param])
            sws = sws.iloc[np.isfinite(sws[param].values)]
            sws = sws.reset_index(drop=True)
            sws[serial_col] = pd.to_numeric(sws[serial_col], errors='coerce')
            site_key = get_1d_from(sws, site_col)
            serial_key = get_1d_from(sws, serial_col)
            serial_grouped = sws.groupby([site_key, serial_key])[param].first()
            serial_grouped.index.names = ['__idx_0__', '__idx_1__']
            serial_grouped = serial_grouped.reset_index()
            expected = []
            seen = set()
            for name in [site_col, serial_col, param]:
                if name not in seen:
                    seen.add(name)
                    expected.append(name)
            serial_grouped = serial_grouped.iloc[:, :len(expected)]
            serial_grouped.columns = expected
        else:
            serial_key = get_1d_from(serial_site_data, serial_col)
            serial_grouped = serial_site_data.groupby(serial_key)[param].first()
            serial_grouped.index.name = '__idx_0__'
            serial_grouped = serial_grouped.reset_index()
            expected = []
            seen = set()
            for name in [serial_col, param]:
                if name not in seen:
                    seen.add(name)
                    expected.append(name)
            serial_grouped = serial_grouped.iloc[:, :len(expected)]
            serial_grouped.columns = expected

        # Build continuous serials
        all_serials = serial_grouped[serial_col].dropna()
        try:
            all_serials = all_serials.astype(int)
            continuous_serials = list(range(int(all_serials.min()), int(all_serials.max()) + 1))
        except (ValueError, TypeError):
            continuous_serials = sorted(list(set(all_serials.dropna().tolist())))

        # Build series_data
        series_data = []
        if site_col:
            for si, site in enumerate(sorted(serial_grouped[site_col].unique())):
                sdf = serial_grouped[serial_grouped[site_col] == site]
                sv_col = param if param in serial_grouped.columns else serial_col
                sv = dict(zip(sdf[serial_col].tolist(), sdf[sv_col].tolist()))
                pts = [[s, sv[s]] for s in continuous_serials if s in sv]
                series_data.append({
                    'name': f'Site {site}',
                    'type': 'scatter',
                    'data': pts,
                    'symbolSize': 6,
                })
        else:
            sv_col = param if param in serial_grouped.columns else serial_col
            sv = dict(zip(serial_grouped[serial_col].tolist(), serial_grouped[sv_col].tolist()))
            pts = [[s, sv[s]] for s in continuous_serials if s in sv]
            series_data.append({
                'name': param,
                'type': 'scatter',
                'data': pts,
                'symbolSize': 6,
            })

        # Compute stats for marks
        from apps.analysis.services.statistics import compute_range_statistics, parse_limit_string
        data_series = get_1d_from(df, param).dropna()
        stats = compute_range_statistics(data_series, metadata, param)
        mean_val = stats['mean']
        std_val = stats['std']

        # Determine spec limits based on range_type (same as histogram)
        spec_lower = None
        spec_upper = None
        if range_type == 'RDL':
            spec_lower = stats['rdl'][0]
            spec_upper = stats['rdl'][1]
        elif range_type == 'DR':
            spec_lower = stats['dr'][0]
            spec_upper = stats['dr'][1]
        elif range_type == 'CL':
            spec_lower = stats['cl'][0]
            spec_upper = stats['cl'][1]
        elif range_type == 'S3':
            spec_lower = stats['s3'][0]
            spec_upper = stats['s3'][1]
        elif range_type == 'S4':
            spec_lower = stats['s4'][0]
            spec_upper = stats['s4'][1]
        elif range_type == 'S6':
            spec_lower = stats['s6'][0]
            spec_upper = stats['s6'][1]

        # Build marks same as old _build_mark_series
        show_limit = 'limit' in chart_config
        show_3sigma = 's3' in chart_config
        show_4sigma = 's4' in chart_config
        show_6sigma = 's6' in chart_config

        marks = []
        if show_limit and spec_lower is not None and spec_upper is not None:
            marks.append({
                'name': '规格限',
                'type': 'scatter',
                'data': [],
                'markLine': {
                    'symbol': 'none',
                    'precision': 4,
                    'data': [
                        {'yAxis': spec_lower, 'lineStyle': {'color': '#FF6384', 'width': 3, 'type': 'dashed'}, 'label': {'show': True, 'formatter': 'LSL', 'position': 'end'}},
                        {'yAxis': spec_upper, 'lineStyle': {'color': '#FF6384', 'width': 3, 'type': 'dashed'}, 'label': {'show': True, 'formatter': 'USL', 'position': 'end'}},
                    ]
                }
            })
        for sigma, flag, color in [(3, show_3sigma, '#5470c6'), (4, show_4sigma, '#91cc75'), (6, show_6sigma, '#fac858')]:
            if flag:
                lower = mean_val - sigma * std_val
                upper = mean_val + sigma * std_val
                marks.append({
                    'name': f'{sigma}σ范围',
                    'type': 'scatter',
                    'data': [],
                    'markLine': {
                        'symbol': 'none',
                        'precision': 4,
                        'data': [
                            {'yAxis': lower, 'lineStyle': {'color': color, 'width': 3, 'type': 'dotted'}, 'label': {'show': True, 'formatter': f'{sigma}σ下限', 'position': 'insideEndTop'}},
                            {'yAxis': upper, 'lineStyle': {'color': color, 'width': 3, 'type': 'dotted'}, 'label': {'show': True, 'formatter': f'{sigma}σ上限', 'position': 'insideEndTop'}},
                        ]
                    }
                })

        # Calculate y-axis limits with padding
        y_min = spec_lower
        y_max = spec_upper
        if y_min is not None and y_max is not None and y_max > y_min:
            pad = (y_max - y_min) * 0.1
            y_min = y_min - pad
            y_max = y_max + pad

        return Response(clean_data({
            'param': param,
            'unit': metadata.get('units', {}).get(param, ''),
            'serial_col': serial_col,
            'lower_limit': spec_lower,
            'upper_limit': spec_upper,
            'mean': mean_val,
            'std': std_val,
            'series_data': series_data,
            'continuous_serials': continuous_serials,
            'marks': marks,
            'y_min': y_min,
            'y_max': y_max,
        }))

    @action(detail=False, methods=['post'])
    def cpk(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        params = request.data.get('params')
        if not params:
            cols = get_columns_with_limits(df, metadata)
            params = cols

        results = {}
        for param in params:
            data_series = get_1d_from(df, param).dropna()
            data_series = data_series[data_series.apply(lambda x: abs(x) < float('inf'))]
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

        return Response(clean_data({'results': results, 'count': len(results)}))

    @action(detail=False, methods=['post'])
    def correlation_matrix(self, request):
        """
        Compute correlation matrix for multiple parameters.

        Request body:
        {
            "file_id": 123,
            "params": ["Param1", "Param2", "Param3"],  // Optional, defaults to all numeric params with limits
            "method": "pearson"  // or "spearman", default is "pearson"
        }
        """
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        params = request.data.get('params', [])
        method = request.data.get('method', 'pearson')

        # Validate method
        if method not in ['pearson', 'spearman']:
            return Response({'error': 'invalid_method'}, status=400)

        # If no params specified, use all numeric columns with limits
        if not params:
            params = get_columns_with_limits(df, metadata)

        # Compute correlation matrix
        result = compute_correlation_matrix(df, params, method)

        return Response(clean_data({
            'file_id': datafile.id,
            'filename': datafile.filename,
            'params': result['params'],
            'matrix': result['matrix'],
            'sample_size': result['sample_size'],
            'method': method
        }))

    @action(detail=False, methods=['post'])
    def bin_trend(self, request):
        """
        Compute bin distribution trend across multiple files.

        Request body:
        {
            "file_ids": [123, 124, 125],
            "group_by": "file"  // Currently only "file" is supported
        }
        """
        file_ids = request.data.get('file_ids', [])
        if not file_ids or not isinstance(file_ids, list):
            return Response({'error': 'file_ids_required'}, status=400)

        # Load all files
        dfs = []
        metadatas = []
        file_info = []

        for file_id in file_ids:
            try:
                datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)

                if not os.path.exists(datafile.file_path):
                    continue

                parser = get_parser(datafile.format_type)
                df, metadata = parser.parse(datafile.file_path)

                dfs.append(df)
                metadatas.append(metadata)
                file_info.append({
                    'file_id': datafile.id,
                    'filename': datafile.filename,
                    'timestamp': datafile.created_at.strftime('%Y-%m-%d %H:%M:%S')
                })
            except Exception:
                continue

        if len(dfs) == 0:
            return Response({'error': 'no_valid_files'}, status=400)

        # Compute bin trend
        result = compute_bin_trend(dfs, metadatas)

        return Response(clean_data({
            'files': file_info,
            'bins': result['bins'],
            'trend_data': result['trend_data'],
            'yield_trend': result['yield_trend']
        }))

    @action(detail=False, methods=['post'])
    def boxplot(self, request):
        """
        Compute box plot statistics for parameters.

        Request body:
        {
            "file_id": 123,
            "params": ["Param1", "Param2"],
            "group_by": "site"  // Optional: "site", "bin", or null for overall
        }
        """
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        params = request.data.get('params', [])
        group_by = request.data.get('group_by', None)

        if not params:
            return Response({'error': 'params_required'}, status=400)

        results = {}
        site_col = get_site_column(df) if group_by == 'site' else None

        for param in params:
            if param not in df.columns:
                continue

            data_series = get_1d_from(df, param)

            # Overall statistics
            overall_stats = compute_boxplot_stats(data_series)

            param_result = {
                'overall': overall_stats
            }

            # Group by site if requested
            if group_by == 'site' and site_col:
                site_idx = get_1d_from(df, site_col)
                by_site = {}

                for site in sorted(site_idx.unique(), key=str):
                    mask = (site_idx == site)
                    if isinstance(mask, pd.Series):
                        mask = mask.values
                    site_data = data_series[mask]
                    by_site[str(site)] = compute_boxplot_stats(site_data)

                param_result['by_site'] = by_site

            results[param] = param_result

        return Response(clean_data({
            'file_id': datafile.id,
            'filename': datafile.filename,
            'results': results
        }))

    @action(detail=False, methods=['post'])
    def param_trend(self, request):
        """
        Compute parameter statistics trend across multiple files.

        Request body:
        {
            "file_ids": [123, 124, 125],
            "param": "Param1",
            "group_by": "file"  // Currently only "file" is supported
        }
        """
        file_ids = request.data.get('file_ids', [])
        param = request.data.get('param', '')

        if not file_ids or not isinstance(file_ids, list):
            return Response({'error': 'file_ids_required'}, status=400)

        if not param:
            return Response({'error': 'param_required'}, status=400)

        # Load all files
        dfs = []
        metadatas = []
        file_info = []

        for file_id in file_ids:
            try:
                datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)

                if not os.path.exists(datafile.file_path):
                    continue

                parser = get_parser(datafile.format_type)
                df, metadata = parser.parse(datafile.file_path)

                dfs.append(df)
                metadatas.append(metadata)
                file_info.append({
                    'file_id': datafile.id,
                    'filename': datafile.filename,
                    'timestamp': datafile.created_at.strftime('%Y-%m-%d %H:%M:%S')
                })
            except Exception:
                continue

        if len(dfs) == 0:
            return Response({'error': 'no_valid_files'}, status=400)

        # Compute parameter trend
        result = compute_param_trend(dfs, param, metadatas)

        return Response(clean_data({
            'files': file_info,
            'param': result['param'],
            'trend_data': result['trend_data'],
            'limits': result['limits']
        }))


class StatisticsViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['post'])
    def detect_fail(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        fail_indices, fail_columns, fail_cells = detect_fail_data(df, metadata)
        unique_fail_rows = len(set(fail_indices))

        fail_mask = {}
        for idx, cols in fail_cells.items():
            fail_mask[str(idx)] = cols

        col_meta = {}
        units = metadata.get('units', {})
        mins = metadata.get('mins', {})
        maxs = metadata.get('maxs', {})
        for col in df.columns:
            col_meta[col] = {
                'unit': units.get(col, '') if isinstance(units, dict) else '',
                'min': mins.get(col, '') if isinstance(mins, dict) else '',
                'max': maxs.get(col, '') if isinstance(maxs, dict) else '',
            }

        return Response(clean_data({
            'fail_row_count': unique_fail_rows,
            'total_rows': df.shape[0],
            'fail_col_summary': list(set(fail_columns))[:50],
            'fail_mask': fail_mask,
            'col_meta': col_meta,
        }))

    @action(detail=False, methods=['post'])
    def bin_stats(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        stats = calculate_fail_bin_statistics(df, metadata)
        result = []
        for bv, s in stats.items():
            result.append({
                'bin': str(bv),
                'count': s['count'],
                'percentage': s['percentage'],
            })
        return Response({'bin_stats': result})

    @action(detail=False, methods=['post'])
    def site_stats(self, request):
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        param = request.data.get('param')
        if not param:
            return Response({'error': 'param_required'}, status=400)

        range_type = request.data.get('range_type', 'RDL')

        data_series = get_1d_from(df, param).dropna()
        data_series = data_series[data_series.apply(lambda x: abs(x) < float('inf'))]
        site_col = get_site_column(df)

        if not site_col:
            return Response({
                'error': 'no_site_column',
                'site_data': [],
                'available_columns': list(df.columns),
            })

        stats = compute_range_statistics(data_series, metadata, param)

        # Determine limits based on range_type (same as histogram and serial distribution)
        lower_limit = None
        upper_limit = None
        if range_type == 'RDL':
            lower_limit = stats['rdl'][0]
            upper_limit = stats['rdl'][1]
        elif range_type == 'DR':
            lower_limit = stats['dr'][0]
            upper_limit = stats['dr'][1]
        elif range_type == 'CL':
            lower_limit = stats['cl'][0]
            upper_limit = stats['cl'][1]
        elif range_type == 'S3':
            lower_limit = stats['s3'][0]
            upper_limit = stats['s3'][1]
        elif range_type == 'S4':
            lower_limit = stats['s4'][0]
            upper_limit = stats['s4'][1]
        elif range_type == 'S6':
            lower_limit = stats['s6'][0]
            upper_limit = stats['s6'][1]

        site_idx = get_1d_from(df, site_col)
        site_result = compute_site_stats(
            data_series, site_idx, lower_limit, upper_limit,
            None, None, False
        )

        return Response(clean_data({
            'param': param,
            'site_data': site_result,
        }))

    @action(detail=False, methods=['post'])
    def correlation_matrix(self, request):
        """
        Compute correlation matrix for multiple parameters.

        Request body:
        {
            "file_id": 123,
            "params": ["Param1", "Param2", "Param3"],  // Optional, defaults to all numeric params with limits
            "method": "pearson"  // Optional: "pearson", "spearman", or "kendall"
        }
        """
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        params = request.data.get('params')
        method = request.data.get('method', 'pearson')

        # Validate method
        if method not in ['pearson', 'spearman', 'kendall']:
            return Response({'error': 'invalid_method', 'valid_methods': ['pearson', 'spearman', 'kendall']}, status=400)

        # If no params specified, use all columns with limits
        if not params:
            params = get_columns_with_limits(df, metadata)

        if not params or len(params) < 2:
            return Response({'error': 'need_at_least_2_params', 'available_params': get_columns_with_limits(df, metadata)}, status=400)

        result = compute_correlation_matrix(df, params, method)

        return Response(clean_data({
            'file_id': datafile.id,
            'filename': datafile.filename,
            **result
        }))

    @action(detail=False, methods=['post'])
    def bin_trend(self, request):
        """
        Compute bin distribution trend across multiple files.

        Request body:
        {
            "file_ids": [123, 124, 125],
            "group_by": "file"  // Optional: "file" or "date"
        }
        """
        file_ids = request.data.get('file_ids', [])
        if not file_ids:
            return Response({'error': 'file_ids_required'}, status=400)

        # Load all files
        file_data_list = []
        for file_id in file_ids:
            try:
                datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)
                if not os.path.exists(datafile.file_path):
                    continue

                parser = get_parser(datafile.format_type)
                df, metadata = parser.parse(datafile.file_path)

                file_data_list.append({
                    'df': df,
                    'metadata': metadata,
                    'file_id': datafile.id,
                    'filename': datafile.filename,
                    'timestamp': datafile.created_at.strftime('%Y-%m-%d %H:%M:%S') if datafile.created_at else ''
                })
            except Exception as e:
                continue

        if not file_data_list:
            return Response({'error': 'no_valid_files'}, status=400)

        result = compute_bin_trend(file_data_list)

        return Response(clean_data(result))

    @action(detail=False, methods=['post'])
    def boxplot(self, request):
        """
        Compute box plot statistics for parameters.

        Request body:
        {
            "file_id": 123,
            "params": ["Param1", "Param2"],
            "group_by": "site"  // Optional: "site", "bin", or null for overall
        }
        """
        df, datafile, metadata, err = _load_df_from_request(request)
        if err:
            return Response({'error': err}, status=400)

        params = request.data.get('params')
        group_by = request.data.get('group_by')

        if not params:
            return Response({'error': 'params_required'}, status=400)

        results = {}

        for param in params:
            if param not in df.columns:
                continue

            data_series = get_1d_from(df, param)
            param_result = {
                'overall': compute_boxplot_stats(data_series)
            }

            # Group by site or bin if requested
            if group_by == 'site':
                site_col = get_site_column(df)
                if site_col:
                    site_idx = get_1d_from(df, site_col)
                    by_group = {}
                    for site in site_idx.unique():
                        if pd.isna(site):
                            continue
                        mask = (site_idx == site)
                        if isinstance(mask, pd.Series):
                            mask = mask.values
                        site_data = data_series[mask]
                        by_group[str(site)] = compute_boxplot_stats(site_data)
                    param_result['by_site'] = by_group

            elif group_by == 'bin':
                bin_col = None
                for col in df.columns:
                    if 'bin' in col.lower():
                        bin_col = col
                        break
                if bin_col:
                    bin_idx = get_1d_from(df, bin_col)
                    by_group = {}
                    for bin_val in bin_idx.unique():
                        if pd.isna(bin_val):
                            continue
                        mask = (bin_idx == bin_val)
                        if isinstance(mask, pd.Series):
                            mask = mask.values
                        bin_data = data_series[mask]
                        by_group[str(bin_val)] = compute_boxplot_stats(bin_data)
                    param_result['by_bin'] = by_group

            results[param] = param_result

        return Response(clean_data({
            'file_id': datafile.id,
            'filename': datafile.filename,
            'results': results
        }))

    @action(detail=False, methods=['post'])
    def param_trend(self, request):
        """
        Compute parameter statistics trend across multiple files.

        Request body:
        {
            "file_ids": [123, 124, 125],
            "param": "Param1",
            "group_by": "file"  // Optional: "file" or "date"
        }
        """
        file_ids = request.data.get('file_ids', [])
        param = request.data.get('param')

        if not file_ids:
            return Response({'error': 'file_ids_required'}, status=400)

        if not param:
            return Response({'error': 'param_required'}, status=400)

        # Load all files
        file_data_list = []
        for file_id in file_ids:
            try:
                datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)
                if not os.path.exists(datafile.file_path):
                    continue

                parser = get_parser(datafile.format_type)
                df, metadata = parser.parse(datafile.file_path)

                file_data_list.append({
                    'df': df,
                    'metadata': metadata,
                    'file_id': datafile.id,
                    'filename': datafile.filename,
                    'timestamp': datafile.created_at.strftime('%Y-%m-%d %H:%M:%S') if datafile.created_at else ''
                })
            except Exception as e:
                continue

        if not file_data_list:
            return Response({'error': 'no_valid_files'}, status=400)

        result = compute_param_trend(file_data_list, param)

        return Response(clean_data(result))
