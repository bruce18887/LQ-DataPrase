"""histogram 选区（子集直方图）：解析 + 行级过滤。

选区是现有统计管线的前置过滤步骤：视图在既有过滤链（Bin1 / 测试项开关）之后、
compute_histogram_stats 之前调用 filter_df_by_selection。分箱强制 DR（子集自身
值域）由视图覆盖；CPK 锚定原规格限是 compute_histogram_stats 的既有口径。

守卫纪律（lessons R3/R4）：非法形态在解析层就 400，绝不放进计算层；数值入口
一律 pd.to_numeric(errors='coerce')，bool 不算数值。
"""
import math

import pandas as pd

from apps.analysis.services.statistics import get_serial_column
from apps.common.errors import error_response

MAX_SERIALS = 100_000


def _is_finite_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def parse_selection(raw):
    """request.data['selection'] → (selection | None, 400 响应 | None)。

    None/缺省 = 无选区（旧口径逐字不变）。value_range 的 lo/hi 各为有限数或
    null（null = 该侧无界，D6 兜底柱语义），至少一个非 null。
    """
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        return None, error_response('invalid_selection', 'selection 必须是对象')
    kind = raw.get('kind')
    if kind == 'value_range':
        lo, hi = raw.get('lo'), raw.get('hi')
        for v in (lo, hi):
            if v is not None and not _is_finite_number(v):
                return None, error_response('invalid_selection', 'value_range 边界必须是有限数或 null')
        if lo is None and hi is None:
            return None, error_response('invalid_selection', 'value_range 至少一侧有界')
        if lo is not None and hi is not None and lo > hi:
            return None, error_response('invalid_selection', 'value_range 下限不能大于上限')
        return {'kind': 'value_range',
                'lo': float(lo) if lo is not None else None,
                'hi': float(hi) if hi is not None else None}, None
    if kind == 'serials':
        serials = raw.get('serials')
        if not isinstance(serials, list) or not serials or len(serials) > MAX_SERIALS:
            return None, error_response('invalid_selection', f'serials 需要 1..{MAX_SERIALS} 个元素的数组')
        for s in serials:
            if isinstance(s, bool) or not isinstance(s, (int, float, str)):
                return None, error_response('invalid_selection', 'serials 元素只能是数值或字符串')
            if isinstance(s, float) and not math.isfinite(s):
                return None, error_response('invalid_selection', 'serials 不允许 NaN/inf')
        serial_col = raw.get('serial_col')
        if serial_col is not None and (not isinstance(serial_col, str) or serial_col == ''):
            return None, error_response('invalid_selection', 'serial_col 必须是字符串')
        out = {'kind': 'serials', 'serials': serials}
        if serial_col:
            out['serial_col'] = serial_col
        return out, None
    return None, error_response('invalid_selection', 'selection.kind 只能是 value_range 或 serials')


def filter_df_by_selection(df, param, selection):
    """按选区过滤行 → (df, 400 响应 | None)。param 已由 guard_all_missing 保证在列里。

    selection 必须非 None（调用方以 `if selection is not None` 守卫）；本函数不再重复判空。
    """
    if selection['kind'] == 'value_range':
        values = pd.to_numeric(df[param], errors='coerce')
        # pandas 3.x 的 between(None, …) 全 False（None 不是无界），用 ±inf 表达无界侧；
        # NaN 与 ±inf 比较仍为 False，脏值行自动落选。
        lo = selection['lo'] if selection['lo'] is not None else -math.inf
        hi = selection['hi'] if selection['hi'] is not None else math.inf
        out = df[values.between(lo, hi)]
    else:
        preferred = selection.get('serial_col')
        if preferred and preferred not in df.columns:
            return df, error_response('invalid_selection', 'serial_col 不在该文件的列中')
        serial_col = get_serial_column(df, preferred=preferred)
        if not serial_col:
            return df, error_response('invalid_selection', '该文件没有可用的序列列')
        col = df[serial_col]
        wanted = selection['serials']
        if pd.api.types.is_numeric_dtype(col):
            col_nums = pd.to_numeric(col, errors='coerce')
            wanted_nums = pd.to_numeric(pd.Series(wanted), errors='coerce').dropna()
            out = df[col_nums.isin(wanted_nums)]
        else:
            out = df[col.astype(str).isin([str(s) for s in wanted])]
    if len(out) == 0:
        return out, error_response('empty_selection', '选区内没有数据行')
    return out, None


def resolve_selection_serials(df):
    """value_range 选区命中行的序列号 + 列名 → (serials, col) | None。

    供前端把选区固化成 serials 跨参数重查（契约 Global Constraints #11）。
    numpy 标量转 Python 原生（int/float），字符串保持 str；丢弃 NaN/None，
    保持行序。无序列列或丢弃后为空 → None（响应两字段缺席，旧口径不变）。
    """
    serial_col = get_serial_column(df)
    if serial_col is None:
        return None
    serials = []
    for v in df[serial_col].tolist():
        if pd.isna(v):
            continue
        if hasattr(v, 'item'):  # numpy 标量 → 原生；str 无 item，原样保留
            v = v.item()
        serials.append(v)
    if not serials:
        return None
    return serials, serial_col
