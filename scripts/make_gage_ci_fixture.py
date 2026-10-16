#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""派生「虚拟化」的 gage datalog CI 夹具。

    输入（只读，绝不写回）：Data/SampleData/Gage/gage_m_S1.csv … gage_m_S4.csv
    输出：test/fixtures/gage/ 下的同名 4 个 CSV + MANIFEST.txt

**这份夹具是给 CI 的虚拟化副本；真实样例在 Data/ 下、不入库**（仓库是公开的，
而 datalog 头里带内部绝对路径 / 机台主机名 / 账号 / 测试项名）。改完测试项名或
GENERAL 头之后重跑本脚本即可再生成，产物字节级可复现（幂等）。

虚拟化范围（只改「标识符」，不改任何数值与结构）：
  1. 332 个测试项名 → PAR0001…PAR0332，**按位置**改（PARAMINFO 段第 i 行（i 从 1 起，
     L97..L428）的第 1 字段，与表头 L431 的第 13+i 个字段（1-based，前 13 列是系统列，
     故第 1 个参数落在第 14 列）是同一个参数的两处出现）。
     ⚠ 严禁按字符串全文替换：实测有 48 个真实名是另一个真实名的严格前缀
     （BG1⊂BG10、CON_SW⊂CON_SW_POST、OC1、TEMP、R_Kelvin_VIN⊂…_POST 等），
     串替换会互相啃掉。
  2. [GENERAL] 里 9 个带内部信息的键的**值字段**：Program / TestFile（内部绝对
     路径 + 料号）、Tester_Name / Customer_ID / Operator / Op_Type / HandlerName /
     DUTBox_Type / Software_Ver。键名与行号原样。
     Program/TestFile 的假值刻意保持解析器依赖的形状（见 FAKE_PROGRAM_PATH 注释）。

承重约束（动了就引入新的 CI 红，脚本会硬断言它们没被动过）：
  * Tester_Type=CTA8290DPlus、Software_Name=CTA8290DPlus 原样保留 ——
    parsers/base.py identify_format() 靠 file_content.lower() 里的子串 'cta8290d'
    判格式（只读文件头 4096 字符），改掉就变 Unknown。
  * LotID 保持 gage_m_S1…gage_m_S4（测试与 e2e 都靠文件名）。
  * Tester_ID 的 140000 原样 —— 它在 S1 全文出现 15 次，其中 14 次是数据值
    1.140000 的巧合，所以绝不做全文替换。
  * 所有数值、行数、[SUMMARY]/[SWBININFO]/[HARDWAREBIN] 原文、L70 无尾逗号的
    [SUMMARY] 段头、L429 空行、[Data], 所在行号（L430）、L431 前 13 个系统列名、
    Unit/Min/Max 三行字面值、列顺序、日期时间戳，全部不动。
  * 4 个 CSV 夹具仍是 CRLF 行尾、无 BOM、纯 ASCII（MANIFEST.txt 是给人看的中文
    审计说明，UTF-8 + CRLF，不参与「纯 ASCII」这条约束）。

⚠ 两条现场提醒（2026-10-16 实测）：
  * `.gitignore` 里有 `/test/*`，夹具目录默认被忽略 —— 一条 `!/test/fixtures/` 就够
    （`*` 不跨 `/`，所以它只挡一层；放开该层后其下文件不再被任何规则命中。2026-10-16 实测，
    与本仓 `!/test/backend/` 能跟踪 76 个文件同理）。
  * 同文件里的 `!/Data/SampleData/Gage/` 是把**真实**样例（含内部绝对路径、机台主机名、
    内部账号）放开入库的。那与虚拟化夹具的目的相反：一旦推到
    公开仓库，真实头信息就外发了。改用夹具后应把这条放开收回。

用法：
    python scripts/make_gage_ci_fixture.py
    python scripts/make_gage_ci_fixture.py --input-dir … --output-dir …
"""

from __future__ import annotations

import argparse
import os
import re
import sys

# --------------------------------------------------------------------------
# 路径与文件名
# --------------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_INPUT_DIR = os.path.join(REPO_ROOT, "Data", "SampleData", "Gage")
DEFAULT_OUTPUT_DIR = os.path.join(REPO_ROOT, "test", "fixtures", "gage")

FIXTURE_FILES = ("gage_m_S1.csv", "gage_m_S2.csv", "gage_m_S3.csv", "gage_m_S4.csv")

# --------------------------------------------------------------------------
# 结构常量（行号 1-based；已对 4 个真实文件逐一实测，完全同构）
# --------------------------------------------------------------------------
EXPECTED_TOTAL_LINES = 534          # 534 行正文 + 文件尾 CRLF
PARAM_COUNT = 332                   # 测试项个数
SYSTEM_COL_COUNT = 13               # L431 表头前 13 个系统列（不许动）
EXPECTED_FIELD_COUNT = 346          # L431 字段数 = 13 系统 + 332 参数 + 1 尾部空字段
PARAMINFO_FIELD_COUNT = 12          # PARAMINFO 每行 12 字段

LINE_GENERAL_HEADER = 1             # [GENERAL],
LINE_WAFERCONFIG = 57               # [WAFERCONFIG],
LINE_SUMMARY = 70                   # [SUMMARY]  ← 唯一没有尾逗号的段头
LINE_SWBININFO = 74                 # [SWBININFO],
LINE_HARDWAREBIN = 92               # [HARDWAREBIN],
LINE_PARAMINFO_HEADER = 96          # [PARAMINFO],
LINE_PARAMINFO_FIRST = 97           # 第 1 个测试项
LINE_PARAMINFO_LAST = 428           # 第 332 个测试项
LINE_BLANK_BEFORE_DATA = 429        # 空行
LINE_DATA_MARKER = 430              # [Data],,,,,…
LINE_DATA_HEADER = 431              # 表头行
LINE_DATA_UNIT = 432                # Unit 行
LINE_DATA_MIN = 433                 # Min 行
LINE_DATA_MAX = 434                 # Max 行
LINE_DATA_FIRST = 435               # 第 1 行数据
LINE_DATA_LAST = 534                # 第 100 行数据
DATA_ROW_COUNT = LINE_DATA_LAST - LINE_DATA_FIRST + 1

SYSTEM_COLUMNS = (
    "Serial_No", "Part_No", "Dut_No", "Site_No", "Dut_Pass", "SW_Bin",
    "X_COORD", "Y_COORD", "QR_Code", "Start_T", "Test_Time", "Alarm", "Data_Cnt",
)

# identify_format() 的承重子串（小写比较）；夹具里必须仍能 grep 到。
FORMAT_TOKEN = "cta8290d"

# 假参数名的形态（自检时用它区分「映射来自真实样例」与「映射来自已虚拟化输入」）。
FAKE_NAME_RE = re.compile(r"^PAR\d{4}$")

# --------------------------------------------------------------------------
# [GENERAL] 值虚拟化表：行号 → (键名, 假值)
# --------------------------------------------------------------------------
# 假料号家族：BFI99999（B + 1~2 个大写字母 + 数字，正好落进
# apps/datafiles/utils.py::_PRODUCT_CODE_TOKEN = ^B[A-Z]{1,2}\d+[A-Z0-9]*，
# 且按下划线切分后是「整词」命中 —— 与真实料号的命中方式一致）。
# parsers/cta8290d.py 取 TestFile 的 basename 当 program_name，
# utils.extract_product_code() → BFI99999，utils.extract_stage() → FT
# （靠 '_FT' 这个 token）。所以假值必须保住：
#   同样的 3 层目录 + 同样的 .dll / .cpts 扩展名
#   同样的 '<料号>_FT_YAA_<料号>XBAD_EN[_FT]' token 结构
FAKE_PROGRAM_PATH = (
    "E:\\CI-FIXTURE\\2025-04-23_despiked\\BFI99999_FT_YAA_BFI99999XBAD_EN"
    "\\BFI99999_FT_YAA_BFI99999XBAD_EN.dll"
)
FAKE_TESTFILE_PATH = (
    "E:\\CI-FIXTURE\\2025-04-23_despiked\\BFI99999_FT_YAA_BFI99999XBAD_EN"
    "\\BFI99999_FT_YAA_BFI99999XBAD_EN_BFI99999_FT.cpts"
)

GENERAL_REPLACEMENTS = {
    3: ("Tester_Name", "DESKTOP-CI-FIXTURE"),
    6: ("Software_Ver", "9.9.9.9FIX"),
    7: ("Customer_ID", "userfixt"),
    8: ("Operator", "opfixt"),
    9: ("Op_Type", "opfixt(opfixt)"),
    11: ("Program", FAKE_PROGRAM_PATH),
    14: ("TestFile", FAKE_TESTFILE_PATH),
    21: ("DUTBox_Type", "FIXT8290"),
    29: ("HandlerName", "C0Handler"),
}

# 夹具里不应再出现的「真实标识符」：刻意**不在源码里写死字面量** —— 本脚本要进公开仓库，
# 把真实料号/内部路径/账号抄成常量等于把它们再发布一遍。改为运行时从真实输入现取：
# 被替换掉的那些 [GENERAL] 原值，就是不允许残留的字符串。
FAKE_GENERAL_VALUES = frozenset(fake for _key, fake in GENERAL_REPLACEMENTS.values())


def real_general_identifiers(real_lines: list[str]) -> tuple[str, ...]:
    out = []
    for line_no, (key, _fake) in GENERAL_REPLACEMENTS.items():
        fields = real_lines[line_no - 1].split(",")
        value = fields[1].strip() if len(fields) > 1 else ""
        # 太短的值（如单字符）没有识别性又容易误报；已在假值集合里的说明输入本身就是夹具，
        # 幂等重跑不该因此判成泄漏。
        if len(value) >= 4 and value not in FAKE_GENERAL_VALUES:
            out.append(value)
    return tuple(out)

# 明确保留（自检用）：行号 → 该行必须逐字等于的真实文本（Tester_ID 是「禁止全文
# 替换 140000」这条约束的锚点，Tester_Type/Software_Name 是格式识别的锚点）。
KEEP_VERBATIM_LINES = {
    2: "Tester_Type,CTA8290DPlus,",
    4: "Tester_ID,140000,",
    5: "Software_Name,CTA8290DPlus,",
    70: "[SUMMARY]",
}


class FixtureError(RuntimeError):
    """结构/校验不符合预期 —— 直接失败退出，绝不产出残缺夹具。"""


# --------------------------------------------------------------------------
# 低层行/字段工具（一律按行号 + 字段下标操作，不用正则全文替换）
# --------------------------------------------------------------------------
def read_lines(path: str) -> list[str]:
    """读成 1 基行号可寻址的列表（len == EXPECTED_TOTAL_LINES）。"""
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:3] == b"\xef\xbb\xbf":
        raise FixtureError(f"{path}: 带 BOM，与真实夹具假设不符")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise FixtureError(f"{path}: 存在非 ASCII 字节（{exc}）") from exc
    crlf = raw.count(b"\r\n")
    if crlf != EXPECTED_TOTAL_LINES or raw.count(b"\n") != crlf:
        raise FixtureError(f"{path}: CRLF 行数 {crlf} != {EXPECTED_TOTAL_LINES}（行尾不纯）")
    if not text.endswith("\r\n"):
        raise FixtureError(f"{path}: 文件尾不是 CRLF")
    parts = text.split("\r\n")
    if parts[-1] != "" or len(parts) != EXPECTED_TOTAL_LINES + 1:
        raise FixtureError(f"{path}: 切分后行数 {len(parts)} 异常")
    return parts[:-1]


def write_lines(path: str, lines: list[str]) -> int:
    """每行 CRLF 结尾写盘，纯 ASCII；返回字节数。"""
    text = "".join(line + "\r\n" for line in lines)
    data = text.encode("ascii")  # 非 ASCII 会在这里炸，不会静默产出
    with open(path, "wb") as fh:
        fh.write(data)
    return len(data)


def split_fields(line: str, line_no: int, expect_count: int) -> list[str]:
    fields = line.split(",")
    if len(fields) != expect_count:
        raise FixtureError(
            f"L{line_no}: 字段数 {len(fields)} != 预期 {expect_count}：{line[:80]!r}"
        )
    return fields


def join_fields(fields: list[str]) -> str:
    return ",".join(fields)


def check_structure(lines: list[str], src: str) -> None:
    """动任何字段之前先把骨架钉死；结构一变就报错而不是产出错夹具。"""
    if len(lines) != EXPECTED_TOTAL_LINES:
        raise FixtureError(f"{src}: 总行数 {len(lines)} != {EXPECTED_TOTAL_LINES}")
    probes = (
        (LINE_GENERAL_HEADER, "[GENERAL],"),
        (LINE_WAFERCONFIG, "[WAFERCONFIG],"),
        (LINE_SUMMARY, "[SUMMARY]"),
        (LINE_SWBININFO, "[SWBININFO],"),
        (LINE_HARDWAREBIN, "[HARDWAREBIN],"),
        (LINE_PARAMINFO_HEADER, "[PARAMINFO],"),
    )
    for line_no, literal in probes:
        if lines[line_no - 1] != literal:
            raise FixtureError(f"{src}: L{line_no} 应为 {literal!r}，实为 {lines[line_no - 1]!r}")
    if lines[LINE_BLANK_BEFORE_DATA - 1] != "":
        raise FixtureError(f"{src}: L{LINE_BLANK_BEFORE_DATA} 应为空行")
    if not lines[LINE_DATA_MARKER - 1].startswith("[Data],"):
        raise FixtureError(f"{src}: L{LINE_DATA_MARKER} 不是 [Data], 标记行")
    header = split_fields(lines[LINE_DATA_HEADER - 1], LINE_DATA_HEADER, EXPECTED_FIELD_COUNT)
    if tuple(header[:SYSTEM_COL_COUNT]) != SYSTEM_COLUMNS:
        raise FixtureError(f"{src}: L{LINE_DATA_HEADER} 前 13 个系统列名与预期不符")
    if header[-1] != "":
        raise FixtureError(f"{src}: L{LINE_DATA_HEADER} 尾部字段应为空")
    for line_no in (LINE_DATA_UNIT, LINE_DATA_MIN, LINE_DATA_MAX):
        split_fields(lines[line_no - 1], line_no, EXPECTED_FIELD_COUNT)
    for line_no in (LINE_PARAMINFO_FIRST, LINE_PARAMINFO_LAST):
        split_fields(lines[line_no - 1], line_no, PARAMINFO_FIELD_COUNT)
    for line_no in range(LINE_DATA_FIRST, LINE_DATA_LAST + 1):
        if len(split_fields(lines[line_no - 1], line_no, EXPECTED_FIELD_COUNT)) != EXPECTED_FIELD_COUNT:
            raise FixtureError(f"{src}: L{line_no} 数据行字段数异常")
    for line_no, literal in KEEP_VERBATIM_LINES.items():
        if lines[line_no - 1] != literal:
            raise FixtureError(f"{src}: L{line_no} 必须逐字保留为 {literal!r}")
    if FORMAT_TOKEN not in "".join(lines).lower():
        raise FixtureError(f"{src}: 头部缺 {FORMAT_TOKEN!r}，格式识别会退化成 Unknown")


def fake_param_name(index: int) -> str:
    """index 是 1-based 的参数位次 → PAR0001…PAR0332（固定 4 位宽度）。"""
    return "PAR%04d" % index


# --------------------------------------------------------------------------
# 单个文件的派生
# --------------------------------------------------------------------------
def derive(lines: list[str], param_map: dict[str, str], src_name: str) -> tuple[list[str], dict]:
    """返回（新行列表, 统计）。行列表是新对象，输入永不受影响。"""
    out = list(lines)
    stats = {"general": 0, "paraminfo": 0, "header": 0, "general_keys": []}

    # 1) [GENERAL]：只改值字段（parts[1]），键名与尾逗号原样。
    for line_no, (key, fake_value) in GENERAL_REPLACEMENTS.items():
        fields = split_fields(out[line_no - 1], line_no, 3)
        if fields[0] != key:
            raise FixtureError(f"{src_name}: L{line_no} 键应为 {key!r}，实为 {fields[0]!r}")
        if fields[1] != fake_value:
            fields[1] = fake_value
            out[line_no - 1] = join_fields(fields)
            stats["general"] += 1
            stats["general_keys"].append(key)

    # 2) PARAMINFO：按位置改第 1 字段，其余 11 个字段（失败计数/百分比）原样。
    for i in range(PARAM_COUNT):
        line_no = LINE_PARAMINFO_FIRST + i
        fields = split_fields(out[line_no - 1], line_no, PARAMINFO_FIELD_COUNT)
        real = fields[0]
        expected_fake = fake_param_name(i + 1)
        if param_map.setdefault(real, expected_fake) != expected_fake:
            raise FixtureError(f"{src_name}: 参数 {real!r} 在不同位次出现（映射冲突）")
        fields[0] = expected_fake
        out[line_no - 1] = join_fields(fields)
        stats["paraminfo"] += 1

    # 3) 表头行：按位置改第 14+i 个字段（下标 13+i），前 13 系统列与尾部空字段原样。
    fields = split_fields(out[LINE_DATA_HEADER - 1], LINE_DATA_HEADER, EXPECTED_FIELD_COUNT)
    for i in range(PARAM_COUNT):
        real = fields[SYSTEM_COL_COUNT + i]
        if param_map.setdefault(real, fake_param_name(i + 1)) != fake_param_name(i + 1):
            raise FixtureError(f"{src_name}: 表头参数 {real!r} 与 PARAMINFO 位次不一致")
        if fields[SYSTEM_COL_COUNT + i] != fake_param_name(i + 1):
            fields[SYSTEM_COL_COUNT + i] = fake_param_name(i + 1)
            stats["header"] += 1
    out[LINE_DATA_HEADER - 1] = join_fields(fields)

    return out, stats


# --------------------------------------------------------------------------
# 产物自检
# --------------------------------------------------------------------------
def verify_output(path: str, param_map: dict[str, str], forbidden: tuple[str, ...] = ()) -> list[str]:
    """重读产物核一遍硬指标；返回问题清单（空 = 全过）。"""
    problems: list[str] = []
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:3] == b"\xef\xbb\xbf":
        problems.append("存在 BOM")
    if any(b > 127 for b in raw):
        problems.append("存在非 ASCII 字节")
        return problems  # 解码不下去，后续文本类检查无意义
    crlf = raw.count(b"\r\n")
    if crlf != EXPECTED_TOTAL_LINES or raw.count(b"\n") != EXPECTED_TOTAL_LINES:
        problems.append("CRLF 计数 %d / LF 计数 %d，预期各 %d" % (crlf, raw.count(b"\n"), EXPECTED_TOTAL_LINES))
    text = raw.decode("ascii")
    lines = text.split("\r\n")[:-1]

    try:
        check_structure(lines, path + "(夹具)")
    except FixtureError as exc:
        problems.append(str(exc))

    # 332 个假名与真实名位置一一对应 + PARAMINFO/表头两处一致
    pnames = [lines[LINE_PARAMINFO_FIRST - 1 + i].split(",")[0] for i in range(PARAM_COUNT)]
    hnames = lines[LINE_DATA_HEADER - 1].split(",")[SYSTEM_COL_COUNT:SYSTEM_COL_COUNT + PARAM_COUNT]
    want = [fake_param_name(i + 1) for i in range(PARAM_COUNT)]
    if pnames != want:
        problems.append("PARAMINFO 假名序列 != PAR0001..PAR0332")
    if hnames != want:
        problems.append("表头假名序列 != PAR0001..PAR0332")
    mismatch = sum(1 for i in range(PARAM_COUNT) if pnames[i] != hnames[i])
    if mismatch:
        problems.append(f"PARAMINFO 与表头假名不一致 {mismatch} 处")
    if len(set(pnames)) != PARAM_COUNT:
        problems.append("假名有重复")

    for bad in forbidden:
        if bad in text:
            problems.append(f"产物仍含真实标识符 {bad!r}")
    if FORMAT_TOKEN not in text.lower():
        problems.append(f"产物 grep 不到 {FORMAT_TOKEN!r}（格式识别会失效）")

    # 真实参数名（若与 PARxxxx 形态不同）不应残留在产物里。映射若来自夹具自身
    # （幂等重跑指到 test/fixtures/gage 时 key 就是 PARxxxx），跳过自比对。
    leaked = [n for n in param_map if not FAKE_NAME_RE.match(n) and n in text]
    if leaked:
        problems.append(f"真实参数名残留 {len(leaked)} 个，例如 {leaked[:3]}")

    # 数据区必须还是 100 行 × 346 字段
    for i in range(DATA_ROW_COUNT):
        line_no = LINE_DATA_FIRST + i
        if len(lines[line_no - 1].split(",")) != EXPECTED_FIELD_COUNT:
            problems.append(f"L{line_no} 数据字段数 != {EXPECTED_FIELD_COUNT}")
            break
    return problems


# --------------------------------------------------------------------------
# MANIFEST
# --------------------------------------------------------------------------
def build_manifest(param_map: dict[str, str], per_file: list[dict], out_bytes: dict[str, int]) -> str:
    lines: list[str] = []
    add = lines.append
    add("gage CI fixture MANIFEST — 由 scripts/make_gage_ci_fixture.py 生成，请勿手改")
    add("=" * 78)
    add("")
    add("用途：GitHub CI 用的「虚拟化」gage datalog 夹具。真实样例在 Data/SampleData/Gage/")
    add("      下（本就不该入库：仓库公开，而 datalog 头带内部路径/主机名/账号）。")
    add("      ⚠ 现场核对：.gitignore 目前有 `!/Data/SampleData/Gage/` 把真实 4 个 CSV 放开")
    add("      入库了（本地提交 c6b7bd8，未推送）。改用本夹具后应把这条收回，否则外发的还是")
    add("      真实头信息。本表列出哪些字段是假的。")
    add("")
    add("输入目录：Data/SampleData/Gage/")
    add("输出目录：test/fixtures/gage/")
    add("")
    add("-" * 78)
    add("A. 虚拟化的标识符（[GENERAL] 段，按行号定位，只改值字段；4 个文件同值）")
    add("-" * 78)
    add("%-4s %-14s %-30s %s" % ("行", "键", "假值", "（真实值形态）"))
    real_shape = {
        "Tester_Name": "内部机台主机名",
        "Software_Ver": "程序版本",
        "Customer_ID": "内部账号",
        "Operator": "操作员账号",
        "Op_Type": "操作员账号(自身)",
        "Program": "内部绝对路径 + 真实料号",
        "TestFile": "内部绝对路径 + 真实料号（两处料号）",
        "DUTBox_Type": "内部 DUTBox 型号",
        "HandlerName": "分选机命名",
    }
    for line_no, (key, value) in sorted(GENERAL_REPLACEMENTS.items()):
        add("%-4d %-14s %-30s %s" % (line_no, key, value, real_shape.get(key, "")))
    add("")
    add("  假 Program : %s" % FAKE_PROGRAM_PATH)
    add("  假 TestFile : %s" % FAKE_TESTFILE_PATH)
    add("  假料号家族  ：BFI99999（真实料号一并换成它；真实值不写进本表，见脚本注释）")
    add("  形状保持    ：3 层目录 + .dll/.cpts + '<料号>_FT_…' token，")
    add("                使 parsers/cta8290d.py 的 program_name 与 utils.extract_product_code()/")
    add("                extract_stage() 仍解析出 product_code=BFI99999、stage=FT。")
    add("")
    add("  原样保留（承重）：Tester_Type=CTA8290DPlus、Software_Name=CTA8290DPlus（identify_format")
    add("  靠小写子串 'cta8290d' 判格式）、LotID=gage_m_S1..S4、Tester_ID=140000（S1 全文出现 15 次、")
    add("  14 次是数据值 1.140000 的巧合，禁止全文替换）、日期时间戳、全部数值。")
    add("")
    add("-" * 78)
    add("B. 测试项名：**按位次**虚拟化，共 %d 个，形态 PAR0001..PAR%04d" % (PARAM_COUNT, PARAM_COUNT))
    add("-" * 78)
    add("  ⚠ 本 MANIFEST 刻意**不列出真实名 → 假名的映射表**：那等于把刚虚拟化掉的测试项名")
    add("  再公开一遍（夹具进的是公开仓库）。要核对位次就在本机重新导出：")
    add("      python scripts/make_gage_ci_fixture.py --emit-mapping ..\\..\\Data\\ci-fixture-mapping.txt")
    add("  写到 `Data/` 下面正合适 —— 那儿整目录不入库。")
    add("")
    add("  必须按位次替换、不能按字符串全文替换：真实名中存在「一个是另一个的严格前缀」的")
    add("  情况达 48 个，按串替换会互相啃掉（具体名字属于不公开的真实测试项名，此处不列）。")
    add("  同一参数的两处出现：PARAMINFO 第 i 行（i 从 1 起，L%d..L%d）的第 1 字段，与" % (LINE_PARAMINFO_FIRST, LINE_PARAMINFO_LAST))
    add("  表头 L%d 的第 %d+i 个字段（1-based；即第 1 个参数在第 %d 列，前 %d 列是系统列）。"
        % (LINE_DATA_HEADER, SYSTEM_COL_COUNT, SYSTEM_COL_COUNT + 1, SYSTEM_COL_COUNT))
    add("")
    add("-" * 78)
    add("C. 未虚拟化的段落（原文照抄，审计时知道它们不是假的）")
    add("-" * 78)
    add("  [WAFERCONFIG] L57-69 / [SUMMARY] L70-73 / [SWBININFO] L74-91 / [HARDWAREBIN] L92-95")
    add("  —— bin 名是通用失效类别标签（Open/Short/Kelvin/Trim…），全仓零消费者，不构成披露。")
    add("  PARAMINFO 第 2-12 字段、[Data] 的 Unit/Min/Max 三行、%d 行数据 × %d 字段、"
        % (DATA_ROW_COUNT, EXPECTED_FIELD_COUNT))
    add("  表头前 %d 个系统列（%s）：全部原样。" % (SYSTEM_COL_COUNT, ", ".join(SYSTEM_COLUMNS)))
    add("")
    add("-" * 78)
    add("D. 每文件替换统计")
    add("-" * 78)
    add("%-16s %10s %10s %9s %9s %9s" % ("文件", "输入字节", "输出字节", "GENERAL", "PARAMINFO", "表头列"))
    for rec in per_file:
        add("%-16s %10d %10d %9d %9d %9d" % (
            rec["name"], rec["in_bytes"], out_bytes[rec["name"]],
            rec["stats"]["general"], rec["stats"]["paraminfo"], rec["stats"]["header"]))
    add("")
    add("  GENERAL：真实输入时每文件应改 %d 行（键：%s）；上表计数即实际改动计数。"
        % (len(GENERAL_REPLACEMENTS), ", ".join(sorted(k for k, _ in GENERAL_REPLACEMENTS.values()))))
    add("  4 个 CSV 夹具：行尾 CRLF、无 BOM、纯 ASCII；总行数 %d；[Data], 仍在 L%d。"
        % (EXPECTED_TOTAL_LINES, LINE_DATA_MARKER))
    add("  本 MANIFEST.txt 自身为 UTF-8（含中文审计说明）+ CRLF，不是 ASCII。")
    add("  入库前提：`.gitignore` 需有 `!/test/fixtures/`（`/test/*` 的 `*` 不跨 `/`，一条就够）。")
    add("  跨平台：`core.autocrlf=true` 且无 `.gitattributes` 时，git 会把 CRLF 存成 LF，")
    add("  Linux CI 检出即变 LF —— 需要 `.gitattributes` 里 `test/fixtures/gage/*.csv -text` 才字节守恒。")
    add("")
    return "\r\n".join(lines) + "\r\n"


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 cp936，中文日志会乱码甚至抛 UnicodeEncodeError。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="生成虚拟化 gage datalog CI 夹具（幂等，可重跑）")
    ap.add_argument("--input-dir", default=DEFAULT_INPUT_DIR, help="真实样例目录（只读）")
    ap.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="夹具输出目录")
    ap.add_argument("--no-manifest", action="store_true", help="只写 4 个 CSV，不写 MANIFEST.txt")
    ap.add_argument("--emit-mapping", metavar="PATH", default=None,
                    help="把「真实测试项名 → 假名」全映射写到此路径供本地审计。"
                         "默认不写：这份映射会把虚拟化掉的名字再公开一遍，绝不能进版本库"
                         "（建议写到 Data/ 下，那儿整目录不入库）。")
    args = ap.parse_args(argv)

    in_dir = os.path.abspath(args.input_dir)
    out_dir = os.path.abspath(args.output_dir)

    # 护栏：本脚本对输入侧只读，绝不允许把夹具写进真实数据目录。
    if out_dir == in_dir or out_dir.startswith(in_dir + os.sep):
        print("[错误] 输出目录不能落在输入（真实数据）目录内：%s" % out_dir, file=sys.stderr)
        return 2
    guarded = {"data", "sampledata"}
    bad_comp = [c for c in out_dir.lower().split(os.sep) if c in guarded]
    if bad_comp:
        print("[错误] 拒绝写入真实数据目录（含 %r 组件）：%s" % (bad_comp[0], out_dir), file=sys.stderr)
        return 2

    missing = [f for f in FIXTURE_FILES if not os.path.isfile(os.path.join(in_dir, f))]
    if missing:
        print(
            "[错误] 真实样例库缺失：在 %s 下找不到 %s\n"
            "       夹具必须由真实样例派生；请把真实 Data/SampleData/Gage/ 放到本机后再重跑，\n"
            "       本脚本不会静默产出残缺夹具。" % (in_dir, ", ".join(missing)),
            file=sys.stderr,
        )
        return 1

    os.makedirs(out_dir, exist_ok=True)

    param_map: dict[str, str] = {}
    out_bytes: dict[str, int] = {}
    per_file: list[dict] = []
    all_problems: list[str] = []

    for name in FIXTURE_FILES:
        src = os.path.join(in_dir, name)
        dst = os.path.join(out_dir, name)
        in_bytes = os.path.getsize(src)
        lines = read_lines(src)
        check_structure(lines, src)
        derived, stats = derive(lines, param_map, name)
        # 幂等：GENERAL 值与假名都是固定字面量，重跑时 changed 行数只会来自真实输入
        # → 夹具这一次派生；同一输入两次运行得到逐字节相同的产物。
        stats["changed_lines"] = sum(1 for a, b in zip(lines, derived) if a != b)
        out_bytes[name] = write_lines(dst, derived)
        problems = verify_output(dst, param_map, real_general_identifiers(lines))
        per_file.append({
            "name": name, "in_bytes": in_bytes, "out_bytes": out_bytes[name],
            "stats": stats, "problems": problems,
        })
        all_problems += ["%s: %s" % (name, p) for p in problems]

    if len(param_map) != PARAM_COUNT:
        all_problems.append("参数映射条数 %d != %d" % (len(param_map), PARAM_COUNT))

    if not args.no_manifest:
        manifest_path = os.path.join(out_dir, "MANIFEST.txt")
        # MANIFEST 是给人审计的说明，带中文，按 UTF-8 + CRLF 写；4 个 CSV 才是纯 ASCII。
        with open(manifest_path, "wb") as fh:
            fh.write(build_manifest(param_map, per_file, out_bytes).encode("utf-8"))

    if args.emit_mapping:
        ordered = sorted(param_map.items(), key=lambda kv: kv[1])
        text = "\r\n".join("%s,%s" % (real, fake) for real, fake in ordered) + "\r\n"
        with open(args.emit_mapping, "wb") as fh:
            fh.write(text.encode("utf-8"))
        print("位次映射 %d 条已导出到 %s（此文件含真实测试项名，勿入库）" % (len(ordered), args.emit_mapping))

    for rec in per_file:
        print("%-16s %8d -> %8d 字节  改动行 GENERAL=%d PARAMINFO=%d 表头=%d（合计 %d 行）" % (
            rec["name"], rec["in_bytes"], rec["out_bytes"], rec["stats"]["general"],
            rec["stats"]["paraminfo"], rec["stats"]["header"], rec["stats"]["changed_lines"]))
    print("参数映射 %d 条；夹具输出 %s" % (len(param_map), out_dir))

    if all_problems:
        print("\n[失败] 自检发现问题：", file=sys.stderr)
        for p in all_problems:
            print("  - %s" % p, file=sys.stderr)
        return 1
    print("[通过] 4 个夹具自检：结构/假名一致性/禁止串/CRLF/ASCII 全过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
