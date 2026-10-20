#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""把真实权重 CSV「虚拟化」后写出入库 CI 夹具（spec §8）。

    用法：python scripts/make_weight_ci_fixture.py \
             --src <本机真实 csv 路径> \
             --out test/fixtures/weight/trim_weight_ci.csv

    `--src` 必填且没有默认值（真实路径是本机事实，不能进公开仓库）；`--out` 解析后必须落在
    本仓库内，否则拒绝写入。

仓库是**公开**的，而真实权重样例里全是内部测试项名，所以夹具只保留真实样例的
**形状**，标识符按「首次出现位次」换成 WT0001…WTTNN（14 个 → WT0001..WT0014）。
数值、行数、TAB、空行、CRLF、数组长度分布、行尾有无换行，一律原样保留。

⚠ 与 make_gage_ci_fixture.py 的同族教训（2026-10-16 那次真实样例被无关 push 带上
公开仓库）：本脚本与产物里**禁止出现真实标识符字面量**，连「真实名 → 假名」的映射也
只打到 stdout、绝不写文件，本脚本更不会把真实路径写成默认值（`--src` 必填）。

承重约束分两档说，别混为一谈（数字为 2026-10-19 对**已入库夹具**的实测，非估计值）：

A. 每一批 CI 都会跑（test/backend/test_weight_fixture.py 直接断言入库的那 11181 个字节，
   跑它不需要本机有任何真实样例）：
  * 56 条声明、14 个不同名称、每个名称恰好出现 4 次、名称一律 WT#### 形态；
  * 数组长度集合恰为 {4, 8, 16, 32, 64}；每条声明的「声明长度 == 实际值个数」；
  * TAB 恰好 **56** 个（`double` 与名称之间的分隔就是它）、CRLF 恰好 **112** 个且裸 LF 为 0、
    文件**结尾没有换行**（最后一个字符是 `;`）；
  * 花括号里的 1088 个数值全部匹配 `-?\d+\.\d{5}`（本 docstring 是 raw 字符串，这里就是
    正则字面量），即**恰好 5 位小数**（Task 2/4 的精度工作假设的正是这条）。
  这几条用的是**精确计数**而不是 `> 0`：把 56 个 TAB 只换掉 30 个、把 112 个 CRLF 只转掉
  100 个、给某个值少写一位小数、或手滑补一个结尾换行，现在都会引入新的 CI 红。

B. 只有重新生成时才跑（CI 手里没有真实样例，够不着这一段；这一档改坏了不会立刻红）：
  * check_input_shape() 量 `--src`：声明条数/名称数/长度集合/每名 4 次/声明长度==值个数
    都是精确断言，但 TAB 只校 `>= 56`、CRLF 只校 `> 0`，且**不校**小数位数与结尾有无换行；
  * _assert_only_names_changed() 的字节总账（假名按映射反向换回后必须与输入逐字符相等）——
    真正守恒数值、值个数、TAB/空格、空行、CRLF、数组长度与结尾有无换行的是这一条；
  * 真实名残留扫描与 `.encode('ascii')`（顺带保证无 BOM、纯 ASCII）。

形状与真实样例漂移时（换了新版样例），A 档的计数会先让 CI 红，本脚本再按 B 档第一条对
`--src` 的精确断言把根因指出来：重量一遍，改 EXPECTED_* 常量并同步改
test/backend/test_weight_fixture.py 里的计数，不要改计划的历史。
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys

# `double` + 空白 + 名称 + 空白 + `[`：只用来「认名称」，不参与替换。
NAME_RE = re.compile(r'double\s+(\w+)\s*\[')
# 替换专用：把 `double` 与 `[` 之间那两段**原样捕获**（真实样例里是 TAB，一个空格都不是）。
# ⚠ 绝不能用字面量 'double ' 回填 —— 那会把承重的 TAB 换成空格，夹具就废了。
_DECL_WITH_WS_RE = re.compile(r'double(\s+)(\w+)(\s*)\[')
# 整条声明：名称 / 声明长度 / 花括号里的值串。
DECL_RE = re.compile(r'double\s+(\w+)\s*\[\s*(\d+)\s*\]\s*=\s*\{([^}]*)\}\s*;')

FAKE_NAME_TMPL = 'WT%04d'
FAKE_NAME_RE = re.compile(r'^WT\d{4}$')

EXPECTED_DECL_COUNT = 56
EXPECTED_NAME_COUNT = 14
EXPECTED_TIMES_PER_NAME = 4
EXPECTED_LENGTHS = [4, 8, 16, 32, 64]


class FixtureError(RuntimeError):
    """输入形状或产物守恒不符合预期 —— 直接失败退出，绝不产出残缺夹具。"""


def repo_root() -> str:
    """仓库根 = 本脚本所在 `scripts/` 的上一级。

    用 `__file__` 算而**不是**用 cwd：本仓库里相对路径 + 多工作树 + `core.autocrlf` 的组合
    咬过不止一次，cwd 是哪个检出完全靠运气，而这条护栏要守的是「产物只能落在本检出内」。
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_inside(path: str, root: str) -> bool:
    """`path` 是否**严格**落在 `root` 目录内（Windows 大小写不敏感、分隔符归一）。"""
    p = os.path.normcase(os.path.abspath(path))
    r = os.path.normcase(os.path.abspath(root))
    return p.startswith(r + os.sep)


def read_source(path: str) -> str:
    """按字节读入并严格 UTF-8 解码，换行不翻译（CRLF 必须原样留在字符串里）。"""
    with io.open(path, 'rb') as fh:
        raw = fh.read()
    if raw[:3] == b'\xef\xbb\xbf':
        raise FixtureError('%s: 带 BOM，与夹具假设（无 BOM 纯 ASCII）不符' % path)
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise FixtureError('%s: 存在非 UTF-8 字节（%s）' % (path, exc)) from exc


def check_input_shape(text: str, src: str) -> list[tuple[str, str, str]]:
    """量一遍真实样例；形状与文档不符就报错，而不是静默生成一份对不上的夹具。"""
    decls = DECL_RE.findall(text)
    if len(decls) != EXPECTED_DECL_COUNT:
        raise FixtureError('%s: 声明条数 %d != %d' % (src, len(decls), EXPECTED_DECL_COUNT))
    names = [n for n, _, _ in decls]
    if len(set(names)) != EXPECTED_NAME_COUNT:
        raise FixtureError('%s: 不同名称数 %d != %d' % (src, len(set(names)), EXPECTED_NAME_COUNT))
    counts = {n: names.count(n) for n in set(names)}
    if set(counts.values()) != {EXPECTED_TIMES_PER_NAME}:
        raise FixtureError('%s: 名称出现次数不是恒定 %d 次：%r'
                           % (src, EXPECTED_TIMES_PER_NAME, sorted(set(counts.values()))))
    lengths = sorted({int(k) for _, k, _ in decls})
    if lengths != EXPECTED_LENGTHS:
        raise FixtureError('%s: 数组长度集合 %r != %r' % (src, lengths, EXPECTED_LENGTHS))
    for name, declared, values in decls:
        actual = len([v for v in values.split(',') if v.strip()])
        if actual != int(declared):
            raise FixtureError('%s: 声明 %s[%s] 实际值 %d 个（名称不入库，只报位次）'
                               % (src, name, declared, actual))
    tabs = text.count('\t')
    if tabs < EXPECTED_DECL_COUNT:
        raise FixtureError('%s: TAB 数 %d < 声明数 %d，`double` 与名称之间的分隔不是 TAB'
                           % (src, tabs, EXPECTED_DECL_COUNT))
    crlf = text.count('\r\n')
    if not crlf:
        raise FixtureError('%s: 没有 CRLF，行尾形态与夹具假设不符' % src)
    return decls


def build_mapping(names: list[str]) -> dict[str, str]:
    """按**首次出现位次**编号：WT0001…WTTNN。真实名一律不出现在返回值之外的任何地方。"""
    order: list[str] = []
    for n in names:
        if n not in order:
            order.append(n)
    mapping = {n: FAKE_NAME_TMPL % (i + 1) for i, n in enumerate(order)}
    # 假名若与某个真实名撞车，替换会自我吞噬（幂等重跑也会踩这条）。
    clash = [n for n in mapping if FAKE_NAME_RE.match(n)]
    if clash:
        raise FixtureError('输入里已有 %d 个 WT#### 形态的名称，映射不唯一，拒绝虚拟化' % len(clash))
    return mapping


def virtualize(text: str) -> tuple[str, dict[str, str]]:
    """返回（夹具文本, 真实名→假名映射）。只改名称，其余字节一个都不动。"""
    mapping = build_mapping([m.group(1) for m in NAME_RE.finditer(text)])
    out = _DECL_WITH_WS_RE.sub(
        lambda mm: 'double' + mm.group(1) + mapping[mm.group(2)] + mm.group(3) + '[',
        text)
    leftovers = set(NAME_RE.findall(out)) - set(mapping.values())
    if leftovers:
        raise FixtureError('出现未映射名称 %d 个，虚拟化不完整' % len(leftovers))
    return out, mapping


def _assert_only_names_changed(text: str, out: str, mapping: dict[str, str]) -> None:
    """总账：把假名按原宽度反向换回真实名，必须与输入**逐字符相等**。

    这一条同时守恒数值、值个数、TAB/空格、空行、CRLF、数组长度与结尾有无换行 —— 任何
    一处被顺手改动都会在这里炸，而不需要为每个特征单独写一条计数断言。
    （夹具**必然比输入短**：真实名 13~31 字符换成等宽 6 字符的 WT####，所以这里不校长度。）
    """
    inv = {v: k for k, v in mapping.items()}
    back = _DECL_WITH_WS_RE.sub(
        lambda mm: 'double' + mm.group(1) + inv[mm.group(2)] + mm.group(3) + '[', out)
    if back != text:
        pos = next((i for i, (a, b) in enumerate(zip(back, text)) if a != b),
                   min(len(back), len(text)))
        raise FixtureError('反向还原后与输入不一致（首个差异在字符 %d：%r vs %r）—— '
                           '除名称外的任何改动都不允许' % (pos, back[pos:pos + 20], text[pos:pos + 20]))
    for name in NAME_RE.findall(out):
        if name not in inv:
            raise FixtureError('夹具里出现映射外的名称 %r（形态不符？）' % name)


def check_residue(out: str, mapping: dict[str, str]) -> list[str]:
    """真实名残留清单（只返回，绝不打印原串）。"""
    return [real for real in mapping if real in out]


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 cp936，中文日志会乱码甚至抛 UnicodeEncodeError。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description='生成虚拟化权重 CSV CI 夹具（幂等，可重跑）')
    # 真实路径是本机事实，绝不写成默认值 —— 脚本要进公开仓库。
    ap.add_argument('--src', required=True, help='真实权重 CSV 路径（只读，不入仓）')
    ap.add_argument('--out', required=True, help='夹具输出路径')
    a = ap.parse_args(argv)

    src = os.path.abspath(a.src)
    out_path = os.path.abspath(a.out)
    # 护栏 1：夹具是仓库里的文件，输出必须落在**本检出内**。真实样例早已搬到仓库之外，
    # 所以「指到仓库外面」的唯一现实含义就是把别处的数据目录当输出 —— 拒了它，既防误写
    # 也顺带防把真实数据整份抄进公开仓库。这条不需要写任何目录名/工程名（2026-10-17 的
    # 清除指令不允许在本仓库文件里点名兄弟工程），也不看 cwd：仓库根由 `__file__` 反推。
    root = repo_root()
    if not is_inside(out_path, root):
        print('[错误] --out 解析后不在本仓库内，拒绝写入\n'
              '       仓库根：%s\n'
              '       --out  ：%s（相对路径按当前工作目录 %s 解析，请在仓库根运行或用仓库内路径）'
              % (root, out_path, os.getcwd()), file=sys.stderr)
        return 2
    # 护栏 2：不许原地覆盖真实样例本身。
    if out_path == src:
        print('[错误] --out 不能就是 --src 本身', file=sys.stderr)
        return 2
    if not os.path.isfile(src):
        print('[错误] 真实样例不存在：%s\n'
              '       夹具必须由真实样例派生；本脚本不会静默产出残缺夹具。' % src, file=sys.stderr)
        return 1

    text = read_source(src)
    check_input_shape(text, src)
    out, mapping = virtualize(text)
    _assert_only_names_changed(text, out, mapping)

    residue = check_residue(out, mapping)
    if residue:
        print('[失败] 真实名称残留 %d 处，拒绝入库' % len(residue), file=sys.stderr)
        return 1

    data = out.encode('ascii')  # 非 ASCII 在这里炸，不会静默产出
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, 'wb') as fh:
        fh.write(data)

    print('wrote %s: %d chars, %d names' % (a.out, len(out), len(mapping)))
    # 只打印假名与真实名长度：映射表本身是敏感信息，不入库、不写文件。
    for real, fake in sorted(mapping.items(), key=lambda kv: kv[1]):
        print('  %s <- (真实名长 %d，本脚本不打印原串)' % (fake, len(real)))
    print('[通过] 形状 %d/%d/%s、每名 %d 次、反向还原逐字符相等、无真实名残留、纯 ASCII。'
          % (EXPECTED_DECL_COUNT, EXPECTED_NAME_COUNT, EXPECTED_LENGTHS, EXPECTED_TIMES_PER_NAME))
    return 0


if __name__ == '__main__':
    sys.exit(main())
