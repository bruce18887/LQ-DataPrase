import logging
import os

import pandas as pd
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.datafiles.models import DataFile
from apps.datafiles.parsers import get_parser
from apps.analysis.services.statistics import (
    calculate_fail_bin_statistics,
    calculate_fail_test_item_statistics,
    get_site_column,
    get_columns_with_limits,
    compute_site_yield_data,
    get_bin_column_name,
)
from apps.datafiles.services import get_cached_parsed_file

logger = logging.getLogger(__name__)


def compute_bin_site_table(df, format_type, site_col):
    """计算Bin×Site交叉表"""
    if not site_col or site_col not in df.columns:
        return [], []

    bin_col = get_bin_column_name(format_type)
    if bin_col not in df.columns:
        return [], []

    try:
        # 使用pandas crosstab生成交叉表
        cross_table = pd.crosstab(
            df[bin_col],
            df[site_col],
            margins=True,
            margins_name='ALL'
        )

        # 转换为前端需要的格式
        bin_site_columns = [str(col) for col in cross_table.columns if col != 'ALL']
        bin_table_data = []

        for bin_value in cross_table.index:
            if bin_value == 'ALL':
                row = {'bin': 'Total'}
            else:
                try:
                    row = {'bin': f'Bin {int(float(bin_value))}'}
                except (ValueError, TypeError):
                    row = {'bin': f'Bin {bin_value}'}

            for col in cross_table.columns:
                if col == 'ALL':
                    row['all_site'] = int(cross_table.loc[bin_value, col])
                else:
                    row[str(col)] = int(cross_table.loc[bin_value, col])

            bin_table_data.append(row)

        return bin_table_data, bin_site_columns
    except Exception as e:
        logger.warning(f"compute_bin_site_table failed: {e}")
        return [], []


def compute_parameter_summary(df, metadata):
    """计算所有有规格限参数的 CPK 统计"""
    from apps.analysis.services.statistics import compute_cpk, parse_limit_string

    cols_with_limits = get_columns_with_limits(df, metadata)
    param_stats = []

    for param in cols_with_limits:
        try:
            data_series = df[param].dropna()
            if len(data_series) == 0:
                continue

            mean_val = float(data_series.mean())
            std_val = float(data_series.std(ddof=0))

            lsl_str = str(metadata.get('mins', {}).get(param, ''))
            usl_str = str(metadata.get('maxs', {}).get(param, ''))

            has_valid_lsl = lsl_str and lsl_str.strip() and lsl_str.strip().lower() not in ('', 'nan', 'none', 'n/a')
            has_valid_usl = usl_str and usl_str.strip() and usl_str.strip().lower() not in ('', 'nan', 'none', 'n/a')

            if not (has_valid_lsl or has_valid_usl):
                continue

            lsl = parse_limit_string(lsl_str, data_series, 0.0, 0.0) if has_valid_lsl else float('-inf')
            usl = parse_limit_string(usl_str, data_series, 0.0, 0.0) if has_valid_usl else float('inf')

            if lsl == float('-inf') and usl == float('inf'):
                continue

            cpk_result = compute_cpk(mean_val, std_val, lsl, usl)

            param_stats.append({
                'param': param,
                'mean': round(mean_val, 4),
                'std': round(std_val, 4),
                'cpk': round(cpk_result['cpk'], 3),
                'cpk_level': cpk_result['cpk_level'],
                'cpk_color': cpk_result['cpk_color'],
                'unit': metadata.get('units', {}).get(param, ''),
                'lsl': round(lsl, 4) if lsl != float('-inf') else None,
                'usl': round(usl, 4) if usl != float('inf') else None,
            })
        except Exception as e:
            logger.warning(f"compute_parameter_summary failed for {param}: {e}")
            continue

    # Sort by CPK ascending (worst first)
    param_stats.sort(key=lambda x: x['cpk'])
    return param_stats


def compute_quality_alerts(yield_pct, param_stats, site_yield_data):
    """生成质量警报"""
    alerts = []

    # 警报1：低良率
    if yield_pct < 90:
        alerts.append({
            'level': 'error',
            'type': 'low_yield',
            'message': f'整体良率过低: {yield_pct:.2f}% (目标: ≥90%)',
        })
    elif yield_pct < 95:
        alerts.append({
            'level': 'warning',
            'type': 'low_yield',
            'message': f'良率需要关注: {yield_pct:.2f}% (目标: ≥95%)',
        })

    # 警报2：低CPK参数
    low_cpk_params = [p for p in param_stats if p['cpk'] < 1.33]
    if low_cpk_params:
        alerts.append({
            'level': 'warning',
            'type': 'low_cpk',
            'message': f'{len(low_cpk_params)}个参数CPK不足 (CPK < 1.33)',
            'params': [p['param'] for p in low_cpk_params[:3]]
        })

    # 警报3：Site间差异大
    if site_yield_data and len(site_yield_data) > 1:
        yields = []
        for s in site_yield_data:
            if s['Site'] != 'ALL':
                try:
                    yields.append((float(s['Yield']), s['Site']))
                except (ValueError, TypeError):
                    continue

        if len(yields) > 1:
            yields.sort(key=lambda x: x[0])
            yield_diff = yields[-1][0] - yields[0][0]
            if yield_diff > 5:
                alerts.append({
                    'level': 'warning',
                    'type': 'site_variation',
                    'message': f'Site间良率差异过大: {yield_diff:.2f}%',
                    'max_site': yields[-1][1],
                    'min_site': yields[0][1]
                })

    return alerts


class DashboardSummaryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            file_id = request.query_params.get('file_id')
            if not file_id:
                datafile = DataFile.objects.filter(
                    owner=request.user, status='ready'
                ).order_by('-created_at').first()
            else:
                datafile = get_object_or_404(DataFile, pk=file_id, owner=request.user)

            if not datafile:
                return Response({'error': 'no_data'})

            file_path = datafile.file_path
            if not os.path.exists(file_path):
                return Response({'error': 'file_not_found'})

            df, metadata, fmt = get_cached_parsed_file(datafile.id, request.user.pk)
            if df is None:
                return Response({'error': 'parse_failed'})

            total_rows = df.shape[0]
            bin_stats = calculate_fail_bin_statistics(df, metadata)
            site_col = get_site_column(df)

            total_pass = 0
            bin_pie_data = []
            for bv, s in bin_stats.items():
                try:
                    if int(float(bv)) == 1:
                        total_pass = s['count']
                except (ValueError, TypeError):
                    pass
                try:
                    label = f"Bin {int(float(bv))}" if bv is not None else "Bin 0"
                except Exception:
                    label = f"Bin {bv}"
                bin_pie_data.append({'name': label, 'value': s['count']})

            fail_count = total_rows - total_pass
            yield_pct = round((total_pass / total_rows * 100), 2) if total_rows > 0 else 0

            site_yield_data = []
            if site_col:
                bin_col = get_bin_column_name(fmt)
                if bin_col in df.columns:
                    try:
                        yd = compute_site_yield_data(df, bin_col, site_col)
                        site_yield_data = yd.get('yield_data', [])
                    except Exception as e:
                        logger.warning(f"compute_site_yield_data failed: {e}")

            test_item_stats = calculate_fail_test_item_statistics(df, metadata)
            fail_test_items = [
                {'name': k, 'fail_count': v['fail_count'], 'percentage': v['percentage']}
                for k, v in list(test_item_stats.items())[:20]
            ]

            numeric_cols = [c for c in df.columns if df[c].dtype in ('int64', 'float64')]
            cols_with_limits = get_columns_with_limits(df, metadata)

            # 计算Bin×Site交叉表
            bin_table_data, bin_site_columns = compute_bin_site_table(df, fmt, site_col)

            # 计算参数CPK统计
            param_stats = compute_parameter_summary(df, metadata)

            # 生成质量警报
            quality_alerts = compute_quality_alerts(yield_pct, param_stats, site_yield_data)

            return Response({
                'file_id': datafile.id,
                'filename': datafile.filename,
                'program_name': datafile.program_name,
                'metrics': {
                    'total_rows': total_rows,
                    'pass_count': total_pass,
                    'fail_count': fail_count,
                    'yield_pct': yield_pct,
                    'format': fmt,
                },
                'bin_pie_data': bin_pie_data,
                'site_yield_data': site_yield_data,
                'fail_test_items': fail_test_items,
                'quality_overview': {
                    'numeric_items': len(numeric_cols),
                    'items_with_limits': len(cols_with_limits),
                    'site_count': len(site_yield_data) - 1 if site_yield_data else 0,
                    'bin_types': len(bin_stats),
                    'fail_bin_count': sum(1 for bv in bin_stats if bv != 1),
                },
                'bin_table_data': bin_table_data,
                'bin_site_columns': bin_site_columns,
                'param_stats': param_stats,
                'quality_alerts': quality_alerts,
            })
        except Exception as e:
            logger.exception(f"DashboardSummaryView error: {e}")
            return Response({'error': 'internal_error', 'detail': str(e)}, status=500)


class BatchReportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({'message': 'Batch report endpoint'})
