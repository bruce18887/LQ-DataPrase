"""仪表板单文件汇总的可复用计算（从 views.py 抽出，供 API 与 HTML 报告共用）。

单一数据源：`DashboardSummaryView` 与 HTML 报表都调用 `compute_dashboard_summary`，
避免两处各自组装 payload 造成数字漂移。
"""

import logging
import math
import os
import threading
from collections import OrderedDict

import pandas as pd

from apps.analysis.services.statistics import (
    calculate_fail_bin_statistics,
    calculate_fail_test_item_statistics,
    get_site_column,
    get_columns_with_limits,
    compute_site_yield_data,
    get_bin_column_name,
    compute_pass_yield,
    filter_finite,
)
from apps.datafiles.utils import resolve_file_path

logger = logging.getLogger(__name__)

# 汇总结果缓存：进程内 LRU（容量 32 条）。
# 不用 functools.lru_cache —— df 不可 hash，且这里需要按条数淘汰与整体清空。
# 多线程并发访问（Django 线程池）下由锁保护；值本身是只读 payload。
_SUMMARY_CACHE_MAX_SIZE = 32
_summary_cache = OrderedDict()
_summary_cache_lock = threading.Lock()


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


def compute_test_item_overview(df, metadata, fail_stats, thresholds=None):
    """合并「CPK 参数表」与「Fail 测试项明细」：一行一个测试项。

    ``thresholds``（CpkThresholds）= 当前账号的 CPK 分级阈值，决定 cpk_level /
    cpk_color；None 时用默认 1.67/1.33/1.0。

    行集 = 有规格限的参数（全部，不再 Top10）∪ 出现 Fail 的测试项；
    行序 = df.columns 原始顺序（前端默认排序）。
    无规格限的 fail 项：统计列返回 None（前端显示 N/A）；
    无 fail 的参数：fail_count / percentage 返回 0。
    """
    from apps.analysis.services.statistics import compute_cpk, resolve_spec_limits
    from apps.common.user_settings import DEFAULT_CPK_THRESHOLDS

    th = thresholds or DEFAULT_CPK_THRESHOLDS

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
            # 透传 limits 已保 6 位小数的值，不再二次 round(…, 2)（0.002% 会被再吞一次）
            'percentage': float(fail_stats.get(param, {}).get('percentage', 0.0)),
        }

        if is_limit_param:
            try:
                series = df[param]
                if isinstance(series, pd.DataFrame):  # 重复列名兜底，取第一列
                    series = series.iloc[:, 0]
                # filter_finite 而非 to_numeric().dropna()：dropna 只滤 NaN 不滤 ±inf，
                # 而 ATE 把超量程读数写成字面 `inf` 时 pd.to_numeric 认它是合法浮点
                # （真实案例 BPD96079 / ETS88 / PG_RES 一列一格）—— mean 变 inf、
                # std(ddof=0) 变 nan，DRF 严格渲染器随后 500 整个仪表板。
                # 与分析页 25 个统计站点同源：非有限读数不参与统计。
                data_series = filter_finite(series)
                if len(data_series) > 0:
                    row['data_count'] = int(len(data_series))
                    row['mean'] = round(float(data_series.mean()), 4)
                    row['std'] = round(float(data_series.std(ddof=0)), 4)
                    row['min'] = round(float(data_series.min()), 4)
                    row['max'] = round(float(data_series.max()), 4)

                    # resolve_spec_limits 对缺失/占位/字面 'Min'/'Max' 返回 None。
                    # 旧写法用 parse_limit_string(..., 0.0, 0.0) + _has_valid_limit，
                    # 而 _has_valid_limit 只排除 ''/nan/none/n/a，**不排除 'Min'/'Max'**
                    # —— 于是这类参数把数据自身极值当 LSL/USL，CPK 数学上必然
                    # ≤ 0.5 而永远判红。此处沿用本函数既有约定：缺失侧以
                    # -inf/+inf 传入 compute_cpk 算单边 CPK，输出时转 None。
                    # 注意：行集口径（_has_valid_limit）刻意未改，只修限值取值，
                    # 以保证测试项总览表的行数与既有 e2e 断言不变。
                    lsl_raw, usl_raw = resolve_spec_limits(metadata, param)
                    lsl = float('-inf') if lsl_raw is None else lsl_raw
                    usl = float('inf') if usl_raw is None else usl_raw
                    row['lsl'] = round(lsl, 4) if lsl != float('-inf') else None
                    row['usl'] = round(usl, 4) if usl != float('inf') else None

                    if not (lsl == float('-inf') and usl == float('inf')):
                        cpk_result = compute_cpk(row['mean'], row['std'], lsl, usl,
                                                 **th.as_kwargs())
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


def compute_quality_alerts(yield_pct, param_stats, site_yield_data, thresholds=None):
    """生成质量警报

    ``thresholds``（CpkThresholds）里的 B 阈就是「低 CPK」警报的判定线，与
    分析页「仅低 CPK 项」筛选、总览表分级共用同一个账号设置值；文案内插该值，
    不再写死 1.33（否则用户改了阈值后警报与界面判定线不一致）。
    """
    from apps.common.user_settings import DEFAULT_CPK_THRESHOLDS

    cpk_b = (thresholds or DEFAULT_CPK_THRESHOLDS).cpk_b
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
    low_cpk_params = [p for p in param_stats if p['cpk'] < cpk_b]
    if low_cpk_params:
        alerts.append({
            'level': 'warning',
            'type': 'low_cpk',
            'message': f'{len(low_cpk_params)}个参数CPK不足 (CPK < {cpk_b:g})',
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


def compute_dashboard_summary(df, datafile, fmt, metadata, thresholds=None):
    """组装仪表板单文件汇总 payload（`/summary/` 响应体同形）。

    ``thresholds`` = 当前账号 CPK 分级阈值（get_cpk_thresholds(user)）；None 用默认。
    """
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
    # CPK 分级阈值取当前账号的系统设置，与「低 CPK」警报判定线同源，
    # 避免总览说 A 级而警报按 1.33 判。
    test_item_overview = compute_test_item_overview(
        df, metadata, test_item_stats, thresholds=thresholds)
    param_stats = _derive_param_stats(test_item_overview)

    # 生成质量警报
    quality_alerts = compute_quality_alerts(
        yield_pct, param_stats, site_yield_data, thresholds=thresholds)

    return {
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
    }


def _summary_cache_key(datafile, fmt, thresholds):
    """构造汇总缓存 key：文件身份 + 内容 mtime + CPK 阈值 + 展示字段。

    必须包含 mtime_ns：同一 file_id 重新上传/覆盖后内容会变，仅靠 id 会返回
    旧数字。os.stat 失败（文件被删/不可读）回落 0，仍可命中「无文件」口径。
    """
    from apps.common.user_settings import DEFAULT_CPK_THRESHOLDS

    th = thresholds or DEFAULT_CPK_THRESHOLDS
    try:
        mtime_ns = os.stat(resolve_file_path(datafile.file_path)).st_mtime_ns
    except OSError:
        mtime_ns = 0
    return (
        datafile.id,
        getattr(datafile, 'owner_id', 0),
        mtime_ns,
        th.cpk_a, th.cpk_b, th.cpk_c,
        datafile.filename,
        datafile.program_name,
        fmt,
    )


def get_dashboard_summary(datafile, df, fmt, metadata, thresholds=None):
    """``compute_dashboard_summary`` 的进程内 LRU 缓存包装（计算实现仍只有一份）。

    命中直接返回缓存对象；未命中先算再存入，超 32 条淘汰最久未用的一项。
    **返回值是共享只读对象，调用方不得修改**（现有调用方只读取/序列化）。
    """
    key = _summary_cache_key(datafile, fmt, thresholds)

    with _summary_cache_lock:
        cached = _summary_cache.get(key)
        if cached is not None:
            _summary_cache.move_to_end(key)  # 命中即刷新为最近使用
            return cached

    payload = compute_dashboard_summary(
        df, datafile, fmt, metadata, thresholds=thresholds)

    with _summary_cache_lock:
        _summary_cache[key] = payload
        _summary_cache.move_to_end(key)
        while len(_summary_cache) > _SUMMARY_CACHE_MAX_SIZE:
            _summary_cache.popitem(last=False)
    return payload


def summary_cache_stats() -> dict:
    """汇总缓存的条目读数，给 `/api/v1/metrics/`（apps/common/metrics.py）。

    只有条目数与上限：这个缓存按 key 计件（payload 几十 KB 量级），不像解析缓存那样
    按字节预算，所以这里报 `entries/max_entries` 就够 —— 编一个不存在的「字节数」
    只会让运维页显示一个假指标。
    """
    with _summary_cache_lock:
        return {'entries': len(_summary_cache), 'max_entries': _SUMMARY_CACHE_MAX_SIZE}


def clear_dashboard_summary_cache():
    """清空汇总缓存（供测试隔离；将来删除文件路径时也可复用）。"""
    with _summary_cache_lock:
        _summary_cache.clear()

