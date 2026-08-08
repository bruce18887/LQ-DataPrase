import logging
import math
import os

import pandas as pd
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from apps.datafiles.models import DataFile
from apps.analysis.services.statistics import (
    calculate_fail_bin_statistics,
    calculate_fail_test_item_statistics,
    get_site_column,
    get_columns_with_limits,
    compute_site_yield_data,
    get_bin_column_name,
    compute_pass_yield,
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


def _has_valid_limit(limit_str) -> bool:
    """规格限字符串是否为有效值（非空且非 NaN/None/N/A 等关键字）。"""
    if limit_str is None:
        return False
    s = str(limit_str).strip()
    return bool(s) and s.lower() not in ('', 'nan', 'none', 'n/a')


def compute_test_item_overview(df, metadata, fail_stats):
    """合并「CPK 参数表」与「Fail 测试项明细」：一行一个测试项。

    行集 = 有规格限的参数（全部，不再 Top10）∪ 出现 Fail 的测试项；
    行序 = df.columns 原始顺序（前端默认排序）。
    无规格限的 fail 项：统计列返回 None（前端显示 N/A）；
    无 fail 的参数：fail_count / percentage 返回 0。
    """
    from apps.analysis.services.statistics import compute_cpk, parse_limit_string

    # 限值判定沿用原 compute_parameter_summary 的宽松语义：单边限参数也保留
    # （缺失侧以 -inf/+inf 传入 compute_cpk 计算单边 CPK，输出时转 None）。
    fail_set = set(fail_stats)
    rows = []

    for param in df.columns:
        has_valid_lsl = _has_valid_limit(metadata.get('mins', {}).get(param, ''))
        has_valid_usl = _has_valid_limit(metadata.get('maxs', {}).get(param, ''))
        is_limit_param = has_valid_lsl or has_valid_usl

        if not is_limit_param and param not in fail_set:
            continue

        row = {
            'name': param,
            'data_count': 0,
            'mean': None, 'std': None, 'min': None, 'max': None,
            'lsl': None, 'usl': None,
            'cpk': None, 'cpk_level': None, 'cpk_color': None,
            'unit': metadata.get('units', {}).get(param, ''),
            'fail_count': int(fail_stats.get(param, {}).get('fail_count', 0)),
            'percentage': round(float(fail_stats.get(param, {}).get('percentage', 0.0)), 2),
        }

        if is_limit_param:
            try:
                series = df[param]
                if isinstance(series, pd.DataFrame):  # 重复列名兜底，取第一列
                    series = series.iloc[:, 0]
                data_series = pd.to_numeric(series, errors='coerce').dropna()
                if len(data_series) > 0:
                    row['data_count'] = int(len(data_series))
                    row['mean'] = round(float(data_series.mean()), 4)
                    row['std'] = round(float(data_series.std(ddof=0)), 4)
                    row['min'] = round(float(data_series.min()), 4)
                    row['max'] = round(float(data_series.max()), 4)

                    lsl = parse_limit_string(
                        str(metadata['mins'][param]), data_series, 0.0, 0.0) if has_valid_lsl else float('-inf')
                    usl = parse_limit_string(
                        str(metadata['maxs'][param]), data_series, 0.0, 0.0) if has_valid_usl else float('inf')
                    row['lsl'] = round(lsl, 4) if lsl != float('-inf') else None
                    row['usl'] = round(usl, 4) if usl != float('inf') else None

                    if not (lsl == float('-inf') and usl == float('inf')):
                        cpk_result = compute_cpk(row['mean'], row['std'], lsl, usl)
                        if math.isfinite(cpk_result['cpk']):  # 防 inf 破坏 JSON
                            row['cpk'] = round(cpk_result['cpk'], 3)
                            row['cpk_level'] = cpk_result['cpk_level']
                            row['cpk_color'] = cpk_result['cpk_color']
            except Exception as e:
                logger.warning(f"compute_test_item_overview failed for {param}: {e}")

        rows.append(row)

    return rows


def _derive_param_stats(overview_rows):
    """从 overview 派生原 param_stats 字段契约（CPK 升序，最差在前）。

    与旧 compute_parameter_summary 的键集/舍入一致，compute_quality_alerts
    依赖其 cpk 键；从 overview 派生保证两处数据不会漂移。
    """
    return sorted(
        (
            {
                'param': r['name'], 'mean': r['mean'], 'std': r['std'],
                'cpk': r['cpk'], 'cpk_level': r['cpk_level'], 'cpk_color': r['cpk_color'],
                'unit': r['unit'], 'lsl': r['lsl'], 'usl': r['usl'],
            }
            for r in overview_rows if r['cpk'] is not None
        ),
        key=lambda x: x['cpk'],
    )


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

            df, metadata, fmt = get_cached_parsed_file(datafile.id, request.user.pk, datafile)
            if df is None:
                return Response({'error': 'parse_failed'})

            total_rows = df.shape[0]
            bin_stats = calculate_fail_bin_statistics(df, metadata)
            site_col = get_site_column(df)

            yield_result = compute_pass_yield(bin_stats, total_rows)
            total_pass = yield_result['pass_count']
            fail_count = yield_result['fail_count']
            yield_pct = yield_result['yield_pct']

            bin_pie_data = []
            for bv, s in bin_stats.items():
                try:
                    label = f"Bin {int(float(bv))}" if bv is not None else "Bin 0"
                except Exception:
                    label = f"Bin {bv}"
                bin_pie_data.append({'name': label, 'value': s['count']})

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

            # 合并参数CPK统计与Fail测试项明细为测试项总览（行序=原始列序）
            test_item_overview = compute_test_item_overview(df, metadata, test_item_stats)
            param_stats = _derive_param_stats(test_item_overview)

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
                'test_item_overview': test_item_overview,
                'quality_alerts': quality_alerts,
            })
        except Http404:
            # get_object_or_404 的 404 语义不能被兜底吞掉
            raise
        except Exception as e:
            logger.exception(f"DashboardSummaryView error: {e}")
            return Response({'error': 'internal_error', 'detail': str(e)}, status=500)