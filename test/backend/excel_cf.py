"""读回生成的 xlsx 里「条件格式规则」与「列宽」的测试辅助。

excelize 只能**写**条件格式、没有读取接口，所以断言必须把工作簿落盘后用
openpyxl（或直接解 sheet xml）读回来。集中放这里，免得各测试文件抄一遍。

判定类断言不要只查"规则存在"——那样阈值写错照样通过；用 ``cf_verdict``
按 ``priority`` + ``stop_if_true`` 对给定数值**模拟 Excel 求值**，返回命中
规则的底色，口径（分档、边界）才真正被钉住。
"""
import io
import operator
import re
import zipfile

from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import coordinate_to_tuple, range_boundaries

_CF_OPS = {
    'greaterThan': operator.gt,
    'greaterThanOrEqual': operator.ge,
    'lessThan': operator.lt,
    'lessThanOrEqual': operator.le,
    'equal': operator.eq,
    'notEqual': operator.ne,
}


def sqref_contains(sqref, coord):
    """``coord``（如 ``'Y12'``）是否落在 ``sqref``（可含多段）范围内。"""
    row, col = coordinate_to_tuple(coord)
    for part in str(sqref).split():
        min_c, min_r, max_c, max_r = range_boundaries(part)
        if min_r <= row <= max_r and min_c <= col <= max_c:
            return True
    return False


def dxf_fill(rule):
    """条件格式规则的底色。

    excelize 写的是 solid pattern + ``bgColor``（不是 ``fgColor``），只看
    ``fgColor`` 会拿到 ``00000000`` 而误判成"CF 没生效"。
    """
    fill = getattr(getattr(rule, 'dxf', None), 'fill', None)
    if fill is None:
        return None
    for attr in ('bgColor', 'fgColor'):
        color = getattr(fill, attr, None)
        if color is not None and color.rgb and str(color.rgb) != '00000000':
            return str(color.rgb)[-6:].upper()
    return None


def cf_rules_for_cell(ws, coord):
    """覆盖该格的 CF 规则，按 ``priority`` 升序（Excel 的求值顺序）。"""
    for rng, rules in ws.conditional_formatting._cf_rules.items():
        if sqref_contains(rng.sqref, coord):
            return sorted(rules, key=lambda r: r.priority)
    return []


def cf_verdict(rules, value):
    """模拟 Excel：返回第一条命中规则的底色；都不命中返回 ``None``。"""
    for rule in rules:
        op = _CF_OPS.get(rule.operator)
        formula = list(rule.formula or [])
        if op is None or not formula:
            continue
        if op(value, float(formula[0])):
            return dxf_fill(rule)
    return None


def column_widths(data, sheet_index=0):
    """``{列字母: 宽度}``，直接解 sheet xml 的 ``<cols>``。

    openpyxl 对 excelize 合并写的 ``<col min max>`` 区间读回来不可靠
    （同区间内的列会报出不同值），所以这里自己展开区间。
    """
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read(f'xl/worksheets/sheet{sheet_index + 1}.xml').decode('utf-8')
    widths = {}
    for tag in re.findall(r'<col [^>]*>', xml):
        width = re.search(r'width="([\d.]+)"', tag)
        low = re.search(r'min="(\d+)"', tag)
        high = re.search(r'max="(\d+)"', tag)
        if not (width and low and high):
            continue
        for idx in range(int(low.group(1)), int(high.group(1)) + 1):
            widths[get_column_letter(idx)] = float(width.group(1))
    return widths
