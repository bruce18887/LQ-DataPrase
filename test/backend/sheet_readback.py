"""A5 两段「工作表下发形状」回归共用的 **sheet XML 读回**（判据本体在
``test_buyoff_sheet_shape.py`` 与 ``test_gage_sheet_shape.py``，本模块只被这两个文件消费）。

原先这两份读回各自实现，实测 **78 行逐字重复且已经漂移**：一份拿 sheet XML 的 ``r=``
属性当格子地址，另一份由 ``(行, 列)`` 坐标反推 ref（顺带每格多跨一次 Go 边界 —— 正是
本次要消掉的那类调用）。合并成一份后只保留 ``r=`` 那个口径。

文件名不以 ``test`` 开头 ⇒ Django ``DiscoverRunner`` 的 ``test*.py`` 发现规则不会把它
当用例收集（同 ``test/backend/excel_cf.py``、``test/backend/buyoff_sheet_fixture.py`` 的先例）。
口径写在 ``test/backend/`` 而不 import ``tasks/perf-review-2026-10-27/``：``tasks/`` 不入库
（``.gitignore`` 的 ``/tasks/*``），CI 的干净检出里那个路径根本不存在，判据必须能独立跑。

三条口径都是承重件，改动会让判据**静默失效**（不是注释掉就没事的那种）：

1. **格子集合只信 sheet XML 里真实出现的 ``<c r=".." s="..">``，不信 ``<dimension>``**：
   excelize 写出的 ``<dimension ref="A1">`` 是错的（单个 ref，连统计带的第一行都盖不住），
   信它就会漏掉「有样式但空值」的格子，而那些格子正是游程区间的落点 ⇒ 漏读等于没有判据。
   这条**自证**钉在 ``test_buyoff_sheet_shape.BuyoffReadbackEquivalenceTests`` 的
   ``test_scanner_sees_styled_blank_cells_that_dimension_omits``；本模块因此把 ``refs`` 与
   ``dimension`` 一起交出去（两者都不进 digest，加了不改钉值）。
2. **样式一律取内容**（``get_style`` 解析后哈希）而不是样式 id：id 会随 ``new_style``
   调用顺序平移，内容平移不了，判据要的是「每格长什么样」。
3. **列宽以 XML 的 ``<col min max width>`` 为准并自己展开区间**：openpyxl 读 excelize
   合并写的 ``<col min max>`` 区间不可靠（同区间内的列会报出不同值，理由与这一手写法见
   ``test/backend/excel_cf.py`` 的 ``column_widths``）。下发侧那一口径（``set_col_width``
   的调用记录）留在两个测试文件各自的 spy 档里 ⇒ 读回与下发双口径互不遮蔽。
"""
import dataclasses
import hashlib
import io
import json
import re
import zipfile

import excelize

_C_TAG = re.compile(r'<c\b[^>]*?(?:/>|>.*?</c>)', re.S)
_ATTR = re.compile(r'([\w:]+)="([^"]*)"')
_COL_TAG = re.compile(r'<col\b[^>]*?/?>')
_DIM_TAG = re.compile(r'<dimension\b[^>]*?/?>')


def canonical(obj):
    """稳定序列化的 JSON —— digest 与「快照是否被改」的比对都用它。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def plain(value):
    """``Style`` 这类 dataclass → 可 JSON 化的嵌套 dict/list（样式**内容**哈希的前置）。"""
    if dataclasses.is_dataclass(value):
        return {k: plain(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def style_key(handle, style_id, cache):
    """样式 id → 12 位**内容**哈希；同一 id 只解析一次（``get_style`` 也要跨 Go 边界）。"""
    if style_id not in cache:
        cache[style_id] = sha(canonical(plain(handle.get_style(style_id))))[:12]
    return cache[style_id]


def runs_from_mapping(col_to_value):
    """``{列号: 值}`` → 连续同值的 ``[[起列, 末列, 值], ...]``（自左至右）。

    读回侧拿它摊「每行实际长什么样的样式游程」，预言侧（``buyoff_sheet_fixture`` 的
    输入模型）拿它摊「按输入帧该下发哪些游程」—— 同一个式子，两边共用才比得出边界。
    """
    segments = []
    prev_col = prev_value = None
    for col in sorted(col_to_value):
        value = col_to_value[col]
        if segments and value == prev_value and col == prev_col + 1:
            segments[-1][1] = col
        else:
            segments.append([col, col, value])
        prev_col, prev_value = col, value
    return segments


def sheet_parts(data):
    """``{sheet 名: '/xl/worksheets/sheetN.xml'}``，走 workbook.xml + rels 显式映射。"""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        wb_xml = z.read('xl/workbook.xml').decode('utf-8')
        rels = z.read('xl/_rels/workbook.xml.rels').decode('utf-8')
    targets = {}
    for tag in re.finditer(r'<Relationship\b[^>]*?>', rels):
        attrs = dict(_ATTR.findall(tag.group(0)))
        targets[attrs.get('Id')] = '/xl/' + attrs.get('Target', '').lstrip('/')
    parts = {}
    for tag in re.finditer(r'<sheet\b[^>]*?/?>', wb_xml):
        attrs = dict(_ATTR.findall(tag.group(0)))
        rid = (attrs.get('{http://schemas.openxmlformats.org/officeDocument/2006/'
                         'relationships}id') or attrs.get('r:id'))
        if attrs.get('name') and rid in targets:
            parts[attrs['name']] = targets[rid]
    return parts


def col_widths_from_xml(xml_text):
    """展开 ``<col min max width>`` 区间为 ``{列字母: 宽度}``（口径 3，不信 openpyxl）。"""
    widths = {}
    for tag in _COL_TAG.finditer(xml_text):
        attrs = dict(_ATTR.findall(tag.group(0)))
        width, low, high = attrs.get('width'), attrs.get('min'), attrs.get('max')
        if not (width and low and high):
            continue
        for idx in range(int(low), int(high) + 1):
            widths[excelize.column_number_to_name(idx)] = float(width)
    return widths


def readback(data):
    """工作簿字节 → ``{'digest', 'body', 'refs', 'dimension'}``（口径 1/2/3 见模块文档）。

    ``body = {'sheet_order': [...], 'sheets': {名: {cells, nonempty_styles, runs,
    widths, merges}}}``；``digest`` 是它的 ``canonical`` 哈希。``refs``（``{(行, 列)}``）与
    ``dimension``（XML 里那个 ref 属性原文）只服务「扫描器自证」那条用例，不进 digest。
    """
    handle = excelize.open_reader(data)
    parts = sheet_parts(data)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml_by_part = {'/' + name: z.read(name).decode('utf-8')
                       for name in z.namelist()
                       if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', name)}
    key_cache = {}
    sheets = {}
    refs = {}
    dimension = {}
    try:
        for name, part in parts.items():
            xml_text = xml_by_part.get(part)
            if not xml_text:
                raise RuntimeError(f'工作表 {name!r} 没映射到 sheet xml，读回会静默变空表')
            tag = _DIM_TAG.search(xml_text)
            dimension[name] = (dict(_ATTR.findall(tag.group(0))).get('ref')
                               if tag else None)
            per_row = {}
            nonempty_seq = []
            seen = []
            for cell_tag in _C_TAG.finditer(xml_text):
                text = cell_tag.group(0)
                attrs = dict(_ATTR.findall(text.split('>', 1)[0]))
                ref = attrs.get('r')
                if not ref:
                    continue
                # cell_name_to_coordinates 返回 (列号, 行号)，顺序搞反会让行列域整体错位。
                col_idx, row = excelize.cell_name_to_coordinates(ref)
                nonempty = (bool(re.search(r'<v>.*?</v>', text, re.S))
                            or bool(re.search(r'<f[ >]', text)))
                seen.append((row, col_idx, ref, nonempty))
            for row, col_idx, ref, nonempty in seen:
                key = style_key(handle, handle.get_cell_style(name, ref), key_cache)
                per_row.setdefault(row, {})[col_idx] = key
                if nonempty:
                    nonempty_seq.append((row, col_idx, ref, key))
            sheets[name] = {
                'cells': len(seen),
                # 非空格子按 (行, 列) 升序的「单元格地址 + 样式内容」序列 —— 判据 ② 的主判据
                'nonempty_styles': [[r[2], r[3]] for r in sorted(nonempty_seq)],
                'runs': {str(row): runs_from_mapping(mapping)
                         for row, mapping in sorted(per_row.items())},
                'widths': col_widths_from_xml(xml_text),
                'merges': sorted([m.get_start_axis(), m.get_end_axis()]
                                 for m in handle.get_merge_cells(name)),
            }
            refs[name] = {(row, col_idx) for row, col_idx, _ref, _n in seen}
    finally:
        handle.close()
    body = {'sheet_order': list(sheets), 'sheets': sheets}
    return {'digest': sha(canonical(body)), 'body': body,
            'refs': refs, 'dimension': dimension}
