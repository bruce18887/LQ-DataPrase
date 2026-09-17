"""读取 excelize 生成的**公式**单元格：取公式串与算值。

excelize 写公式时不落缓存值，``get_cell_value`` 读回空串；要拿到结果得用
``calc_cell_value`` —— 它返回的是**格式化后的显示值**（例如百分比格是
``'15.492%'``，不是 ``0.154919``）。本模块把这两件事收口，供 buyoff / gage
的测试共用。

注意：``calc_cell_value`` 是 excelize 自带的计算器，个别表达式组合它解析不了
（实测 ``ROUND(6*SQRT(x/y),4)`` 会算成 0，改成 ``ROUND(SQRT(x/y)*6,4)`` 正常）。
测试若断言某条公式的算值踩到这类情况，需要换一种写法。
"""


def open_handle(data):
    """从 xlsx 字节重开一个 excelize 句柄（调用方负责 ``close()``）。"""
    import excelize
    return excelize.open_reader(data)


def formula_of(handle, sheet, ref):
    """取公式串（不含前导 ``=``）；非公式格返回 ``''``。"""
    return handle.get_cell_formula(sheet, ref)


def calc(handle, sheet, ref):
    """返回单元格/公式的**格式化显示值**（字符串）。"""
    return handle.calc_cell_value(sheet, ref)


def as_number(text):
    """把 ``calc`` 的显示值解析成 float：``'%'`` 结尾按百分数还原，空返回 None。"""
    if text is None or text == '':
        return None
    t = str(text).strip()
    if t.endswith('%'):
        return float(t[:-1]) / 100
    return float(t)
