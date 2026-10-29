"""Buyoff Excel form builder using excelize.
Generates the single-sheet buyoff form with vertical FT/QA1/QA2 sections.
"""

import excelize
from apps.export.excel_theme import (
    make_header_style, make_data_style, make_unit_style, make_title_style,
    make_label_style, make_section_style, make_verdict_style,
    add_percent_verdict_rules, add_fail_if_nonpositive_rule,
    set_formula, enable_full_recalc,
)
from apps.buyoff.services import NA, parse_limit

# 百分比小数位：项目口径 6 位（apps/analysis/services/statistics/limits.py 的
# round(..., 6)），否则 1/50000 = 0.002% 会被 2 位小数归零。
PCT_DECIMALS = 6
# Result 百分比以**数值**存小数（0.06）+ 百分比数字格式，显示仍是 6.000000%。
# 存文本的话条件格式无法做数值比较。
PCT_NUM_FMT = "0." + "0" * PCT_DECIMALS + "%"

# Result 判定阈值（|百分比|）：> fail 判红、> warn 判黄、其余浅绿。
PCT_WARN_THRESHOLD = 5
PCT_FAIL_THRESHOLD = 10

# ── Stat rows definition ──
STAT_ROWS = [
    ("Lower Limit", "lower_limit", True),
    ("Upper Limit", "upper_limit", True),
    ("Min", "min", False),
    ("Max", "max", False),
    ("Range", "range", False),
    ("Mean", "mean", False),
    ("STD", "std", False),
    ("Mean-6*STD", "mean_minus_6std", False),
    ("Mean-3*STD", "mean_minus_3std", False),
    ("Mean+3*STD", "mean_plus_3std", False),
    ("Mean+6*STD", "mean_plus_6std", False),
    ("Ca", "ca", False),
    ("Cp", "cp", False),
    ("Cpk", "cpk", False),
]


def _na_style(f):
    """浅灰「无法判定」样式（与 pass/warn/fail 判定色明确区分）。"""
    return make_verdict_style(f, 'na')


def _write_na(f, sheet_name, cell, na_style):
    """写入 'N/A' + 灰色样式：表示「无法判定」，不参与红/黄/绿判定。"""
    f.set_cell_value(sheet_name, cell, NA)
    f.set_cell_style(sheet_name, cell, cell, na_style)


def _limit_of(datasets, fname, table, param):
    """从 dataset 的 metadata 里取并解析限值；不可用返回 ``None``。"""
    meta = datasets[fname].get('metadata') or {}
    return parse_limit(meta.get(table, {}).get(param))


def _qa_range(stats):
    """公差（upper - lower）；限值缺失或公差为 0 时返回 ``None``（无定义）。

    旧实现用 ``if qa_range == 0: qa_range = 1`` 把分母静默换成「1 个工程单位」，
    Result 列因此输出无意义大数并被 ``abs(pct) > 10`` 判红。
    """
    lower = stats.get('lower_limit')
    upper = stats.get('upper_limit')
    if lower is None or upper is None:
        return None
    span = upper - lower
    return span if span != 0 else None


def build_buyoff_form(f, role_mapping, common_items, all_stats, datasets, ordered_roles):
    """Build the buyoff form on an existing excelize file handle.

    Layout (single sheet):
      Row 1:  Merged title "Buyoff Analysis Report"
      Row 3-5: Column headers + test number + units
      FT section:  14 stat rows
      QA1 section: 14 stat rows
      QA2 section: 14 stat rows
      Results: 5 rows
       - FT-LL minus QA-LL
       - QA-UL minus FT-UL
       - (QA1 Mean - FT Mean)/range %
       - (QA2 Mean - FT Mean)/range %
       - Comments
      Freeze panes at C6

    四个分区（FT/QA1/QA2/Result）共用同一条中性灰竖带，靠竖排文字区分；
    判定结果只改字体色，不铺整格淡彩底。
    """
    sheet_name = "Buyoff data"
    sheet_list = f.get_sheet_list()
    if sheet_list:
        f.set_sheet_name(sheet_list[0], sheet_name)

    # ── Shared styles ──
    header_style = make_header_style(f, 10)
    data_style = make_data_style(f)
    unit_style = make_unit_style(f)
    title_style = make_title_style(f, 14)
    section_style = make_section_style(f)
    stat_label_style = make_label_style(f, 10, bold=True, align="left")

    # Result 区的判定底色由**条件格式**承载（改值后颜色自动跟随），
    # 所以这里只需要一个基色：|pct| 未过 warn 的浅绿。
    # 「无法判定」仍是静态灰底，不参与条件格式。
    pass_pct_style = make_verdict_style(f, 'pass', num_fmt=PCT_NUM_FMT)
    na_style = _na_style(f)

    # ── Layout setup ──
    test_col_start = 3  # A=section header, B=stat label, C+=test items
    last_col_letter = excelize.column_number_to_name(test_col_start - 1 + len(common_items))
    # 统计带的列字母表：`column_number_to_name` 每调一次都要跨一次 Go 边界
    # （实测实现见 excelize.py:6736），而统计带是「角色 × 14 行 × 参数」的三重循环。
    # 进循环前一次算表、循环内按下标取 ⇒ 换算次数只随**列数**增长，不再随行数增长。
    # 取值与原逐格换算逐字相同（同一个函数、同一批列号，从 test_col_start 起）。
    col_letters = [excelize.column_number_to_name(test_col_start + off)
                   for off in range(len(common_items))]

    # Get units
    test_units = {}
    for param in common_items:
        for role_name in ordered_roles:
            fname = role_mapping[role_name]
            unit = datasets[fname]['metadata'].get('units', {}).get(param, '')
            if unit:
                test_units[param] = unit
                break

    # ── Row 1: Title ──
    f.merge_cell(sheet_name, "A1", f"{last_col_letter}1")
    f.set_cell_value(sheet_name, "A1", "Buyoff Analysis Report")
    f.set_cell_style(sheet_name, "A1", "A1", title_style)
    f.set_row_height(sheet_name, 1, 30)

    # ── Row 3: Column headers ──
    f.set_cell_value(sheet_name, "A3", "Parameters")
    f.set_cell_style(sheet_name, "A3", "A3", header_style)
    f.set_cell_value(sheet_name, "B3", "Test Name")
    f.set_cell_style(sheet_name, "B3", "B3", header_style)
    for c_num, param in enumerate(common_items, start=test_col_start):
        cl = excelize.column_number_to_name(c_num)
        f.set_cell_value(sheet_name, f"{cl}3", param)
        f.set_cell_style(sheet_name, f"{cl}3", f"{cl}3", header_style)

    # ── Row 4: Test number ──
    f.set_cell_value(sheet_name, "A4", "")
    f.set_cell_style(sheet_name, "A4", "A4", header_style)
    f.set_cell_value(sheet_name, "B4", "Test Number")
    f.set_cell_style(sheet_name, "B4", "B4", header_style)
    for c_num in range(test_col_start, test_col_start + len(common_items)):
        cl = excelize.column_number_to_name(c_num)
        f.set_cell_style(sheet_name, f"{cl}4", f"{cl}4", header_style)

    # ── Row 5: Units ──
    f.set_cell_value(sheet_name, "A5", "")
    f.set_cell_style(sheet_name, "A5", "A5", unit_style)
    f.set_cell_value(sheet_name, "B5", "Units")
    f.set_cell_style(sheet_name, "B5", "B5", unit_style)
    for c_num, param in enumerate(common_items, start=test_col_start):
        cl = excelize.column_number_to_name(c_num)
        f.set_cell_value(sheet_name, f"{cl}5", test_units.get(param, ''))
        f.set_cell_style(sheet_name, f"{cl}5", f"{cl}5", unit_style)

    # ── Section writing loop ──
    row_idx = 6
    # 记下每个角色 上限/下限/均值 所在的行号，Result 区的公式要引用它们。
    role_rows = {}
    for role_name in ordered_roles:
        section_start = row_idx
        fname = role_mapping[role_name]
        ds = datasets[fname]

        for stat_name, stat_key, is_limit in STAT_ROWS:
            role_rows.setdefault(role_name, {})[stat_key] = row_idx
            # Col B: stat label
            f.set_cell_value(sheet_name, f"B{row_idx}", stat_name)
            f.set_cell_style(sheet_name, f"B{row_idx}", f"B{row_idx}", stat_label_style)

            # Cols C+: data for each test item
            # 样式按「连续同 id 的游程」成段下发。`set_cell_style(左上, 右下, id)` 是
            # **覆盖写**、不 append/merge（excelize.py:5432-5434），所以一段区间与这段里
            # 逐格同 id 调用是同一件事。等价性三条（由 test/backend/test_buyoff_sheet_shape.py
            # 逐条钉住：读回游程 / 下发区间 / 值-样式先后次序）：
            #   集合 —— 游程划分恰好覆盖本行的每个数据格，一格不多一格不少；
            #   id   —— 段内 id 全相同（段就是按 id 变化切的），单格段仍与现状同一调用；
            #   次序 —— 先只判定这一格的「值 + 样式」，不落 FFI；游程在**下一格的值写下去
            #           之前**收尾 ⇒ 某段的下发时机正是「段末那格的值之后、下一格的值之前」，
            #           与原「值(c)→样式(c)→值(c+1)」逐字同一相对次序（拆成「先写完值再写
            #           样式」两趟遍历就会破坏这一条，测试里有对应的次序判据）。
            #           本行 C.. 列域之后没有第二次样式写：B 列的行名（stat_label_style）在本段
            #           之上单独下发、A 列的分区名（section_style）在合并区段时单独下发，两者都
            #           不在这个列域内；Result 区又是另外一批行 ⇒ 「最后一写生效」的那一写
            #           没有被挪到别处。
            run_start = None   # 未下发游程的起始下标（common_items 的 enumerate 下标）
            run_style = None
            for idx, param in enumerate(common_items):
                cl = col_letters[idx]
                cell = f"{cl}{row_idx}"

                # 先只判定「这一格写什么值 + 用哪个样式」，一次 FFI 都不发；
                # 值的落盘挪到游程收尾之后（见上面「次序」那条等价性）。
                if is_limit:
                    table = 'mins' if stat_name == "Lower Limit" else 'maxs'
                    meta = ds.get('metadata') or {}
                    raw = meta.get(table, {}).get(param)
                    if raw is None or (isinstance(raw, str) and not raw.strip()):
                        # 「无法判定」＝ 静态 'N/A' + 浅灰底（与 _write_na 同一语义，
                        # 只是样式改由游程统一下发）
                        value, style_id = NA, na_style
                    else:
                        # 数值限值写成 float（而非原字符串）：Result 公式要对这两格做算术。
                        parsed = parse_limit(raw)
                        value, style_id = (parsed if parsed is not None else raw), data_style
                elif param in all_stats.get(role_name, {}):
                    val = all_stats[role_name][param].get(stat_key)
                    if val is None or val == NA:
                        value, style_id = NA, na_style
                    else:
                        if isinstance(val, float):
                            val = round(val, 6)
                        value, style_id = val, data_style
                else:
                    # 三分支的最后一条（else：该角色没有这个参数的 stats）：只有样式、不写值。
                    # 三个分支可能写出的值里没有 None
                    # （val is None 已在上面归成 'N/A'；parsed is None 时写的是 raw），
                    # 所以 None 可以安全地当「这一格不写值」的哨兵。
                    value, style_id = None, data_style

                if run_start is None:
                    run_start, run_style = idx, style_id
                elif style_id != run_style:
                    f.set_cell_style(sheet_name, f"{col_letters[run_start]}{row_idx}",
                                     f"{col_letters[idx - 1]}{row_idx}", run_style)
                    run_start, run_style = idx, style_id
                if value is not None:
                    f.set_cell_value(sheet_name, cell, value)
            if run_start is not None:
                f.set_cell_style(sheet_name, f"{col_letters[run_start]}{row_idx}",
                                 f"{col_letters[-1]}{row_idx}", run_style)

            row_idx += 1

        section_end = row_idx - 1

        # Merge col A for section header
        f.merge_cell(sheet_name, f"A{section_start}", f"A{section_end}")
        f.set_cell_value(sheet_name, f"A{section_start}", role_name)
        f.set_cell_style(sheet_name, f"A{section_start}", f"A{section_start}", section_style)

        # Blank row between sections
        row_idx += 1

    # ── Results section ──
    results_start = row_idx
    margin = 5
    results_end = results_start + margin - 1

    f.merge_cell(sheet_name, f"A{results_start}", f"A{results_end}")
    f.set_cell_value(sheet_name, f"A{results_start}", "Result")
    f.set_cell_style(sheet_name, f"A{results_start}", f"A{results_start}", section_style)

    # Result row 1: FT Lower Limit - QA Lower Limit
    f.set_cell_value(sheet_name, f"B{row_idx}", "FT Lower Limit - QA Lower Limit")
    f.set_cell_style(sheet_name, f"B{row_idx}", f"B{row_idx}", stat_label_style)
    for c_num, param in enumerate(common_items, start=test_col_start):
        cl = excelize.column_number_to_name(c_num)
        cell = f"{cl}{row_idx}"
        if 'FT' in role_mapping and 'QA1' in role_mapping:
            ft_ll = _limit_of(datasets, role_mapping['FT'], 'mins', param)
            qa_ll = _limit_of(datasets, role_mapping['QA1'], 'mins', param)
            if ft_ll is None or qa_ll is None:
                # 限值缺失/不可解析 → 「无法判定」，不能当 diff=0 渲染成红色 FAIL。
                _write_na(f, sheet_name, cell, na_style)
                continue
            ft_row = role_rows['FT']['lower_limit']
            qa_row = role_rows['QA1']['lower_limit']
            set_formula(f, sheet_name, cell, f"=ROUND({cl}{ft_row}-{cl}{qa_row},6)")
            f.set_cell_style(sheet_name, cell, cell, data_style)
        else:
            _write_na(f, sheet_name, cell, na_style)
    add_fail_if_nonpositive_rule(f, sheet_name, f"C{row_idx}:{last_col_letter}{row_idx}")
    row_idx += 1

    # Result row 2: QA Upper Limit - FT Upper Limit
    f.set_cell_value(sheet_name, f"B{row_idx}", "QA Upper Limit - FT Upper Limit")
    f.set_cell_style(sheet_name, f"B{row_idx}", f"B{row_idx}", stat_label_style)
    for c_num, param in enumerate(common_items, start=test_col_start):
        cl = excelize.column_number_to_name(c_num)
        cell = f"{cl}{row_idx}"
        if 'FT' in role_mapping and 'QA1' in role_mapping:
            ft_ul = _limit_of(datasets, role_mapping['FT'], 'maxs', param)
            qa_ul = _limit_of(datasets, role_mapping['QA1'], 'maxs', param)
            if ft_ul is None or qa_ul is None:
                _write_na(f, sheet_name, cell, na_style)
                continue
            qa_row = role_rows['QA1']['upper_limit']
            ft_row = role_rows['FT']['upper_limit']
            set_formula(f, sheet_name, cell, f"=ROUND({cl}{qa_row}-{cl}{ft_row},6)")
            f.set_cell_style(sheet_name, cell, cell, data_style)
        else:
            _write_na(f, sheet_name, cell, na_style)
    add_fail_if_nonpositive_rule(f, sheet_name, f"C{row_idx}:{last_col_letter}{row_idx}")
    row_idx += 1

    # Result row 3: (QA1 Mean - FT Mean) / range
    f.set_cell_value(sheet_name, f"B{row_idx}", "(QA1 Mean - FT Mean)/ (QA Upper Limit - QA Lower Limit)")
    f.set_cell_style(sheet_name, f"B{row_idx}", f"B{row_idx}", stat_label_style)
    for c_num, param in enumerate(common_items, start=test_col_start):
        cl = excelize.column_number_to_name(c_num)
        cell = f"{cl}{row_idx}"
        if ('FT' in role_mapping and 'QA1' in role_mapping
                and param in all_stats.get('QA1', {})
                and param in all_stats.get('FT', {})):
            qa_range = _qa_range(all_stats['QA1'][param])
            if qa_range is None:
                _write_na(f, sheet_name, cell, na_style)
                continue
            # 公式存分数（小数），显示交给 pass_pct_style 的百分比格式；
            # ROUND 位数与旧 Python 口径（PCT_DECIMALS + 2）一致。
            m_qa = role_rows['QA1']['mean']
            m_ft = role_rows['FT']['mean']
            ul = role_rows['QA1']['upper_limit']
            ll = role_rows['QA1']['lower_limit']
            set_formula(f, sheet_name, cell,
                        f"=ROUND(({cl}{m_qa}-{cl}{m_ft})/({cl}{ul}-{cl}{ll}),{PCT_DECIMALS + 2})")
            f.set_cell_style(sheet_name, cell, cell, pass_pct_style)
        else:
            _write_na(f, sheet_name, cell, na_style)
    add_percent_verdict_rules(f, sheet_name, f"C{row_idx}:{last_col_letter}{row_idx}",
                              warn=PCT_WARN_THRESHOLD, fail=PCT_FAIL_THRESHOLD)
    row_idx += 1

    # Result row 4: (QA2 Mean - FT Mean) / range
    f.set_cell_value(sheet_name, f"B{row_idx}", "(QA2 Mean - FT Mean)/ (QA Upper Limit - QA Lower Limit)")
    f.set_cell_style(sheet_name, f"B{row_idx}", f"B{row_idx}", stat_label_style)
    for c_num, param in enumerate(common_items, start=test_col_start):
        cl = excelize.column_number_to_name(c_num)
        cell = f"{cl}{row_idx}"
        if ('FT' in role_mapping and 'QA2' in role_mapping
                and param in all_stats.get('QA2', {})
                and param in all_stats.get('FT', {})):
            qa_range = _qa_range(all_stats['QA2'][param])
            if qa_range is None:
                _write_na(f, sheet_name, cell, na_style)
                continue
            m_qa = role_rows['QA2']['mean']
            m_ft = role_rows['FT']['mean']
            ul = role_rows['QA2']['upper_limit']
            ll = role_rows['QA2']['lower_limit']
            set_formula(f, sheet_name, cell,
                        f"=ROUND(({cl}{m_qa}-{cl}{m_ft})/({cl}{ul}-{cl}{ll}),{PCT_DECIMALS + 2})")
            f.set_cell_style(sheet_name, cell, cell, pass_pct_style)
        else:
            _write_na(f, sheet_name, cell, na_style)
    add_percent_verdict_rules(f, sheet_name, f"C{row_idx}:{last_col_letter}{row_idx}",
                              warn=PCT_WARN_THRESHOLD, fail=PCT_FAIL_THRESHOLD)
    row_idx += 1

    # Result row 5: Comments
    f.set_cell_value(sheet_name, f"B{row_idx}", "Comments")
    f.set_cell_style(sheet_name, f"B{row_idx}", f"B{row_idx}", stat_label_style)
    for c_num in range(test_col_start, test_col_start + len(common_items)):
        cl = excelize.column_number_to_name(c_num)
        cell = f"{cl}{row_idx}"
        f.set_cell_style(sheet_name, cell, cell, data_style)
    row_idx += 2  # blank rows

    # ── Freeze panes ──
    f.set_panes(sheet_name, excelize.Panes(
        freeze=True, split=False,
        x_split=2, y_split=5,
        top_left_cell="C6",
    ))

    # ── Column widths ──
    f.set_col_width(sheet_name, "A", "A", 8)
    f.set_col_width(sheet_name, "B", "B", 22)
    for c_num in range(test_col_start, test_col_start + len(common_items)):
        cl = excelize.column_number_to_name(c_num)
        f.set_col_width(sheet_name, cl, cl, 18)

    # Result 区是公式，Excel 打开时须重算（否则在重算前显示空白）。
    enable_full_recalc(f)
