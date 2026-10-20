# 权重画图（桌面版）实施计划

> **2026-10-20 改版（执行后用户实测反馈）**：14 组叠一张图会被大值组压扁 ⇒ 每个测试项独立成图。
> 最终导出形态（同日再改）：`总览`（测试项超链接）+ 每个测试项一张 sheet（图 + 数据 + 返回链接）；
> 4 条原始线带圆点、均值线（默认打开）带数值标签。本计划中 Task 4/6/8/9 的旧版描述保留为历史记录，
> **以 spec 与当前代码为准**。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development（推荐）或
> superpowers:executing-plans 逐任务实施。步骤用 checkbox（`- [ ]`）跟踪。

**Goal:** 在 LQ-DataPrase 桌面应用里新增「权重画图」页：本地选一个 C 声明式权重 CSV，后端解析出按测试项分组的
多条曲线，前端用 ECharts 画「X=code、Y=weight」的无标记折线图并支持整组开关与逐点均值，同时能导出带**原生 Excel 图**的 xlsx。

**Architecture:** 浏览器只读文件文本 → `POST /api/v1/weight/parse/` → 后端纯模块 `apps/weight/parser.py`
返回结构化文档（分组、`_1.._N` 命名、逐点均值）；前端 `buildWeightOption` 纯函数把文档 + 可见组状态变成 ECharts option，
开关与均值只改可见集合、不重新请求后端；导出把原始文本 + 可见状态 + 当前主题色板再交给**同一个解析器**，
由 `apps/weight/xlsx.py` 用 openpyxl 生成 `bytes` 并 `FileResponse` 同步返回。全程零 multipart、零 `MEDIA_ROOT`、零 model、零 migration。

**Tech Stack:** Django 5 + DRF（`apps/weight/`，无 models）、openpyxl 3.1.5（已在 `requirements/base.txt:48`，
**不新增依赖**）、Vue 3 Composition API + Pinia（setup 式 store）+ ECharts（必须走 `useChart`）、
Playwright（T3）、vitest（T2，node 环境零 DOM）。

**Spec:** `docs/superpowers/specs/2026-10-19-weight-plot-desktop-design.md`（与本计划同批读，冲突以 spec 为准）
需求来源稿：`docs/superpowers/specs/2026-10-19-weight-plot-design.md`（Excel 加载项版，**不要按它实现**）

## Global Constraints（每个任务都受这些条款约束）

- 单个 Vue 文件 / Python 文件 **≤ 600 行**，超了就拆（`.claude/CLAUDE.md`）。
- **落库禁令**：不建 model、不写 `MEDIA_ROOT`、不用 multipart、不加 migration。
  现成上传视图 `apps/datafiles/views/file_views.py:535` 与作业化 `apps/jobs/views.py:122-124`
  （`get_object_or_404(DataFile, …)`）都**不许**复用或改动 —— 前者建 `DataFile`/`ParseHistory`，后者无库记录即 404。
- **文案单一来源**：后端 `error_response(code, detail=None, status=400, **extra)`（`apps/common/errors.py:14`）
  只给机器码 + 结构化 detail；中文句子一律进 `frontend/src/utils/error.ts:15` 的 `ERROR_CODE_MAP`。
  漏加不会报错，只会把裸机器码显示给用户（`error.ts:63` 的 `?? d.code` 回落）。
- **ECharts 规矩**（lessons R7）：颜色取 `useEChartsTheme()`（`frontend/src/utils/echarts-theme.ts:77`）的 JS 语义色，
  DOM 才用 `var(--token)`；**禁止裸调 `echarts.init`**，必须经 `useChart`（`frontend/src/composables/useChart.ts:28`）
  → `initEchartsWhenReady`（`frontend/src/utils/echarts-init.ts:76`）。任何前端改动同时维护 dark + light。
- **后端测试禁用 pytest 风格**：本仓后端跑在 Django `DiscoverRunner` 下，测试文件里出现 `import pytest`
  会让 runner 静默不收集（项目 memory 里钉着这条）。写法一律 `from django.test import TestCase`。
- **真实权重样例禁止入库**（spec §8）：本机那份私有样例 CSV 含内部工位/产品代号，
  仓库是公开的，且 `docs/reference/testing-gates.md` §6.5 记着 2026-10-16 同类泄露事故。只有派生夹具能进 git。
- 入站边界固定值：`text ≤ 2_000_000` 字符、`声明 ≤ 2000` 条、`单条长度 ≤ 1024`。
  Django 未设置 `DATA_UPLOAD_MAX_MEMORY_SIZE`（实测 `config/` 无该项）⇒ 默认 2 621 440 **字节**，
  纯 ASCII 的 2 000 000 字符 JSON 体约 2.0 MB < 2.5 MB，所以我们的守卫先于 Django 触发；
  若文本含大量多字节字符，会先被 Django 拦成它自己的 400（不是我们的 code），这条要在 §10 的验收里明说。
- 门禁节奏（`docs/reference/testing-gates.md`）：每批 commit 前 `cd frontend && npm run test:e2e:affected`；
  本功能必改 `frontend/src/router/` 与 `config/` ⇒ **快门禁会直接判成全量**，收口要
  `node scripts/e2e_pool.mjs --slots=4` + 后端全套；每次提交前 `npx vitest run` + `npm run lint:e2e` + `npm run build`。
- 定向单跑 e2e **必须带 `--project=P1`**：`frontend/playwright.config.ts:124` 的 Edge 项目用
  `grepInvert: /@p[012]/`，不带项目名会被静默跳过出假绿（`testDir: './e2e'` 会自动收新目录，**不需要**改 glob）。
- 共享工作区：本仓可能有另一个代理在写，逐文件 `git add`（禁 `git add -A`）、不并发提交、禁裸 `git stash`。
- 提交信息风格跟随仓内历史：`feat(weight): 中文一句话`。

---

## Task 1: 派生 CI 夹具（虚拟化）

**Files:**
- Create: `scripts/make_weight_ci_fixture.py`
- Create: `test/fixtures/weight/trim_weight_ci.csv`（脚本生成后入库）
- Modify: `.gitattributes`（追加两行）
- Test: `test/backend/test_weight_fixture.py`

**Interfaces:**
- Consumes: 真实样例（仅本机；绝对路径由 shell 变量 `$SRC` 传入，**不写进任何入库文件**）
- Produces: `test/fixtures/weight/trim_weight_ci.csv` —— 后续所有任务的测试素材；形状与真实样例一致
  （56 条声明、14 个不同名称、每个名称出现 4 次、数组长度仅取 4/8/16/32/64、`double` 与名称之间是 TAB、条目间夹空行）

- [ ] **Step 1: 确认真实样例的形状，把数字抄进脚本注释前先自己量一遍**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase"   # 只在仓内跑
SRC="<把本机那份私有样例 csv 的绝对路径填在这里，它不进仓库>"
python -c "import re,io,sys; t=io.open(sys.argv[1],encoding='utf-8',errors='replace').read(); m=re.findall(r'double\s+(\w+)\s*\[\s*(\d+)\s*\]',t); print('decls',len(m)); print('names',len(set(n for n,_ in m))); print('lengths',sorted(set(int(k) for _,k in m))); print('tabs',t.count(chr(9))); print('crlf',t.count('\r\n'))" "$SRC"
```
Expected: `decls 56`、`names 14`、`lengths [4, 8, 16, 32, 64]`、tabs > 0、crlf > 0。
**量出来的数字与下面断言不一致时，以实测为准改脚本，不要改这份计划的历史。**

- [ ] **Step 2: 写虚拟化脚本**

```python
# scripts/make_weight_ci_fixture.py
"""把真实权重 CSV 虚拟化后写出入库夹具。

规则（spec §8）：测试项名按**首次出现位次**换成 WT0001..WTTNN；数值、行数、TAB、空行、
CRLF、数组长度分布原样保留。本文件与生成的夹具里**禁止出现真实标识符字面量**，
映射只打到 stdout（不入库），照 scripts/make_gage_ci_fixture.py 的同族教训。

用法：python scripts/make_weight_ci_fixture.py --src <真实csv路径> --out test/fixtures/weight/trim_weight_ci.csv
"""
import argparse
import io
import re
import sys

NAME_RE = re.compile(r'double\s+(\w+)\s*\[')


def virtualize(text: str) -> tuple[str, dict[str, str]]:
    order: list[str] = []
    for m in NAME_RE.finditer(text):
        n = m.group(1)
        if n not in order:
            order.append(n)
    mapping = {n: f'WT{i + 1:04d}' for i, n in enumerate(order)}
    # 整词替换，避免 A 是 B 前缀时互啃（gage 那次的根因，48 个名字互为前缀）
    out = re.sub(r'double\s+(\w+)\s*\[',
                 lambda mm: 'double ' + mapping[mm.group(1)] + '[',
                 text)
    if re.search(r'double\s+\w+\s*\[', out) and set(NAME_RE.findall(out)) - set(mapping.values()):
        raise SystemExit('出现未映射名称，虚拟化不完整')
    return out, mapping


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    text = io.open(a.src, encoding='utf-8', errors='replace', newline='').read()
    out, mapping = virtualize(text)
    with io.open(a.out, 'w', encoding='utf-8', newline='') as f:
        f.write(out)
    print(f'wrote {a.out}: {len(out)} chars, {len(mapping)} names')
    for real, fake in mapping.items():
        print(f'  {fake} <- (真实名长 {len(real)}，本脚本不打印原串)')
    residue = [n for n in mapping if n in out]
    if residue:
        raise SystemExit(f'真实名称残留 {len(residue)} 处，拒绝入库')
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 3: 生成夹具**

```bash
mkdir -p test/fixtures/weight
python scripts/make_weight_ci_fixture.py \
  --src "$SRC" \
  --out test/fixtures/weight/trim_weight_ci.csv
```
Expected: stdout 打 `wrote ...: N chars, 14 names`，**退出码 0**（非 0 = 有真实名残留）。

- [ ] **Step 4: 加 `.gitattributes` 一行**（本机 `core.autocrlf=true`，CRLF 与 TAB 都是承重项）

```
test/fixtures/weight/*.csv -text
```

- [ ] **Step 5: 写形状断言测试**（断言要带对照组，不是「文件存在就算绿」）

```python
# test/backend/test_weight_fixture.py
"""夹具形状断言：虚拟化后的素材必须仍具备解析测试依赖的全部结构特征。"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
import django  # noqa: E402
django.setup()
from django.test import TestCase  # noqa: E402

PATH = os.path.join('test', 'fixtures', 'weight', 'trim_weight_ci.csv')
DECL_RE = re.compile(r'double\s+(\w+)\s*\[\s*(\d+)\s*\]\s*=\s*\{([^}]*)\}\s*;')
DECIMAL_RE = re.compile(r'-?\d+\.\d{5}')      # 恰好 5 位小数，配 fullmatch
EXPECTED_TABS = 56
EXPECTED_CRLFS = 112
EXPECTED_VALUES = 1088


class WeightFixtureShapeTests(TestCase):
    def setUp(self):
        with io.open(PATH, 'rb') as f:
            self.raw = f.read()
        self.text = self.raw.decode('utf-8')

    def test_counts_match_real_sample(self):
        decls = DECL_RE.findall(self.text)
        self.assertEqual(len(decls), 56)                      # 声明条数
        self.assertEqual(len({n for n, _, _ in decls}), 14)    # 不同名称数
        self.assertEqual(sorted({int(k) for _, k, _ in decls}), [4, 8, 16, 32, 64])

    def test_every_name_appears_four_times(self):
        counts = {}
        for name, _, _ in DECL_RE.findall(self.text):
            counts[name] = counts.get(name, 0) + 1
        self.assertEqual(set(counts.values()), {4})

    def test_tabs_and_crlf_survived_git(self):
        # 精确计数，不用 >0：部分规范化（只换掉一部分 TAB / 只把一部分 CRLF 转裸 LF）
        # 会带着「有 TAB、有 CRLF」继续变绿，而解析器吃的是每条声明各自的分隔符。
        self.assertEqual(self.raw.count(b'\t'), EXPECTED_TABS)
        self.assertEqual(self.raw.count(b'\r\n'), EXPECTED_CRLFS)
        self.assertEqual(self.raw.count(b'\n'), EXPECTED_CRLFS)   # 裸 LF 为 0（LF 总数 == CRLF 数）

    def test_no_trailing_newline(self):
        # 「结尾多一个换行」是另一种形状漂移：按行切分的写法会受影响，
        # 而上面所有计数都不会因为它变红。
        self.assertFalse(self.raw.endswith((b'\n', b'\r')))
        self.assertEqual(self.raw[-1:], b';')

    def test_every_value_has_exactly_five_decimals(self):
        # Task 2/4 的精度工作假设「每个值恰好 5 位小数」。先钉住值总数，
        # 否则推导一旦退化（花括号没捕到内容），「每个值都合格」会在空列表上假绿。
        vals = [v.strip() for _, _, body in DECL_RE.findall(self.text)
                for v in body.split(',') if v.strip()]
        self.assertEqual(len(vals), EXPECTED_VALUES)
        bad = [v for v in vals if not DECIMAL_RE.fullmatch(v)]
        self.assertEqual(bad, [])

    def test_declared_length_equals_value_count(self):
        # 真实样例里这种不符情形为 0 条（实测），所以这条断言的是夹具自身的自洽性：
        # [N] 就是数组宽度，Task 2 的解析器以此为前提。
        for _, declared, body in DECL_RE.findall(self.text):
            self.assertEqual(int(declared), len([v for v in body.split(',') if v.strip()]))

    def test_names_are_all_virtualized(self):
        # 对照组：虚拟化后名称一律 WT####，任何其它形态都说明漏替换
        bad = [n for n in re.findall(r'double\s+(\w+)\s*\[', self.text)
               if not re.fullmatch(r'WT\d{4}', n)]
        self.assertEqual(bad, [])
```

- [ ] **Step 6: 跑测试**

```bash
python manage.py test test.backend.test_weight_fixture -v 2
```
Expected: **7 例全 PASS**。若 TAB/CRLF 两条红，先分清是哪一半：`git ls-files --eol` 应当报
`i/crlf w/crlf attr/-text` —— 报 `i/lf` 说明入库时就规范化了（`.gitattributes` 没管住），
报 `w/lf` 说明工作树被改过（`core.autocrlf` 在检出时动的手），两种修法不同，别一律去改 `.gitattributes`。

- [ ] **Step 7: 入库前扫一遍真实标识符**

```bash
git add test/fixtures/weight/trim_weight_ci.csv .gitattributes scripts/make_weight_ci_fixture.py test/backend/test_weight_fixture.py
git diff --cached --name-only          # 必须恰好 4 个文件（Step 5 的测试文件在这里，别漏）
python - <<'PY'
import io
t = io.open('test/fixtures/weight/trim_weight_ci.csv', encoding='utf-8').read()
s = io.open('scripts/make_weight_ci_fixture.py', encoding='utf-8').read()
assert 'Trim_TrimWeight' not in t and 'Trim_TrimWeight' not in s, '真实名残留'
print('residue scan ok')
PY
```
Expected: `residue scan ok`。

- [ ] **Step 8: Commit**

```bash
git commit -m "test(weight): 虚拟化权重样例夹具入仓，钉住 56/14/四次的形状"
```

---

## Task 2: 后端解析器（纯模块，零 Django 依赖）

**Files:**
- Create: `apps/weight/__init__.py`（空文件，先建出来让 import 成立）
- Create: `apps/weight/parser.py`
- Test: `test/backend/test_weight_parser.py`

**Interfaces:**
- Consumes: `test/fixtures/weight/trim_weight_ci.csv`
- Produces（Task 3/5/6 都按这些名字与类型对接，**不许改名**）：
  - `WeightError(code: str, **fields)` —— 属性 `.code: str`、`.fields: dict`
  - `WeightSeries(name: str, source_index: int, declared_length: int, decimals: int, values: tuple[float | None, ...])`
  - `WeightGroup(index: int, name: str, first_row: int, series: tuple[WeightSeries, ...], mean: WeightSeries)`
  - `WeightDoc(filename_hint: str, groups: tuple[WeightGroup, ...], code_max: int, series_count: int, group_count: int)`
  - `parse_weight_text(text: str, *, filename_hint: str = '') -> WeightDoc`
  - `compute_mean(members: Sequence[WeightSeries], name: str) -> WeightSeries`
  - `doc_to_payload(doc: WeightDoc) -> dict`（JSON 可序列化，NaN→None）
  - 常量 `TEXT_LIMIT = 2_000_000`、`DECLARATION_LIMIT = 2000`、`LENGTH_LIMIT = 1024`、`MEAN_DECIMALS = 6`

- [ ] **Step 1: 写失败测试（全组合放 T1，不在浏览器里点）**

```python
# test/backend/test_weight_parser.py
"""apps/weight/parser.py 契约：解析 / 分组 / 命名 / 逐点均值 / 报错带行号。"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
import django  # noqa: E402
django.setup()
from django.test import TestCase  # noqa: E402

from apps.weight.parser import (  # noqa: E402
    DECLARATION_LIMIT, LENGTH_LIMIT, TEXT_LIMIT,
    WeightError, compute_mean, doc_to_payload, parse_weight_text,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE = os.path.join(_ROOT, 'test', 'fixtures', 'weight', 'trim_weight_ci.csv')
SINGLE = 'double A[3] = {1.5, 2.5, 3.5};\n'


def _mean_series(*rows):
    """按 members 构造一条用于均值断言的组（绕过解析，隔离测试点）。"""
    from apps.weight.parser import WeightSeries
    return [WeightSeries(n, i + 1, len(v), 5, tuple(v)) for i, (n, v) in enumerate(rows)]


class ParseRealFixtureTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with io.open(FIXTURE, encoding='utf-8', newline='') as f:
            cls.doc = parse_weight_text(f.read(), filename_hint='trim_weight_ci')

    def test_shape(self):
        self.assertEqual(self.doc.group_count, 14)
        self.assertEqual(self.doc.series_count, 56)
        self.assertEqual(self.doc.code_max, 63)          # 最大数组长度 64 → 轴上界 63
        self.assertEqual(len(self.doc.groups[0].series), 4)

    def test_group_order_is_first_appearance(self):
        names = [g.name for g in self.doc.groups]
        self.assertEqual(len(names), len(set(names)))
        with io.open(FIXTURE, encoding='utf-8', newline='') as f:
            first_seen = re.findall(r'double\s+(\w+)\s*\[', f.read())
        self.assertEqual(names, list(dict.fromkeys(first_seen)))  # 组序 == 首次出现序
        self.assertEqual(self.doc.groups[0].series[0].name, 'WT0001_1')
        self.assertEqual(self.doc.groups[0].series[3].name, 'WT0001_4')

    def test_mean_present_and_pointwise(self):
        g = self.doc.groups[0]
        self.assertEqual(g.mean.name, 'WT0001_Avg')
        s0, s1 = g.series[0].values, g.series[1].values
        self.assertAlmostEqual(g.mean.values[0], (s0[0] + s1[0] + g.series[2].values[0]
                                                 + g.series[3].values[0]) / 4, places=12)

    def test_declared_length_equals_value_count_for_all_56(self):
        for g in self.doc.groups:
            for s in list(g.series):
                self.assertEqual(len(s.values), s.declared_length, s.name)


class NamingAndMeanTests(TestCase):
    def test_single_occurrence_keeps_original_name(self):
        doc = parse_weight_text(SINGLE)
        self.assertEqual(doc.groups[0].series[0].name, 'A')
        self.assertEqual(doc.groups[0].series[0].source_index, 1)

    def test_repeated_name_gets_suffix_for_all_members(self):
        doc = parse_weight_text(SINGLE + SINGLE)
        self.assertEqual([s.name for s in doc.groups[0].series], ['A_1', 'A_2'])

    def test_case_sensitive_names_split_groups(self):
        doc = parse_weight_text('double A[1] = {1.0};\ndouble a[1] = {2.0};\n')
        self.assertEqual(doc.group_count, 2)

    def test_mean_of_unequal_lengths_only_over_available_values(self):
        m = compute_mean(_mean_series(('A_1', [1.0, 2.0]), ('A_2', [3.0])), 'A_Avg')
        self.assertEqual(m.values, (2.0, 2.0))     # code0=(1+3)/2, code1=2/1
        self.assertEqual(m.declared_length, 2)     # 长度取组内最大

    def test_mean_length_uses_group_maximum_and_gaps_stay_none(self):
        m = compute_mean(_mean_series(('A_1', [1.0]), ('A_2', [2.0, 4.0, 6.0])), 'A_Avg')
        self.assertEqual(m.values, (1.5, 4.0, 6.0))
        self.assertEqual(m.declared_length, 3)


class ErrorAndLimitTests(TestCase):
    def assert_code(self, text, code, **fields):
        with self.assertRaises(WeightError) as cm:
            parse_weight_text(text)
        self.assertEqual(cm.exception.code, code)
        for k, v in fields.items():
            self.assertEqual(cm.exception.fields.get(k), v, f'字段 {k} 不符')

    def test_no_declaration(self):
        self.assert_code('print("hi")\n\n', 'no_declaration')

    def test_length_mismatch_carries_line_and_counts(self):
        self.assert_code('double A[3] = {1.0, 2.0};\n', 'weight_length_mismatch',
                         line=1, name='A', declared=3, actual=2)

    def test_length_mismatch_line_counts_prior_newlines(self):
        self.assert_code(SINGLE + 'double B[2] = {1.0};\n', 'weight_length_mismatch', line=2)

    def test_bad_number_carries_line_and_token(self):
        self.assert_code('double A[2] = {1.0, x};\n', 'weight_bad_number', line=1, token='x')

    def test_nan_and_inf_literals_are_rejected(self):
        for tok in ('nan', 'inf', '-inf', 'NaN'):
            self.assert_code(f'double A[1] = {{{tok}}};\n', 'weight_bad_number', token=tok)

    def test_underscore_digit_separators_are_rejected(self):
        self.assert_code('double A[1] = {1_000};\n', 'weight_bad_number', token='1_000')

    def test_scientific_notation_is_accepted(self):
        doc = parse_weight_text('double A[2] = {1.5e-3, 2E2};\n')
        self.assertEqual(doc.groups[0].series[0].values, (0.0015, 200.0))

    def test_tab_between_keyword_and_name_is_accepted(self):
        doc = parse_weight_text('double\tA[2] = {1.0, 2.0};\n')
        self.assertEqual(doc.group_count, 1)

    def test_lf_only_and_crlf_both_accepted(self):
        a = parse_weight_text('double A[2] = {1.0, 2.0};\ndouble B[1] = {3.0};\n')
        b = parse_weight_text('double A[2] = {1.0, 2.0};\r\ndouble B[1] = {3.0};\r\n')
        self.assertEqual([g.name for g in a.groups], [g.name for g in b.groups])

    def test_trailing_comma_is_tolerated(self):
        doc = parse_weight_text('double A[2] = {1.0, 2.0,};\n')
        self.assertEqual(len(doc.groups[0].series[0].values), 2)

    def test_text_limit(self):
        big = 'double A[1] = {1.0};\n' * (TEXT_LIMIT // len('double A[1] = {1.0};\n') + 1)
        self.assert_code(big, 'weight_too_large', which='text', limit=TEXT_LIMIT)

    def test_declaration_limit(self):
        many = '\n'.join(f'double N{i}[1] = {{1.0}};' for i in range(DECLARATION_LIMIT + 1))
        self.assert_code(many, 'weight_too_large', which='declarations', limit=DECLARATION_LIMIT)

    def test_length_limit(self):
        self.assert_code('double A[%d] = {%s};\n' % (LENGTH_LIMIT + 1, ','.join(['1.0'] * (LENGTH_LIMIT + 1))),
                         'weight_too_large', which='length', limit=LENGTH_LIMIT)


class PayloadShapeTests(TestCase):
    def test_payload_keys_and_nan(self):
        doc = parse_weight_text(SINGLE)
        p = doc_to_payload(doc)
        self.assertEqual(sorted(p), ['code_max', 'group_count', 'groups', 'series_count'])
        s = p['groups'][0]['series'][0]
        self.assertEqual(sorted(s), ['decimals', 'declared_length', 'name', 'source_index', 'values'])
        self.assertEqual(p['groups'][0]['mean']['name'], 'A_Avg')

    def test_decimals_recorded_from_source_text(self):
        doc = parse_weight_text('double A[2] = {1.50, 2.5};\n')
        self.assertEqual(doc.groups[0].series[0].decimals, 2)


if __name__ == '__main__':
    from django.test.runner import DiscoverRunner
    sys.exit(1 if DiscoverRunner(verbosity=1).run_tests(
        ['test.backend.test_weight_parser']) else 0)
```

- [ ] **Step 2: 跑到失败**

```bash
python manage.py test test.backend.test_weight_parser -v 1
```
Expected: `ModuleNotFoundError: No module named 'apps.weight.parser'`（先确认失败原因确实是缺模块，不是收集问题）。

- [ ] **Step 3: 写实现**

```python
# apps/weight/parser.py
"""权重 CSV 解析：`double 名称[n] = {v,…};` → 分组 / 序号命名 / 逐点均值。

零 Django、零 Excel 依赖 —— parse 端点与 xlsx 构建共用这唯一一份（spec §2 第 4 条）。
错误只给机器码 + 结构化字段，中文文案在前端 ERROR_CODE_MAP（spec §3.3）。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Sequence

TEXT_LIMIT = 2_000_000
DECLARATION_LIMIT = 2000
LENGTH_LIMIT = 1024
MEAN_DECIMALS = 6

DECL_RE = re.compile(
    r'double\s+(?P<name>[A-Za-z_]\w*)\s*\[\s*(?P<length>\d+)\s*\]\s*=\s*\{(?P<body>[^}]*)\}\s*;'
)
# 数字的形状守卫：字符类里没有 `_`，所以 `1_000` 过不了 fullmatch，不需要额外的下划线子句。
NUMBER_RE = re.compile(r'[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?')


class WeightError(Exception):
    def __init__(self, code: str, **fields):
        super().__init__(code)
        self.code = code
        self.fields = fields


@dataclass(frozen=True)
class WeightSeries:
    name: str
    source_index: int
    declared_length: int
    decimals: int
    values: tuple[float | None, ...]


@dataclass(frozen=True)
class WeightGroup:
    index: int
    name: str
    first_row: int
    series: tuple[WeightSeries, ...]
    mean: WeightSeries


@dataclass(frozen=True)
class WeightDoc:
    filename_hint: str
    groups: tuple[WeightGroup, ...]
    code_max: int
    series_count: int
    group_count: int


def _decimals_of(token: str) -> int:
    mantissa = token.lower().split('e')[0]
    return len(mantissa.split('.')[1]) if '.' in mantissa else 0


def _parse_values(body: str, *, line: int, name: str) -> tuple[list[float], int]:
    values: list[float] = []
    decimals = 0
    for raw in body.split(','):
        token = raw.strip()
        if not token:
            continue                      # 容忍尾随逗号
        if not NUMBER_RE.fullmatch(token):
            raise WeightError('weight_bad_number', line=line, token=token)
        v = float(token)
        if not math.isfinite(v):          # float() 认 nan/inf，必须显式拒（lessons R4①）
            raise WeightError('weight_bad_number', line=line, token=token)
        values.append(v)
        decimals = max(decimals, _decimals_of(token))
    return values, decimals


def compute_mean(members: Sequence[WeightSeries], name: str) -> WeightSeries:
    width = max((len(m.values) for m in members), default=0)
    means: list[float | None] = []
    for i in range(width):
        pool = [m.values[i] for m in members if i < len(m.values) and m.values[i] is not None]
        means.append(sum(pool) / len(pool) if pool else None)
    return WeightSeries(name=name, source_index=0, declared_length=width,
                        decimals=MEAN_DECIMALS, values=tuple(means))


def parse_weight_text(text: str, *, filename_hint: str = '') -> WeightDoc:
    if len(text) > TEXT_LIMIT:
        raise WeightError('weight_too_large', which='text', limit=TEXT_LIMIT)

    matches = list(DECL_RE.finditer(text))
    if not matches:
        raise WeightError('no_declaration')
    if len(matches) > DECLARATION_LIMIT:
        raise WeightError('weight_too_large', which='declarations', limit=DECLARATION_LIMIT)

    order: list[str] = []
    buckets: dict[str, list[WeightSeries]] = {}
    for n, m in enumerate(matches, start=1):
        line = text.count('\n', 0, m.start()) + 1
        declared = int(m.group('length'))
        if declared > LENGTH_LIMIT:
            raise WeightError('weight_too_large', which='length', limit=LENGTH_LIMIT, line=line)
        values, decimals = _parse_values(m.group('body'), line=line, name=m.group('name'))
        if len(values) != declared:
            raise WeightError('weight_length_mismatch', line=line, name=m.group('name'),
                              declared=declared, actual=len(values))
        name = m.group('name')
        if name not in buckets:
            buckets[name] = []
            order.append(name)
        buckets[name].append(WeightSeries(name, n, declared, decimals, tuple(values)))

    groups = []
    for gi, name in enumerate(order):
        members = buckets[name]
        if len(members) > 1:
            members = [WeightSeries(f'{name}_{i + 1}', s.source_index, s.declared_length,
                                    s.decimals, s.values) for i, s in enumerate(members)]
        groups.append(WeightGroup(index=gi, name=name, first_row=members[0].source_index,
                                  series=tuple(members),
                                  mean=compute_mean(members, f'{name}_Avg')))

    # 钳到 0：全是 `double A[0] = {};` 时不该开出 0..-1 的轴（Task 3/4/6 都无守卫地消费它），
    # 也不为零长度数组开新错误码——它合法，只是不贡献任何点。
    code_max = max(max(s.declared_length for g in groups for s in g.series) - 1, 0)
    return WeightDoc(filename_hint=filename_hint, groups=tuple(groups), code_max=code_max,
                     series_count=sum(len(g.series) for g in groups), group_count=len(groups))


def _series_to_dict(s: WeightSeries) -> dict:
    return {'name': s.name, 'source_index': s.source_index, 'declared_length': s.declared_length,
            'decimals': s.decimals, 'values': list(s.values)}


def doc_to_payload(doc: WeightDoc) -> dict:
    return {
        'code_max': doc.code_max,
        'group_count': doc.group_count,
        'series_count': doc.series_count,
        'groups': [{'index': g.index, 'name': g.name, 'first_row': g.first_row,
                    'series': [_series_to_dict(s) for s in g.series],
                    'mean': _series_to_dict(g.mean)} for g in doc.groups],
    }
```

- [ ] **Step 4: 跑到全绿**

```bash
python manage.py test test.backend.test_weight_parser -v 2
```
Expected: 全 PASS。`test_group_order_is_first_appearance` 里那条 `and` 怪断言请顺手删掉，
只留 `assertEqual(..., 'WT0001_1')` / `'WT0001_4'` 两条显式断言。

- [ ] **Step 5: 提交前快门禁**

```bash
cd frontend && npm run test:e2e:affected
```
Expected: 打印 `NO AFFECTED TESTS` + `note:`（这两批只加了后端测试与脚本，不由浏览器承载）——
**这不是绿灯**，绿灯证据是 Step 4 的 Django 测试输出。

- [ ] **Step 6: Commit**

```bash
git add apps/weight/__init__.py apps/weight/parser.py test/backend/test_weight_parser.py
git commit -m "feat(weight): 后端解析 C 声明式权重 CSV，分组命名与逐点均值"
```

---

## Task 3: Django app 注册 + `/parse/` 端点

**Files:**
- Create: `apps/weight/apps.py`、`apps/weight/views.py`、`apps/weight/urls.py`
- Modify: `config/settings/base.py:56-66`（INSTALLED_APPS 那组之后）、`config/urls.py:10-22`
- Test: `test/backend/test_weight_api.py`

**Interfaces:**
- Consumes: Task 2 的 `parse_weight_text`、`doc_to_payload`、`WeightError`、三个 LIMIT
- Produces: `POST /api/v1/weight/parse/`，请求体 `{filename: str, text: str}`；
  200 响应体 = `doc_to_payload()` 再加 `'filename'`（原样回显用户文件名，供页面标题用）；
  400 响应体 = `{code, message, detail}`（`error_response()` 的形状）

- [ ] **Step 1: 写失败测试**

```python
# test/backend/test_weight_api.py
"""POST /api/v1/weight/parse/ 的契约：守卫、状态码、字段；不测图表。"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
import django  # noqa: E402
django.setup()
from django.test import TestCase  # noqa: E402
from rest_framework.test import APIClient  # noqa: E402

from apps.accounts.models import User  # noqa: E402

URL = '/api/v1/weight/parse/'
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE = os.path.join(_ROOT, 'test', 'fixtures', 'weight', 'trim_weight_ci.csv')


class ParseEndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='w-parse', password='x-pass-12345678')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)   # R6①：Permission 读的是 request._auth

    def _post(self, payload):
        return self.client.post(URL, data=json.dumps(payload),
                                content_type='application/json')

    def test_requires_auth(self):
        anon = APIClient()
        self.assertIn(anon.post(URL, data='{}', content_type='application/json').status_code,
                      (401, 403))

    def test_happy_path_counts(self):
        with io.open(FIXTURE, encoding='utf-8', newline='') as f:
            r = self._post({'filename': 'trim_weight_ci.csv', 'text': f.read()})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual((body['group_count'], body['series_count'], body['code_max']), (14, 56, 63))
        self.assertEqual(body['filename'], 'trim_weight_ci.csv')
        self.assertEqual(body['groups'][0]['series'][0]['name'], 'WT0001_1')

    def test_error_body_shape(self):
        r = self._post({'filename': 'x.csv', 'text': 'no declarations here\n'})
        self.assertEqual(r.status_code, 400)
        body = r.json()
        self.assertEqual(body['code'], 'no_declaration')
        self.assertIn('message', body)          # detail 为 None 时前端靠 ERROR_CODE_MAP，不靠这层

    def test_mismatch_detail_is_structured(self):
        r = self._post({'filename': 'x.csv', 'text': 'double A[3] = {1.0, 2.0};\n'})
        self.assertEqual(r.status_code, 400)
        d = r.json()['detail']
        self.assertEqual((d['line'], d['name'], d['declared'], d['actual']), (1, 'A', 3, 2))

    def test_missing_fields_are_param_required(self):
        for payload in ({}, {'text': 'double A[1] = {1.0};'}, {'filename': 'a.csv'}):
            r = self._post(payload)
            self.assertEqual(r.status_code, 400, payload)
            self.assertEqual(r.json()['code'], 'param_required')

    def test_non_text_types_are_rejected(self):
        # R3②：不能假设前端已经过滤过
        for bad in (123, [], None, {'a': 1}):
            r = self._post({'filename': 'a.csv', 'text': bad})
            self.assertEqual(r.status_code, 400, bad)
            self.assertEqual(r.json()['code'], 'param_required')

    def test_filename_length_is_capped_not_trusted(self):
        r = self._post({'filename': 'x' * 300, 'text': 'double A[1] = {1.0};\n'})
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(r.json()['filename']), 120)


if __name__ == '__main__':
    from django.test.runner import DiscoverRunner
    sys.exit(1 if DiscoverRunner(verbosity=1).run_tests(['test.backend.test_weight_api']) else 0)
```

- [ ] **Step 2: 跑到失败**

```bash
python manage.py test test.backend.test_weight_api -v 1
```
Expected: 404/`NoReverseMatch`/`ModuleNotFoundError` 一类的「端点不存在」失败，而不是断言不符。

- [ ] **Step 3: 写实现**

```python
# apps/weight/apps.py
from django.apps import AppConfig


class WeightConfig(AppConfig):
    name = 'apps.weight'
    verbose_name = '权重画图'
```

```python
# apps/weight/views.py
"""权重画图的端点：解析（Task 3）与 xlsx 导出（Task 5）。

不落库、不落盘、不用 multipart（spec §4）。同步 FileResponse —— 作业化那条路要求 DataFile 行。
"""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.errors import error_response

from .parser import WeightError, doc_to_payload, parse_weight_text

FILENAME_MAX = 120


def _bad_input(**extra):
    # detail 一律留空：非空字符串会被 errors.py 复制成 message，并在前端赢过 ERROR_CODE_MAP 的中文
    return error_response('param_required', None, **extra)


class WeightParseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        text = request.data.get('text')
        filename = request.data.get('filename')
        if not isinstance(text, str) or not text:
            return _bad_input(field='text')
        if not isinstance(filename, str) or not filename:
            return _bad_input(field='filename')
        try:
            doc = parse_weight_text(text, filename_hint=filename[:FILENAME_MAX])
        except WeightError as exc:
            return error_response(exc.code, exc.fields or None, **exc.fields)
        return Response({**doc_to_payload(doc), 'filename': filename[:FILENAME_MAX]})
```

```python
# apps/weight/urls.py
from django.urls import path

from .views import WeightParseView

urlpatterns = [
    path('weight/parse/', WeightParseView.as_view(), name='weight-parse'),
]
```

`config/settings/base.py`：在第 66 行 `'apps.jobs',` 之后加一行 `'apps.weight',`。
`config/urls.py`：在第 21 行 `path('api/v1/', include('apps.sftp.urls')),` 之后加
`path('api/v1/', include('apps.weight.urls')),`。

- [ ] **Step 4: 跑到全绿**

```bash
python manage.py test test.backend.test_weight_api test.backend.test_weight_parser -v 1
```
Expected: 两个模块合计全 PASS。

- [ ] **Step 5: 冒烟一下 URL 真的挂上（不靠测试自证）**

```bash
python manage.py shell -c "from django.urls import resolve; print(resolve('/api/v1/weight/parse/').func.__name__)"
```
Expected: 打印 `view`（不是 `Resolver404`）。

- [ ] **Step 6: Commit**

```bash
git add apps/weight/ config/settings/base.py config/urls.py test/backend/test_weight_api.py
git commit -m "feat(weight): 新增 /api/v1/weight/parse/ 解析端点，零落库"
```

---

## Task 4: xlsx 构建器（原生 Excel 图）

**Files:**
- Create: `apps/weight/xlsx.py`
- Test: `test/backend/test_weight_xlsx.py`

**Interfaces:**
- Consumes: Task 2 的 `WeightDoc` / `WeightGroup` / `WeightSeries`
- Produces:
  - `build_weight_workbook(doc: WeightDoc, *, sheet_base: str, visible_group_indexes=None,
    show_mean: bool = False, palette: Sequence[str],
    mean_color: str = '4B5563') -> bytes`
  - `weight_sheet_name(sheet_base: str) -> str`
  - 常量 `COL_SOURCE_INDEX = 15`（O）、`COL_NAME = 16`（P）、`COL_VALUE0 = 17`（Q）、
    `HEADER_ROW = 3`、`FIRST_DATA_ROW = 4`、`DASH_BY_WITHIN_GROUP = ('solid', 'dash', 'dot', 'dashDot')`、
    `PT = 12700`（1 pt 的 EMU）
  - **已实测的 openpyxl 形态**（`tasks/probe_openpyxl_chart3.py` 留着当证据）：
    `ScatterChart().x_axis` 默认就是 `NumericAxis`；`Marker(symbol='none')` 序列化成
    `<marker><symbol val="none"/>`；`Series(yref, xref, title=...)` 的名字往返读得到（`series.tx.v`）；
    **散点系列的 y 住在 `series.yVal.numRef.f`，`series.val` 是 None**；
    `load_workbook` 读回 `_charts` 有对象（长度 1），但 `marker.symbol` 读回是 `None` ⇒
    marker 只能断 XML 子串，不能断对象属性。

- [ ] **Step 1: 写失败测试**

```python
# test/backend/test_weight_xlsx.py
"""apps/weight/xlsx.py：表几何、系列集合、颜色线型、图例上限的实测断言。"""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
import django  # noqa: E402
django.setup()
from django.test import TestCase  # noqa: E402
from openpyxl import load_workbook  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

from apps.weight.parser import parse_weight_text  # noqa: E402
from apps.weight.xlsx import (  # noqa: E402
    COL_NAME, COL_SOURCE_INDEX, COL_VALUE0, DASH_BY_WITHIN_GROUP, FIRST_DATA_ROW,
    HEADER_ROW, build_weight_workbook, weight_sheet_name,
)

SHEET = 'trim_weight_ci'
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE = os.path.join(_ROOT, 'test', 'fixtures', 'weight', 'trim_weight_ci.csv')


def _doc():
    with io.open(FIXTURE, encoding='utf-8', newline='') as f:
        return parse_weight_text(f.read(), filename_hint=SHEET)


def _book(doc, **kw):
    ws = load_workbook(io.BytesIO(build_weight_workbook(doc, sheet_base=SHEET, **kw)))
    return ws[weight_sheet_name(SHEET)]


class GeometryTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doc = _doc()
        cls.ws = _book(cls.doc)

    def test_constants(self):
        self.assertEqual((COL_SOURCE_INDEX, COL_NAME, COL_VALUE0, HEADER_ROW, FIRST_DATA_ROW),
                         (15, 16, 17, 3, 4))

    def test_header_row(self):
        self.assertEqual(self.ws.cell(HEADER_ROW, COL_SOURCE_INDEX).value, '原序号')
        self.assertEqual(self.ws.cell(HEADER_ROW, COL_NAME).value, '系列名')
        self.assertEqual(self.ws.cell(HEADER_ROW, COL_VALUE0).value, 0)
        self.assertEqual(self.ws.cell(HEADER_ROW, COL_VALUE0 + 63).value, 63)

    def test_rows_are_grouped_in_first_appearance_order(self):
        names = [self.ws.cell(FIRST_DATA_ROW + i, COL_NAME).value for i in range(56)]
        self.assertEqual(names[0], 'WT0001_1')
        self.assertEqual(names[3], 'WT0001_4')
        self.assertEqual(names[4], 'WT0002_1')      # 第 5 行已经是第二组

    def test_mean_rows_absent_by_default(self):
        self.assertNotIn('WT0001_Avg',
                         [self.ws.cell(FIRST_DATA_ROW + i, COL_NAME).value for i in range(70)])

    def test_number_format_follows_source_decimals(self):
        """真实样例（及夹具）的小数位**只有 5 位**（实测小数位分布 = [5]），
        拿夹具断这条不承重：实现里写死 '0.00000' 也照样绿。必须用混合精度的合成 doc。"""
        doc = parse_weight_text('double A[2] = {1.0, 2.5};\n'
                                'double B[2] = {3.25, 4.75};\n'
                                'double C[2] = {5, 6};\n')
        ws = load_workbook(io.BytesIO(build_weight_workbook(doc, sheet_base='syn')))['权重图_syn']
        self.assertEqual([ws.cell(FIRST_DATA_ROW + i, COL_VALUE0).number_format for i in range(3)],
                         ['0.0', '0.00', '0'])

    def test_no_pane_freeze_and_code_columns_are_narrow(self):
        self.assertIsNone(self.ws.freeze_panes)              # 源稿 §4.3：不冻结窗格
        self.assertEqual(self.ws.column_dimensions[get_column_letter(COL_VALUE0)].width, 7)
        self.assertGreater(self.ws.column_dimensions[get_column_letter(COL_NAME)].width, 14)


class ChartTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doc = _doc()
        cls.ws = _book(cls.doc)
        cls.chart = cls.ws._charts[0]
        cls.xml = zipfile.ZipFile(io.BytesIO(build_weight_workbook(cls.doc, sheet_base=SHEET))
                                  ).read('xl/charts/chart1.xml').decode('utf-8')

    def test_series_count_is_56_and_names_match_rows(self):
        self.assertEqual(len(self.chart.series), 56)
        self.assertEqual([s.tx.v for s in self.chart.series[:4]],
                         ['WT0001_1', 'WT0001_2', 'WT0001_3', 'WT0001_4'])

    def _flat_index_of(self, target) -> int:
        """该系列在全可见、关均值状态下是第几行（0 基），与 build_weight_workbook 的写行顺序同构。"""
        flat = [s for g in self.doc.groups for s in g.series]
        for i, s in enumerate(flat):
            if s.name == target.name and s.values == target.values:
                return i
        raise AssertionError('目标系列不在展平序列里')

    def _ref(self, col0: int, col1: int, row: int) -> str:
        q = get_column_letter
        return f"'{weight_sheet_name(SHEET)}'!${q(col0)}${row}:${q(col1)}${row}"

    def test_short_series_use_own_length_not_padded(self):
        """素材前置断言：夹具里必须真的存在短数组，否则这条判据不承重（lessons 2026-10-17 批3）。"""
        s = min((x for g in self.doc.groups for x in g.series), key=lambda x: len(x.values))
        self.assertLess(len(s.values), self.doc.code_max + 1, '素材全是最长数组，断言会假绿')
        row = FIRST_DATA_ROW + self._flat_index_of(s)
        self.assertEqual(self.chart.series[row - FIRST_DATA_ROW].yVal.numRef.f,
                         self._ref(COL_VALUE0, COL_VALUE0 + len(s.values) - 1, row))

    def test_x_ref_spans_full_axis_for_every_series(self):
        want = self._ref(COL_VALUE0, COL_VALUE0 + self.doc.code_max, HEADER_ROW)
        for ser in self.chart.series:
            self.assertEqual(ser.xVal.numRef.f, want)

    def test_markers_are_disabled(self):
        # marker.symbol 往返是 None（与「未设置」同形），只能断 XML
        self.assertIn('<symbol val="none"/>', self.xml)

    def test_all_four_dash_tokens_survive(self):
        for tok in DASH_BY_WITHIN_GROUP:
            self.assertIn(f'prstDash val="{tok}"', self.xml)

    def test_legend_is_removed(self):
        self.assertIsNone(self.chart.legend)
        self.assertNotIn('<legend', self.xml)

    def test_axis_title_and_scaling(self):
        self.assertEqual((self.chart.x_axis.scaling.min, self.chart.x_axis.scaling.max), (0.0, 63.0))
        self.assertEqual(_axis_title(self.chart.x_axis), 'Code')   # Title 的属性是 tx，不是 txt
        self.assertEqual(_axis_title(self.chart.y_axis), 'Weight')  # 读回走 tx.rich.p[].r[].t

    def test_chart_anchor_is_a1(self):
        self.assertEqual(self.ws._charts[0].anchor._from.col, 0)
        self.assertEqual(self.ws._charts[0].anchor._from.row, 0)


class VisibilityAndMeanTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.doc = _doc()

    def test_only_visible_groups_enter_the_chart_and_table_keeps_all_rows(self):
        ws = _book(self.doc, visible_group_indexes=[1])
        self.assertEqual(len(ws._charts[0].series), 4)
        self.assertEqual(ws.cell(FIRST_DATA_ROW, COL_NAME).value, 'WT0001_1')  # 表不删行（源稿 §6 规则）

    def test_show_mean_adds_14_series_and_rows(self):
        ws = _book(self.doc, show_mean=True)
        self.assertEqual(len(ws._charts[0].series), 70)
        self.assertEqual(ws.cell(FIRST_DATA_ROW + 4, COL_NAME).value, 'WT0001_Avg')

    def test_mean_is_last_within_its_group(self):
        ws = _book(self.doc, visible_group_indexes=[0, 1], show_mean=True)
        got = [ws.cell(FIRST_DATA_ROW + i, COL_NAME).value for i in range(10)]
        self.assertEqual(got, ['WT0001_1', 'WT0001_2', 'WT0001_3', 'WT0001_4', 'WT0001_Avg',
                               'WT0002_1', 'WT0002_2', 'WT0002_3', 'WT0002_4', 'WT0002_Avg'])

    def test_mean_cell_format_is_six_decimals_and_none_becomes_blank(self):
        ws = _book(self.doc, show_mean=True)
        self.assertEqual(ws.cell(FIRST_DATA_ROW + 4, COL_VALUE0).number_format, '0.000000')


class SheetNameTests(TestCase):
    def test_illegal_chars_become_underscore(self):
        # 'a[]:*?/\b' → a + 7 个非法字符 + b
        self.assertEqual(weight_sheet_name('a[]:*?/\\b'), '权重图_a' + '_' * 7 + 'b')

    def test_uses_the_whole_31_char_budget(self):
        got = weight_sheet_name('x' * 99)
        self.assertEqual(len(got), 31)               # 前缀 4 + 名称 27
        self.assertTrue(got.startswith('权重图_'))

    def test_trailing_dot_is_stripped(self):
        # Excel 拒绝以 . 结尾的表名；调用方虽已去扩展名，这里仍要自守
        self.assertFalse(weight_sheet_name('abc.').endswith('.'))

    def test_empty_base_falls_back_to_weight(self):
        # (base or 'weight')：空串走默认名，不会产出只有前缀的表名
        self.assertEqual(weight_sheet_name(''), '权重图_weight')
```

- [ ] **Step 2: 跑到失败**

```bash
python manage.py test test.backend.test_weight_xlsx -v 1
```
Expected: `ModuleNotFoundError: No module named 'apps.weight.xlsx'`。

- [ ] **Step 3: 写实现**

```python
# apps/weight/xlsx.py
"""权重画图 → xlsx：数值表 + openpyxl 原生散点折线图（无标记）。

与页面同一解析器（spec §2 第 4 条）；颜色由调用方按当前主题传入，本模块不存色板，
避免色板两处真源（spec §6.1）。图例默认关闭：Excel 原生图例只能逐系列（spec §7.3）。
"""
from __future__ import annotations

import io
import re
from typing import Sequence

from openpyxl import Workbook
from openpyxl.chart import Reference, ScatterChart, Series
from openpyxl.chart.marker import Marker
from openpyxl.drawing.line import LineProperties
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from apps.export.fonts import EXCEL_FONT_FAMILY

from .parser import WeightDoc, WeightGroup, WeightSeries

COL_SOURCE_INDEX = 15   # O
COL_NAME = 16           # P
COL_VALUE0 = 17         # Q
HEADER_ROW = 3
FIRST_DATA_ROW = 4
CHART_ANCHOR = 'A1'
PT = 12700
LINE_WIDTH = int(1.25 * PT)
MEAN_WIDTH = int(2.5 * PT)
DASH_BY_WITHIN_GROUP = ('solid', 'dash', 'dot', 'dashDot')
CODE_COL_WIDTH = 7          # 源稿 §4.3：code 列窄列宽、允许横向滚动
NAME_COL_WIDTH = 22
INDEX_COL_WIDTH = 8
DEFAULT_PALETTE = ('2563EB', '047857', 'D97706', 'B91C1C', '0284C7', '86198F', '475569', '0D9488')
_MEAN_COLOR_DEFAULT = '4B5563'
_ILLEGAL_SHEET_CHARS = re.compile(r'[\[\]:*?/\\]')


def weight_sheet_name(base: str) -> str:
    """`权重图_<去扩展名的文件名>`；非法字符 `[]:*?/\\` → `_`，总长吃满 31 字符。

    `[:27]` 不是随手写的：前缀 `权重图_` 占 4 字符，4 + 27 = 31 正是 Excel 的表名上限。
    末尾点号必须剥掉（Excel 拒绝以 `.` 结尾的表名），所以调用方要先去扩展名（Task 5 视图负责）。
    """
    cleaned = _ILLEGAL_SHEET_CHARS.sub('_', (base or 'weight')).strip().rstrip('.')[:27]
    return f'权重图_{cleaned}'[:31]


def _hex(value: str, fallback: str) -> str:
    v = (value or '').strip().lstrip('#')
    if len(v) == 6 and all(c in '0123456789abcdefABCDEF' for c in v):
        return v.upper()
    return fallback


def _fmt(decimals: int) -> str:
    return '0' if decimals <= 0 else '0.' + '0' * decimals


def _write_header(ws, code_max: int) -> None:
    ws.cell(HEADER_ROW, COL_SOURCE_INDEX, '原序号')
    ws.cell(HEADER_ROW, COL_NAME, '系列名')
    for code in range(code_max + 1):
        ws.cell(HEADER_ROW, COL_VALUE0 + code, code)
    for col in (COL_SOURCE_INDEX, COL_NAME):
        ws.cell(HEADER_ROW, col).font = Font(name=EXCEL_FONT_FAMILY, bold=True)
    ws.column_dimensions[get_column_letter(COL_SOURCE_INDEX)].width = INDEX_COL_WIDTH
    ws.column_dimensions[get_column_letter(COL_NAME)].width = NAME_COL_WIDTH
    for code in range(code_max + 1):
        ws.column_dimensions[get_column_letter(COL_VALUE0 + code)].width = CODE_COL_WIDTH


def _series_color(palette: Sequence[str], group_index: int) -> str:
    return palette[group_index % len(palette)]


def build_weight_workbook(
    doc: WeightDoc, *, sheet_base: str,
    visible_group_indexes: Sequence[int] | None = None,
    show_mean: bool = False, palette: Sequence[str],
    mean_color: str = _MEAN_COLOR_DEFAULT,
) -> bytes:
    visible = ({g.index for g in doc.groups} if visible_group_indexes is None
               else {int(i) for i in visible_group_indexes})
    pal = tuple(_hex(c, DEFAULT_PALETTE[i % len(DEFAULT_PALETTE)])
                for i, c in enumerate(palette)) or DEFAULT_PALETTE
    mean_hex = _hex(mean_color, _MEAN_COLOR_DEFAULT)

    wb = Workbook()
    ws = wb.active
    ws.title = weight_sheet_name(sheet_base)
    _write_header(ws, doc.code_max)

    row = FIRST_DATA_ROW
    chart_rows: list[tuple[WeightSeries, int, int, int]] = []   # (series, row, group_index, within)
    for g in doc.groups:
        members: list[WeightSeries] = list(g.series) + ([g.mean] if show_mean else [])
        alt_fill = PatternFill('solid', fgColor='F7F7F8') if g.index % 2 else None
        for within, s in enumerate(members):
            is_mean = s is g.mean
            ws.cell(row, COL_SOURCE_INDEX, s.source_index if not is_mean else None)
            name_cell = ws.cell(row, COL_NAME, s.name)
            name_cell.font = Font(
                name=EXCEL_FONT_FAMILY, bold=is_mean,
                color=_series_color(pal, g.index) if not is_mean else mean_hex)
            if alt_fill is not None:
                name_cell.fill = alt_fill
            fmt = _fmt(s.decimals)
            for code, v in enumerate(s.values):
                if v is None:
                    continue
                c = ws.cell(row, COL_VALUE0 + code, v)
                c.number_format = fmt
                c.alignment = Alignment(horizontal='right')
            if g.index in visible:
                chart_rows.append((s, row, g.index, within))
            row += 1

    _add_chart(ws, doc, chart_rows, pal, mean_hex)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _add_chart(ws, doc: WeightDoc, chart_rows, pal, mean_hex) -> None:
    chart = ScatterChart()          # 实测：其 x_axis 默认就是 NumericAxis，不需要换轴类型
    chart.x_axis.scaling.min = 0
    chart.x_axis.scaling.max = doc.code_max
    chart.x_axis.title = 'Code'
    chart.y_axis.title = 'Weight'
    chart.legend = None
    for s, row, group_index, within in chart_rows:
        is_mean = s.name.endswith('_Avg')
        xref = Reference(ws, min_col=COL_VALUE0, min_row=HEADER_ROW,
                         max_col=COL_VALUE0 + doc.code_max, max_row=HEADER_ROW)
        yref = Reference(ws, min_col=COL_VALUE0, min_row=row,
                         max_col=COL_VALUE0 + len(s.values) - 1, max_row=row)
        ser = Series(yref, xref, title=s.name)
        ser.marker = Marker(symbol='none')
        ser.graphicalProperties.line = LineProperties(
            solidFill=mean_hex if is_mean else _series_color(pal, group_index),
            w=MEAN_WIDTH if is_mean else LINE_WIDTH,
            prstDash='solid' if is_mean else DASH_BY_WITHIN_GROUP[within % 4])
        ser.smooth = False
        chart.series.append(ser)
    chart.width, chart.height = CHART_WIDTH_CM, CHART_HEIGHT_CM    # 20 × 23 cm
    # 换算全来自 spec §7.2「约 12 列 × 44 行」，且用的是 Excel 默认值（不是 code 列的 width=7）：
    #   默认列宽 8.43 字符 = 64px = 1.693cm（96dpi）⇒ 12 列 = 20.32cm；O 列起点 = 14 × 1.693 = 23.71cm
    #   默认行高 15pt = 15 × 12700 EMU = 0.5292cm ⇒ 44 行 = 23.28cm；1cm = 360000 EMU
    # ⇒ 20cm 天然留 3.4cm 跑道，不必为怕压表头再缩图；测试断的是这两条恒等式，不是常数。
    ws.add_chart(chart, CHART_ANCHOR)
```

> 上面三段是同一件事的两半：断言里拼单元格区域**必须**用 `openpyxl.utils.get_column_letter`，
> 不能用 `chr(64 + col)`（那只在列号 ≤ 26 时碰巧对，而 `COL_VALUE0 + 63 = 80` 早就过了 Z）。
> 实现里 `Reference` 自己会生成正确的 `f`，所以只有测试侧需要它。

- [ ] **Step 4: 跑到全绿**

```bash
python manage.py test test.backend.test_weight_xlsx -v 2
```
Expected: 全 PASS。⚠ **dash 判据不许写成「整份 chart1.xml 含四种 token 子串」** —— 实测 `<marker>` 自带一段
`<spPr><a:ln prstDash val="solid"/>`，`solid` 永远在全文里 ⇒ 那条断言对 solid 不承重。
正确形态是逐个 `<ser>` 只取它自己的第一个 `<spPr>` 再比 token（已交付实现即如此）。

- [ ] **Step 5: 真开一次 Excel（肉眼验证，自动化做不到）**

```bash
python - <<'PY'
import io, os, sys
sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
import django; django.setup()
import os
from apps.weight.parser import parse_weight_text
from apps.weight.xlsx import build_weight_workbook
t = io.open(os.path.join('test', 'fixtures', 'weight', 'trim_weight_ci.csv'),
            encoding='utf-8', newline='').read()
doc = parse_weight_text(t, filename_hint='trim_weight_ci')
io.open('tasks/weight-sample.xlsx', 'wb').write(build_weight_workbook(
    doc, sheet_base='trim_weight_ci',
    palette=['2563eb', '047857', 'd97706', 'b91c1c', '0284c7', '86198f', '475569', '0d9488']))
print('wrote tasks/weight-sample.xlsx')
PY
```
**不要 `start` 打开 Excel**：那是用户自己的应用，代理这边看不见结果，"肉眼验证"会退化成假验证 ——
产出文件后把路径交给用户，由他开一眼。`palette` 现在是必填实参（`DEFAULT_PALETTE` 只作非法色值的逐项回退）。
Expected: Excel 打开后 —— 左上是折线图且**看不到圆点标记**、组内 4 条线型不同、表从 O 列开始、
`WT0001_1` 那行数值显示位数与原始文本一致、**图没有压住 O/P 两列的表头与系列名**。
最后这条是 `chart.width = 20`（cm）的实测关口：code 列宽只有 7，12 列不到 20cm，图会盖到表格上 ——
压住了就把 `chart.width` 调到不压的值并在此处记录实测数，别改表格几何去迁就图。
这条肉眼结论要写进本任务提交信息。

- [ ] **Step 6: Commit**

```bash
git add apps/weight/xlsx.py test/backend/test_weight_xlsx.py
git commit -m "feat(weight): openpyxl 原生散点折线图导出权重 xlsx"
```

---

## Task 5: `/export/` 端点 + 导出文件名**四处**联动

**Files:**
- Modify: `apps/weight/views.py`（加 `WeightExportView`）、`apps/weight/urls.py`
- Modify: `apps/common/export_naming.py:19-30` 与 `:33-43`
- Modify: `frontend/src/types/index.ts:9-11`（`ExportTypeKey`）、`frontend/src/constants/export-templates.ts:35+`
- Test: `test/backend/test_weight_export_api.py`
- Modify: `apps/accounts/tests.py`（硬编码的导出类型键集合，第四处联动）

**Interfaces:**
- Consumes: Task 2 解析器、Task 4 `build_weight_workbook`、`apps/common/export_naming.py` 的
  `render_export_filename(user, export_type, extension, context)`（第 91 行）与 `base_export_context(user)`（第 79 行）
- Produces: `POST /api/v1/weight/export/`，请求体
  `{filename, text, visible_group_indexes: int[], show_mean: bool, palette: string[8], mean_color: string}`；
  （`show_mean` 卡**真布尔**：脏类型一律 400 `field='show_mean'`，整个键缺席才等于 False）
  200 = xlsx 字节流 + `Content-Disposition`（RFC 5987）；400 同 parse 的错误形状

- ⚠ 两条给后续任务的派工注意（Task 5 实测）：
  ① 导出 lane 走共享的 `render_export_filename`，它内部是 `UserSetting.objects.get_or_create(user=…)`
     （`apps/common/export_naming.py:97`）⇒ **会发 SQL，并且给没有设置行的账号 INSERT 一行 UserSetting**
     （本仓每条既有导出通路同形，写的是账号设置不是权重数据）—— 别从 parse 测试照抄 `assertNumQueries(0)`，
     也别在导出上搭「零写入」断言（spec §4 已把这句话写全）；
  ② 联动点是**四处**不是三处 —— 除后端两张表与前端 `ExportTypeKey`/`EXPORT_TEMPLATE_META` 外，
     `apps/accounts/tests.py:329` 还硬编码了一份导出类型键集合（少加即红）。它故意保留硬编码而不是拿
     `EXPORT_TEMPLATE_DEFAULTS` 比对（那会同义反复）。

- [ ] **Step 1: 写失败测试**

```python
# test/backend/test_weight_export_api.py
import io, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
import django; django.setup()
from django.test import TestCase
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.common.export_naming import EXPORT_TEMPLATE_DEFAULTS, EXPORT_TEMPLATE_VARIABLES

URL = '/api/v1/weight/export/'
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FIXTURE = os.path.join(_ROOT, 'test', 'fixtures', 'weight', 'trim_weight_ci.csv')


class WeightExportApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='w-exp', password='x-pass-12345678')
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        with io.open(FIXTURE, encoding='utf-8', newline='') as f:
            self.text = f.read()

    def _post(self, **over):
        payload = {'filename': 'trim_weight_ci.csv', 'text': self.text,
                   'visible_group_indexes': list(range(14)), 'show_mean': False,
                   'palette': ['2563eb'] * 8, 'mean_color': '4b5563'}
        payload.update(over)
        return self.client.post(URL, data=json.dumps(payload), content_type='application/json')

    def test_returns_xlsx_bytes(self):
        r = self._post()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'],
                         'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        wb = load_workbook(io.BytesIO(b''.join(r.streaming_content)))
        self.assertEqual(wb.sheetnames, ['权重图_trim_weight_ci'])

    def test_chinese_filename_does_not_blow_up(self):
        # WSGI 头只认 latin-1；FileResponse 走 RFC 5987，这里钉住不抛 UnicodeEncodeError
        r = self._post(filename='权重测试-2.csv')
        self.assertEqual(r.status_code, 200)
        # 实测 Django 6.0.5 发的是小写 `filename*=utf-8''`，且非 ASCII 名会**丢掉** ASCII 回退段；
        # 前端 utils/download.ts:28 已容忍这个形态 ⇒ 断实际形状，别照 RFC 的大小写写法断。
        self.assertIn("filename*=utf-8''", r['Content-Disposition'])

    def test_visible_subset_reaches_the_chart(self):
        r = self._post(visible_group_indexes=[3])
        wb = load_workbook(io.BytesIO(b''.join(r.streaming_content)))
        ws = wb['权重图_trim_weight_ci']
        self.assertEqual(len(ws._charts[0].series), 4)

    def test_show_mean_reaches_70(self):
        r = self._post(show_mean=True)
        ws = load_workbook(io.BytesIO(b''.join(r.streaming_content)))['权重图_trim_weight_ci']
        self.assertEqual(len(ws._charts[0].series), 70)

    def test_bad_palette_falls_back_not_500(self):
        # 8 个「形状对但值非法」的色：颜色属表现层，逐项回退默认色而不是拒整个导出
        r = self._post(palette=['zzzzzz', 'x'] + [''] * 6)
        self.assertEqual(r.status_code, 200)
        ws = load_workbook(io.BytesIO(b''.join(r.streaming_content)))['权重图_trim_weight_ci']
        self.assertEqual(len(ws._charts[0].series), 56)

    def test_palette_wrong_length_is_param_required(self):
        # 与上一条配对：长度不对必须拒，否则 palette[i % len] 会静默错位取色
        for bad in (['2563eb'] * 7, '2563eb', None):
            r = self._post(palette=bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertEqual(r.json()['code'], 'param_required')

    def test_sheet_name_drops_the_extension(self):
        # 带扩展名进表名会得到 `权重图_....csv`，Excel 会拒绝打开
        r = self._post()
        self.assertEqual(load_workbook(io.BytesIO(b''.join(r.streaming_content))).sheetnames,
                         ['权重图_trim_weight_ci'])

    def test_missing_fields_are_param_required(self):
        for over in ({'text': ''}, {'palette': 'nope'}, {'visible_group_indexes': 'nope'}):
            r = self._post(**over)
            self.assertEqual(r.status_code, 400, over)
            self.assertEqual(r.json()['code'], 'param_required')

    def test_parse_error_passes_through(self):
        r = self._post(text='nothing here\n')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['code'], 'no_declaration')


class ExportNamingRegisteredTests(TestCase):
    def setUp(self):
        # render_export_filename 内部会 UserSetting.objects.get_or_create(user=…) ⇒ 必须是真实 user
        self.user = User.objects.create_user(username='w-naming', password='x-pass-12345678')

    def test_weight_plot_is_in_both_tables(self):
        self.assertIn('weight_plot', EXPORT_TEMPLATE_DEFAULTS)
        self.assertIn('weight_plot', EXPORT_TEMPLATE_VARIABLES)

    def test_filename_is_not_silent_export_default(self):
        # .get(export_type, 'export') 的兜底会静默给出 export.xlsx —— 这条钉住它没发生
        from apps.common.export_naming import render_export_filename
        name = render_export_filename(self.user, 'weight_plot', 'xlsx',
                                      {'filename': 'trim_weight_ci', 'date': '20261019'})
        self.assertNotEqual(name, 'export.xlsx')
        self.assertTrue(name.endswith('.xlsx'))
        self.assertIn('trim_weight_ci', name)
```

- [ ] **Step 2: 跑到失败**

```bash
python manage.py test test.backend.test_weight_export_api -v 1
```
Expected: 端点 404 + `weight_plot` 不在两张表里。

- [ ] **Step 3: 加两张表的条目**

`apps/common/export_naming.py:19-30`：
```python
    'weight_plot': 'Weight_Plot_{filename}_{date}',
```
`apps/common/export_naming.py:33-43`：
```python
    'weight_plot': ('filename', 'date', 'time', 'datetime', 'user'),
```

- [ ] **Step 4: 前端镜像同步（不做这步 `npm run build` 直接红）**

`frontend/src/types/index.ts:11` 那行之后：
```ts
  | 'weight_plot'
```
`frontend/src/constants/export-templates.ts` 的 `EXPORT_TEMPLATE_META` 里加（与后端两张表逐字同值）：
```ts
  weight_plot: {
    label: '权重画图导出',
    default: 'Weight_Plot_{filename}_{date}',
    extension: 'xlsx',
    variables: ['filename', 'date', 'time', 'datetime', 'user'],
  },
```
并确认设置页（用 `EXPORT_TEMPLATE_META` 渲染的那个组件）自动多出这一行 —— 它是遍历出来的，
不需要单独加 UI；若发现是硬编码列表，就在同批补上并截图给 spec §14 记账。

- [ ] **Step 5: 写视图实现**

`apps/weight/views.py` 追加（并把 `FILENAME_MAX` 复用）：
```python
def _str_list(value, expected: int) -> list[str] | None:
    if not isinstance(value, list) or len(value) != expected:
        return None
    return [v if isinstance(v, str) else '' for v in value]


class WeightExportView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data
        # 入站守卫（body/text/filename）与解析错误透传是**两个端点共享**的 400 形状，
        # 已抽成 `_guard_core(data)` → `(错误或 None, text, filename)` 与
        # `_weight_error_response(exc)`（修复轮 R4：各自写一遍迟早漂移）
        err, text, filename = _guard_core(data)
        if err is not None:
            return err
        indexes = data.get('visible_group_indexes', None)
        if indexes is not None and not isinstance(indexes, list):
            return _bad_input(field='visible_group_indexes')
        palette = _str_list(data.get('palette'), 8)
        if palette is None:
            return _bad_input(field='palette')
        mean_color = data.get('mean_color', '')
        if not isinstance(mean_color, str):
            return _bad_input(field='mean_color')
        show_mean = data.get('show_mean', False)
        if not isinstance(show_mean, bool):
            # 修复轮 F2：`bool('false')` / `bool('0')` / `bool([x])` 都是 True ⇒ 用户没要均值
            # 却静默拿到一份画满均值（70 条系列）的错工作簿。与邻居同口径直接 400。
            return _bad_input(field='show_mean')
        try:
            doc = parse_weight_text(text, filename_hint=filename[:FILENAME_MAX])
        except WeightError as exc:
            return _weight_error_response(exc)
        stem = (filename.rsplit('.', 1)[0] if '.' in filename else filename)[:FILENAME_MAX]
        base = stem or filename[:FILENAME_MAX]   # 整串就是扩展名时 stem 为空
        # 表名与下载名**同源**于 base（修复轮 R3）：两处各兜各的会漂移
        content = build_weight_workbook(
            doc, sheet_base=base,
            visible_group_indexes=indexes, show_mean=show_mean,
            palette=palette, mean_color=mean_color)
        fname = render_export_filename(
            request.user, 'weight_plot', 'xlsx',
            {**base_export_context(request.user), 'filename': base})
        return FileResponse(io.BytesIO(content), as_attachment=True, filename=fname,
                            content_type=(
                                'application/vnd.openxmlformats-officedocument'
                                '.spreadsheetml.sheet'))
```
`apps/weight/urls.py` 加 `path('weight/export/', WeightExportView.as_view(), name='weight-export'),`。
文件顶部补 `import io`、`from django.http import FileResponse`、
`from apps.common.export_naming import base_export_context, render_export_filename`、
`from .xlsx import build_weight_workbook`。

- [ ] **Step 6: 跑到全绿 + 类型与构建**

```bash
python manage.py test test.backend.test_weight_export_api test.backend.test_weight_xlsx -v 1
cd frontend && npx vue-tsc -b && npm run build
```
Expected: 后端全 PASS；`vue-tsc -b` 无错（`Record<ExportTypeKey, …>` 若少一处实现会在这里报 TS2741）。

- [ ] **Step 7: Commit**

```bash
git add apps/weight/ apps/common/export_naming.py frontend/src/types/index.ts frontend/src/constants/export-templates.ts test/backend/test_weight_export_api.py
git commit -m "feat(weight): 权重 xlsx 导出端点，注册 weight_plot 文件名模板两处联动"
```

---

## Task 6: 前端纯模块 `weightChartOption.ts` + T2

**Files:**
- Create: `frontend/src/pages/weight/weightChartOption.ts`
- Test: `frontend/test/unit/weightChartOption.spec.ts`

**Interfaces:**
- Consumes: Task 3 的响应体字段（逐字段对应下面的 DTO）
- Produces（Task 8 的组件按这些名字用）:
  - `WeightSeriesDto { name, source_index, declared_length, decimals, values: (number|null)[] }`
  - `WeightGroupDto { index, name, first_row, series: WeightSeriesDto[], mean: WeightSeriesDto }`
  - `WeightDocDto { filename, code_max, group_count, series_count, groups: WeightGroupDto[] }`
  - `buildWeightOption(doc, o: BuildOptions): EChartsOption`
  - `DASH_BY_WITHIN_GROUP: (string | number[])[]`、`MEAN_DASH: 'solid'`
  - `groupColor(colors: string[], groupIndex: number): string`

**系列名不是唯一键（Task 2 评审实测确认，spec §3.2 的已接受行为）**：后缀是按名称出现次数生成的，
所以文件里同时存在 `A`×2 与字面 `A_1` 时会得到 `['A_1','A_2','A_1']`；`A_Avg` 这个字面名同理会与该组的均值线重名。
解析器**不去重也不报错**（加去重要新增错误码，而每个新码都必须同步进前端 `ERROR_CODE_MAP`，那是改 spec）。
⇒ **Vue 侧一律用 `(group.index, series 下标)` 或 `source_index` 做 key，绝不用 `series.name`**：
`v-for` 的 `:key`、选中集合、表格行、tooltip 定位都算。ECharts 的 `series.name` 只用于显示，
同名时图例/tooltip 会把两条当同一系列（本功能图例已关，影响限于 tooltip）。

- [ ] **Step 1: 写失败测试（T2 = node 环境、零 DOM，所以判据必须住纯模块）**

```ts
// frontend/test/unit/weightChartOption.spec.ts
import { describe, expect, it } from 'vitest'
import { buildWeightOption, groupColor, DASH_BY_WITHIN_GROUP } from '../../src/pages/weight/weightChartOption'
import type { WeightDocDto } from '../../src/pages/weight/weightChartOption'

const COLORS = ['#2563eb', '#047857', '#d97706', '#b91c1c', '#0284c7', '#86198f', '#475569', '#0d9488']

function series(name: string, n: number) {
  return { name, source_index: 1, declared_length: n, decimals: 5, values: Array.from({ length: n }, (_, i) => i * 0.5) }
}
function group(index: number, len: number): WeightDocDto['groups'][number] {
  const members = [1, 2, 3, 4].map((k) => series(`WT000${index + 1}_${k}`, len))
  return {
    index, name: `WT000${index + 1}`, first_row: 1, series: members,
    mean: series(`WT000${index + 1}_Avg`, len),
  }
}
const DOC: WeightDocDto = {
  filename: 'trim_weight_ci.csv', code_max: 63, group_count: 4, series_count: 16,
  groups: [group(0, 16), group(1, 8), group(2, 4), group(3, 64)],
}
const base = { textColor: '#6b7280', axisLineColor: '#e5e7eb', titleText: 'W', meanColor: '#4b5563' }

describe('buildWeightOption', () => {
  it('全开时 16 条系列，无标记', () => {
    const opt: any = buildWeightOption(DOC, { visible: new Set([0, 1, 2, 3]), showMean: false, colors: COLORS, ...base })
    expect(opt.series).toHaveLength(16)
    expect(opt.series.every((s: any) => s.symbol === 'none')).toBe(true)
    expect(opt.series.every((s: any) => s.showAllSymbol === false)).toBe(true)
  })

  it('关掉一组只剩 12 条，且掉的正是那一组', () => {
    const opt: any = buildWeightOption(DOC, { visible: new Set([1, 2, 3]), showMean: false, colors: COLORS, ...base })
    expect(opt.series).toHaveLength(12)
    expect(opt.series.filter((s: any) => s.name.startsWith('WT0001_'))).toHaveLength(0)
  })

  it('X 轴固定在 0..code_max，与可见集合无关（对照断言）', () => {
    const wide: any = buildWeightOption(DOC, { visible: new Set([0, 1, 2, 3]), showMean: false, colors: COLORS, ...base })
    const narrow: any = buildWeightOption(DOC, { visible: new Set([0]), showMean: false, colors: COLORS, ...base })
    expect(wide.xAxis[0].min).toBe(0); expect(wide.xAxis[0].max).toBe(63)
    expect(narrow.xAxis[0].max).toBe(63)   // 只看第 1 组（长度 16）也不收窄
  })

  it('每条系列只取自身长度，短数组不补空', () => {
    const opt: any = buildWeightOption(DOC, { visible: new Set([0, 1, 2, 3]), showMean: false, colors: COLORS, ...base })
    const g1 = opt.series.filter((s: any) => s.name.startsWith('WT0002_'))
    expect(g1[0].data).toHaveLength(8)
    expect(g1[0].data[0]).toEqual([0, 0])
    const g3 = opt.series.filter((s: any) => s.name.startsWith('WT0004_'))
    expect(g3[0].data).toHaveLength(64)
  })

  it('组内四条按线型区分、共用该组基色', () => {
    const opt: any = buildWeightOption(DOC, { visible: new Set([1]), showMean: false, colors: COLORS, ...base })
    const g = opt.series.filter((s: any) => s.name.startsWith('WT0002_'))
    expect(g.map((s: any) => s.lineStyle.type)).toEqual(DASH_BY_WITHIN_GROUP.slice(0, 4))
    expect(new Set(g.map((s: any) => s.lineStyle.color))).toEqual(new Set([COLORS[1]]))
  })

  it('开均值加 4 条、深灰加粗实线；关均值回到 16', () => {
    const on: any = buildWeightOption(DOC, { visible: new Set([0, 1, 2, 3]), showMean: true, colors: COLORS, ...base })
    expect(on.series).toHaveLength(20)
    const mean = on.series.find((s: any) => s.name === 'WT0001_Avg')
    expect(mean.lineStyle.color).toBe(base.meanColor)
    expect(mean.lineStyle.type).toBe('solid')
    expect(mean.lineStyle.width).toBeGreaterThan(1)
  })

  it('未勾选组的均值也不进图', () => {
    const opt: any = buildWeightOption(DOC, { visible: new Set([0]), showMean: true, colors: COLORS, ...base })
    expect(opt.series.filter((s: any) => s.name.endsWith('_Avg'))).toHaveLength(1)
  })

  it('14 组循环 8 色：第 9 组与第 1 组同色（这是能力上限，钉住别当 bug 改）', () => {
    expect(groupColor(COLORS, 0)).toBe(COLORS[0])
    expect(groupColor(COLORS, 8)).toBe(COLORS[0])
  })

  it('tooltip 显示到系列名，不只显示组名', () => {
    const opt: any = buildWeightOption(DOC, { visible: new Set([0]), showMean: false, colors: COLORS, ...base })
    expect(opt.tooltip.trigger).toBe('item')
    expect(typeof opt.tooltip.formatter).toBe('function')
  })
})
```

- [ ] **Step 2: 跑到失败**

```bash
cd frontend && npx vitest run test/unit/weightChartOption.spec.ts
```
Expected: 找不到模块（`Failed to resolve import`）。

- [ ] **Step 3: 写实现**

```ts
// frontend/src/pages/weight/weightChartOption.ts
/** 权重画图的 option 构建：纯函数、零 DOM，才能落 T2（testing-gates §2）。
 *  开关做法 = 按可见组重建 series（spec §5.2），不用 ECharts 原生 legend（那是逐系列的）。 */
import type { EChartsOption } from 'echarts'

export interface WeightSeriesDto {
  name: string
  source_index: number
  declared_length: number
  decimals: number
  values: (number | null)[]
}
export interface WeightGroupDto {
  index: number
  name: string
  first_row: number
  series: WeightSeriesDto[]
  mean: WeightSeriesDto
}
export interface WeightDocDto {
  filename: string
  code_max: number
  group_count: number
  series_count: number
  groups: WeightGroupDto[]
}
export interface BuildOptions {
  visible: Set<number>
  showMean: boolean
  colors: string[]
  meanColor: string
  textColor: string
  axisLineColor: string
  titleText: string
}

export const DASH_BY_WITHIN_GROUP: (string | number[])[] = ['solid', 'dashed', 'dotted', [6, 3, 1, 3]]
export const MEAN_DASH = 'solid'
export const MEAN_WIDTH = 2.5
export const LINE_WIDTH = 1.25

export function groupColor(colors: string[], groupIndex: number): string {
  return colors[groupIndex % colors.length]
}

function pairize(values: (number | null)[]): [number, number | null][] {
  return values.map((v, i) => [i, v] as [number, number | null])
}

export function buildWeightOption(doc: WeightDocDto, o: BuildOptions): EChartsOption {
  const series: any[] = []
  for (const g of doc.groups) {
    if (!o.visible.has(g.index)) continue
    g.series.forEach((s, within) => series.push({
      name: s.name, type: 'line', symbol: 'none', showAllSymbol: false,
      sampling: 'lttb', connectNulls: false,
      lineStyle: { type: DASH_BY_WITHIN_GROUP[within % 4], width: LINE_WIDTH, color: groupColor(o.colors, g.index) },
      itemStyle: { color: groupColor(o.colors, g.index) },
      data: pairize(s.values),
    }))
    if (o.showMean) {
      series.push({
        name: g.mean.name, type: 'line', symbol: 'none', showAllSymbol: false,
        lineStyle: { type: MEAN_DASH, width: MEAN_WIDTH, color: o.meanColor },
        itemStyle: { color: o.meanColor },
        data: pairize(g.mean.values),
      })
    }
  }
  return {
    backgroundColor: 'transparent',
    animation: false,
    title: { text: o.titleText, textStyle: { color: o.textColor, fontSize: 12 } },
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => `${p.seriesName}<br/>code ${p.value[0]} · ${p.value[1]}`,
    },
    grid: { left: 56, right: 16, top: 34, bottom: 30, containLabel: false },
    xAxis: {
      type: 'value', name: 'Code', min: 0, max: doc.code_max,
      axisLine: { lineStyle: { color: o.axisLineColor } },
      splitLine: { lineStyle: { color: o.axisLineColor } },
      axisLabel: { color: o.textColor, fontSize: 10 },
    },
    yAxis: {
      type: 'value', name: 'Weight', scale: true,
      axisLine: { lineStyle: { color: o.axisLineColor } },
      splitLine: { lineStyle: { color: o.axisLineColor } },
      axisLabel: { color: o.textColor, fontSize: 10 },
    },
    series,
  } as EChartsOption
}
```

上面那个 `if (o.showMean)` 是被两条断言逼出来的（「全开 16 条」与「开均值 20 条」）——
若把均值无条件推进去，第一条就会红在 `toHaveLength(16)`。同理 `X 轴与可见集合无关` 那条是**对照断言**：
只看第 1 组时轴仍到 63，防的是「顺手按可见数据收窄轴」这种看似合理的改动。

- [ ] **Step 4: 跑到全绿**

```bash
cd frontend && npx vitest run
```
Expected: 新增 9 例 PASS 且原有例不减。

- [ ] **Step 5: Commit**

```bash
cd frontend && npm run build && npm run lint:e2e
git add frontend/src/pages/weight/weightChartOption.ts frontend/test/unit/weightChartOption.spec.ts
git commit -m "feat(weight): 权重图 option 纯函数，按可见组重建系列"
```

---

## Task 7: 前端 API 模块 + 错误码文案

**Files:**
- Create: `frontend/src/api/weight.ts`
- Modify: `frontend/src/utils/error.ts:15`（`ERROR_CODE_MAP`）

**Interfaces:**
- Consumes: `frontend/src/api/index.ts` 的 axios 实例（拦截器已带 token 与 `formatError`）
- Produces: `weightApi.parse(body): Promise<AxiosResponse<WeightDocDto>>`、
  `weightApi.export(body): Promise<AxiosResponse<Blob>>`

- [ ] **Step 1: 写实现（照 `frontend/src/api/gage.ts` 的形状）**

```ts
// frontend/src/api/weight.ts
import api from './index'
import type { WeightDocDto } from '../pages/weight/weightChartOption'

export interface WeightParseRequest { filename: string; text: string }
export interface WeightExportRequest extends WeightParseRequest {
  visible_group_indexes: number[]
  show_mean: boolean
  palette: string[]
  mean_color: string
}

export const weightApi = {
  parse(body: WeightParseRequest) {
    return api.post<WeightDocDto>('/weight/parse/', body)
  },
  /** silent：解析失败比通用提示更具体（行号在 detail 里），由调用方组织文案。 */
  export(body: WeightExportRequest) {
    return api.post('/weight/export/', body, { responseType: 'blob', silent: true })
  },
}
```

- [ ] **Step 2: `ERROR_CODE_MAP` 补四条（spec §3.3 的码，一个都不能少）**

```ts
  no_declaration: '文件里没有找到 double 权重声明',
  weight_length_mismatch: '声明长度与实际数值个数不一致',
  weight_bad_number: '权重数值里有无法解析的项',
  weight_too_large: '权重文件超出可处理范围',
```
注意 `weight_length_mismatch` / `weight_bad_number` 的 detail 是**结构化对象**，
所以页面的错误条要把 `detail.line` 拼进句子（Task 8 的 `composables/useWeightPlot.ts` 负责）。

- [ ] **Step 3: 类型与构建**

```bash
cd frontend && npx vue-tsc -b && npm run build
```
Expected: 无错。`silent` 若不是 `api.post` 已知的配置键，会在这里报 TS2345 —— 那时按
`frontend/src/api/index.ts` 里声明该选项的位置补类型，而不是 `as any`。

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/weight.ts frontend/src/utils/error.ts
git commit -m "feat(weight): 权重解析与导出的前端 API 通路，补四条错误码文案"
```

---

## Task 8: 页面、组件、store 与入口（双主题）

**Files:**
- Create: `frontend/src/pages/weight/WeightPlotPage.vue`
- Create: `frontend/src/pages/weight/components/WeightChartPanel.vue`、`WeightGroupChips.vue`、`WeightSeriesTable.vue`
- Create: `frontend/src/pages/weight/composables/useWeightPlot.ts`、`composables/weightErrorText.ts`
- Create: `frontend/src/stores/weight.ts`
- Modify: `frontend/src/router/index.ts`（icon import + children）、`frontend/src/components/layout/Sidebar.vue:73-82,95-104`

**Interfaces:**
- Consumes: Task 6 的 `buildWeightOption`/DTO、Task 7 的 `weightApi`、既有
  `useEChartsTheme()`（`utils/echarts-theme.ts:77`）、`useChart`（`composables/useChart.ts:28`）、
  `downloadBlob`/`extractFilenameFromContentDisposition`（`utils/download.ts`）
- Produces: 路由名 `WeightPlot`、path `/weight`、侧栏文案「权重画图」

- [ ] **Step 1: store（setup 式，与 `stores/analysis.ts` 同风格）**

```ts
// frontend/src/stores/weight.ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { WeightDocDto } from '../pages/weight/weightChartOption'

/** 只活在本会话：刷新即丢（spec §11，不落 localStorage）。 */
export const useWeightStore = defineStore('weight', () => {
  const doc = ref<WeightDocDto | null>(null)
  const rawText = ref('')            // 导出要把原文再交回同一个解析器（spec §2 第 4 条）
  const filename = ref('')
  const visible = ref<number[]>([])
  const showMean = ref(false)
  const errorText = ref('')
  const busy = ref(false)

  const allVisible = computed(() => doc.value !== null && visible.value.length === doc.value.group_count)

  function reset() {
    doc.value = null; rawText.value = ''; filename.value = ''
    visible.value = []; showMean.value = false
    errorText.value = ''; busy.value = false
  }
  function setDoc(next: WeightDocDto, text: string) {
    doc.value = next
    rawText.value = text
    filename.value = next.filename
    visible.value = next.groups.map((g) => g.index)   // 换文件全量复位
    showMean.value = false
    errorText.value = ''
  }
  function toggleGroup(index: number, on: boolean) {
    const set = new Set(visible.value)
    on ? set.add(index) : set.delete(index)
    visible.value = [...set].sort((a, b) => a - b)
  }
  return { doc, rawText, filename, visible, showMean, errorText, busy, allVisible, reset, setDoc, toggleGroup }
})
```

- [ ] **Step 2: composable（解析失败保留现图 —— spec §3.2 / §11）**

```ts
// frontend/src/pages/weight/composables/useWeightPlot.ts
import { useEChartsTheme } from '../../../utils/echarts-theme'
import { downloadBlob, extractFilenameFromContentDisposition } from '../../../utils/download'
import { weightApi } from '../../../api/weight'
import { useWeightStore } from '../../../stores/weight'
import { TEXT_CHAR_LIMIT, describeExportError, describeWeightError } from './weightErrorText'

export function useWeightPlot() {
  const store = useWeightStore()
  const { colors } = useEChartsTheme()

  async function loadFile(file: File) {
    store.busy = true
    store.errorText = ''
    try {
      const text = await file.text()
      if (text.length > TEXT_CHAR_LIMIT) {
        // 前端先挡一次是为了「点了立刻有话」，后端那道同值守卫仍然要过（R3②：不许假设前端已过滤）
        store.errorText = `文件超出可处理范围（上限 ${TEXT_CHAR_LIMIT.toLocaleString()} 字符）`
        return
      }
      const r = await weightApi.parse({ filename: file.name, text })
      store.setDoc(r.data, text)
    } catch (e: any) {
      // 关键：不碰 doc/rawText/visible —— 解析失败要保留现图（spec §3.2 / §11）
      store.errorText = describeWeightError(e)
    } finally {
      store.busy = false
    }
  }

  async function exportXlsx() {
    if (!store.doc) return
    store.busy = true
    try {
      const r = await weightApi.export({
        filename: store.filename, text: store.rawText,
        visible_group_indexes: store.visible, show_mean: store.showMean,
        palette: colors.value.seriesColors,
        mean_color: colors.value.textColor,
      })
      downloadBlob(r.data as Blob, extractFilenameFromContentDisposition(r.headers) ?? 'weight-plot.xlsx')
    } catch (e: any) {
      store.errorText = await describeExportError(e)   // 导出 lane 的错误体是 Blob
    } finally {
      store.busy = false
    }
  }

  return { store, loadFile, exportXlsx, toggleMean: () => { store.showMean = !store.showMean } }
}
```

`colors.value.seriesColors` 是 hex 数组（`utils/echarts-theme.ts:127` night / `:162` light），
导出侧的 `_hex()` 会剥掉 `#`，所以页面所见与 xlsx 里那条线的颜色是同一个值 —— 这是 spec §6.1
「色板只在前端一份真源」的落点，别在 Python 里再抄一份八色。

`weightErrorText.ts`（把后端结构化 detail 组织成一句人话，住纯模块以便 T2）：
```ts
import type { AxiosError } from 'axios'
export const TEXT_CHAR_LIMIT = 2_000_000

export function describeWeightError(e: unknown): string {
  const err = e as AxiosError<{ code?: string; detail?: any }>
  const d = err?.response?.data
  if (d?.code === 'weight_length_mismatch' && d.detail)
    return `第 ${d.detail.line} 行 ${d.detail.name}：声明长度 ${d.detail.declared}，实际数值 ${d.detail.actual}`
  if (d?.code === 'weight_bad_number' && d.detail)
    return `第 ${d.detail.line} 行有无法解析的数值「${d.detail.token}」`
  if (d?.code === 'weight_too_large')
    return `文件超出可处理范围（${d.detail?.which ?? ''} 上限 ${d.detail?.limit ?? ''}）`
  return (err?.message ?? '权重文件处理失败')
}
```

导出那条 lane 的错误体是 **Blob 不是 JSON**（`responseType: 'blob'` + `silent`，同 `api/gage.ts:14` 的口径），
所以 `describeWeightError` 前面要先解一次：
```ts
export async function describeExportError(e: unknown): Promise<string> {
  const err = e as { response?: { data?: unknown } }
  if (err?.response?.data instanceof Blob) {
    try {
      return describeWeightError({ response: { data: JSON.parse(await err.response.data.text()) } })
    } catch {
      return '导出失败，请稍后重试'        // 解不出 JSON 就是真·网络/服务异常
    }
  }
  return describeWeightError(e)
}
```

`weightErrorText.ts` 是纯模块 ⇒ 落 T2（`frontend/test/unit/weightErrorText.spec.ts`）：
```ts
import { describe, expect, it } from 'vitest'
import { TEXT_CHAR_LIMIT, describeWeightError } from '../../src/pages/weight/composables/weightErrorText'

const withData = (data: unknown) => ({ response: { data } }) as never

describe('describeWeightError', () => {
  it('把后端结构化 detail 组织成带行号的一句话', () => {
    expect(describeWeightError(withData({
      code: 'weight_length_mismatch',
      detail: { line: 2, name: 'WT0002', declared: 2, actual: 1 },
    }))).toBe('第 2 行 WT0002：声明长度 2，实际数值 1')
  })

  it('坏数值给行号与原串', () => {
    expect(describeWeightError(withData({
      code: 'weight_bad_number', detail: { line: 7, token: '1.0.0' },
    }))).toContain('第 7 行').toContain('1.0.0')
  })

  it('裸机器码不静默：没有 detail 时也要出话', () => {
    expect(describeWeightError(withData({ code: 'no_declaration' }))).toContain('double')
  })

  it('未知错误回落到 message，而不是 undefined', () => {
    expect(describeWeightError(new Error('boom'))).toBe('boom')
  })

  it('上限常量与后端一致（2_000_000）', () => {
    expect(TEXT_CHAR_LIMIT).toBe(2_000_000)
  })
})
```
`no_declaration` 那句要在 `describeWeightError` 里补一条分支（后端 detail 为 None，句子只能在前端组）：
```ts
  if (d?.code === 'no_declaration') return '文件里没有找到 double 权重声明'
```

- [ ] **Step 3: 三个组件 + 页面**

`WeightChartPanel.vue`（**必须走 `useChart`，禁止裸 `echarts.init`**）：
```vue
<script setup lang="ts">
import { useTemplateRef } from 'vue'
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import { buildWeightOption, type WeightDocDto } from '../weightChartOption'

const props = defineProps<{ doc: WeightDocDto; visible: number[]; showMean: boolean }>()
const chartRef = useTemplateRef<HTMLDivElement>('chartRef')
// useEChartsTheme() 只返回 { isDark, colors, getBaseOption }（echarts-theme.ts:274-278）——
// 没有 currentTheme 这个键，别照其它 store 的名字猜。取色一律走 colors.value.*（lessons R7②）。
const { colors, isDark } = useEChartsTheme()

const buildOption = () => buildWeightOption(props.doc, {
  visible: new Set(props.visible),
  showMean: props.showMean,
  colors: colors.value.seriesColors,
  meanColor: colors.value.textColor,
  textColor: colors.value.textColor,
  axisLineColor: colors.value.axisLineColor,
  titleText: props.doc.filename,
})

useChart(buildOption, [() => props.visible.join(','), () => props.showMean, isDark], 'chartRef')
</script>

<template>
  <div ref="chartRef" class="weight-chart" data-testid="weight-chart" />
</template>

<style scoped>
.weight-chart { width: 100%; height: 100%; min-height: 360px; }
</style>
```
`useChart` 的入参顺序与 `sources` 语义照 `pages/analysis/components/SerialChart.vue:39,306` 的调用抄
（`const { colors, isDark } = useEChartsTheme()`），主题切换要靠 `isDark` 触发重画。

`WeightGroupChips.vue`：`el-checkbox-group` + `v-model`，每项一个 `el-checkbox class="weight-chip"`、
`:label="g.index"`、文本 `g.name`，左边 8px 实色条取 `groupColor(colors, g.index)`
（用实色边框承载而不是靠色块深浅 —— 项目 memory「token 对比度实测口径」那条：tint 到不了 3:1）；
底部一行小字提示「组内四条按线型区分（实/虚/点/点划）」—— spec §6.2 要求的可见提示，必须真的存在。

`WeightSeriesTable.vue`：`el-table`，外层容器 `data-testid="weight-rows"`，列 = 原序号 / 系列名 / code 0..code_max；
`series` 计算属性按 `visible` 与 `showMean` 过滤出要显示的行（**未勾选组的行仍然保留在表里**，
与 xlsx 行为一致：spec 源稿 §6「表格行保留，图中不出现」）；
code 列 `min-width: 62px`、右对齐、横向滚动；表头随主题走 token，不写页面级 night 覆盖。
`el-table` 的 `row-key` **必须用 `组序号:系列下标` 拼出来的键**（例如 `` `${g.index}:${i}` ``），
不能用系列名 —— 解析器不去重同名系列（Task 2 评审实测：`A`×2 与字面 `A_1` 会得到两条 `A_1`），
用名字当键会让 Vue 的行复用与 `el-table` 的选中态互相打架。

`WeightPlotPage.vue`：
**字号一律走九档 token**（`--p-fs-micro/dense/small/base/...`，`design-tokens.css:43-45`；`global/fonts.spec.ts` 会扫 scoped 样式里的裸 `font-size: <N>px` 并判红 —— 实测本页初版 5 处裸 px 被池抓到）。
- 顶部条：`<input type="file" accept=".csv,.txt,.h,.c" class="sr-only">`（`.sr-only` 真实存在于
  `frontend/src/styles/utilities.css:211`；不能用 `display:none`，否则 Playwright 的 `setInputFiles` 摸不到）
  + 一个 `label for=` 的「选择权重文件」按钮 + 当前文件名；
- 错误条 `data-testid="weight-error"`，只在 `store.errorText` 非空时渲染；
- 空态 `data-testid="weight-empty-hint"`（还没选文件时显示，T3 的第一条断言就靠它）；
- 「均值 / 隐藏均值」按钮：`{{ store.showMean ? '隐藏均值' : '均值' }}`，文案随状态翻；
- 「导出 Excel」按钮：`store.doc` 为空时 `disabled`；
- 主体 `display: flex`：左 `flex: 1 1 55%` 图容器、右 `flex: 1 1 45%` 上 chips 下表格。

- [ ] **Step 4: 路由与侧栏**

`frontend/src/router/index.ts`：import 里加 `DataAnalysis`（或 `Histogram`/`PieChart`，
最终选一个未在该文件用过的图标以免两个菜单项同形），children 里 `sftp/search` 那条之后、
`batch` redirect 之前插：
```ts
      {
        path: 'weight',
        name: 'WeightPlot',
        component: () => import('../pages/weight/WeightPlotPage.vue'),
        meta: { title: '权重画图', icon: DataAnalysis, desc: '本地权重 CSV 的逐点曲线与同名均值' },
      },
```
**不加 `parent`**（`meta.parent` 只影响 Topbar 副行，且会连带「SFTP 浏览器 ›」这种误导性归属）。

`Sidebar.vue`：第 100 行 `/sftp` 与第 102 行 `/admin/users` 之间插入
`{ path: '/weight', label: '权重画图', icon: DataAnalysis, requiresAdmin: false },`，
并在 73-82 行的 import 里补同名图标。**不要写 `groupStart`。**

- [ ] **Step 5: 手测两主题 + 真实样例**

```bash
cd frontend && npm run dev
```
浏览器（或 Electron）进 `#/weight`，选**本机那份私有样例**（路径不入仓，与 Task 1 的 `--src` 同一份）：
14 chip / 56 行、关第 1 个 chip 图掉 4 条、开均值加 14 条、导出得到 `Weight_Plot_…_.xlsx`；
切 night 主题再看一遍（线条与文字都要可辨，色只来自 `useEChartsTheme`）。
把首绘耗时记一行（spec §14 第 3 条要的实测值）。

布局必须先量再锁（spec §14 第 4 条；本仓口径是「省高先量差值再拍」）。一次性探针，跑完即删：

```ts
// frontend/e2e/weight/layout-probe.spec.ts（@p2，不进常规门禁；量完删除文件）
import path from 'node:path'
import { expect, test } from '@playwright/test'
import { gotoApp } from '../helpers/nav'

for (const width of [1280, 1440]) {
  test(`@p2 权重页几何实测 @${width}`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await gotoApp(page, '/weight')
    await page.locator('input[type="file"]').first()
      .setInputFiles(path.join(__dirname, '..', '..', '..', 'test', 'fixtures', 'weight', 'trim_weight_ci.csv'))
    await expect(page.locator('.weight-chip')).toHaveCount(14)
    const chips = page.locator('.weight-chip')
    await expect(chips).toHaveCount(14)                 // 先验存在：空 locator 的 boundingBox 会等满超时后抛（R2⑤）
    const box = async (sel: string) => {
      const b = await page.locator(sel).first().boundingBox()
      if (!b) throw new Error(`没有盒子：${sel}`)
      return { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) }
    }
    const g = {
      chart: await box('[data-testid="weight-chart"]'),
      chipFirst: await box('.weight-chip >> nth=0'),
      chipLast: await box('.weight-chip >> nth=13'),
      table: await box('[data-testid="weight-rows"]'),
      docScrollH: await page.evaluate(() => document.documentElement.scrollHeight),
    }
    console.log(`WEIGHT-LAYOUT ${width} ` + JSON.stringify(g))
    expect(g.chart.w).toBeGreaterThan(400)
    expect(g.chipLast.y).toBeLessThan(g.table.y)        // chip 组没压表格
  })
}
```
Expected：两行 `WEIGHT-LAYOUT 1280/1440 {...}` 打进日志。把这八个数字抄进 `docs/tasks/todo.md`
的本功能条目，**图区宽度 < 400px 或 chip 组折成两行以上就回来改布局参数**，不要顺手把断言放宽。
⚠ 量完**必须删掉这个文件**再进 Task 9：它带 `@p2`，留着就会被 P2 项目收进全量池，
变成一条只打印数字的用例混进 396 例的账里。

- [ ] **Step 6: 构建与提交**

```bash
cd frontend && npm run build && npm run lint:e2e && npx vitest run
npm run test:e2e:affected
git add frontend/src/pages/weight frontend/src/stores/weight.ts frontend/src/router/index.ts frontend/src/components/layout/Sidebar.vue
git commit -m "feat(weight): 权重画图页面，整组开关与均值走重建系列"
```

---

## Task 9: e2e 一条接线证明 + 冒烟路由

**Files:**
- Create: `frontend/e2e/weight/weight-plot.spec.ts`
- Modify: `frontend/e2e/fixtures/test-data.ts:112-118`（`ROUTES`）、`frontend/e2e/theme/night-visibility.spec.ts:168-172`

**Interfaces:**
- Consumes: `frontend/e2e/helpers/upload.ts` 的 `uploadFile()`、`gotoApp`、`sidebarLink`、
  夹具 `test/fixtures/weight/trim_weight_ci.csv`
- Produces: 一条 `@p1` 用例 + 冒烟覆盖

- [ ] **Step 1: 写用例（下载等待不许 `.catch(() => null)`）**

```ts
// frontend/e2e/weight/weight-plot.spec.ts
/**
 * 权重画图接线证明：选文件 → 出图 → 关一组掉系列 → 开均值 → 导出触发下载。
 * 数值/分组契约在 T1（test/backend/test_weight_*.py）已经全组合钉住，这里只验通路。
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import { gotoApp } from '../helpers/nav'

// ⚠ e2e 是 ESM（package.json type=module）：本作用域没有 `__dirname`。直接用它会在**注册用例前**
// 把整个文件崩掉，Playwright 报 `No tests found` 且**退出码 0** —— 实测踩过一次。
// 本仓 idiom（e2e/helpers/slot.ts:7-9 同形）：
const __dirname = path.dirname(fileURLToPath(import.meta.url))

const FIXTURE = path.join(__dirname, '..', '..', '..', 'test', 'fixtures', 'weight', 'trim_weight_ci.csv')
const BAD = path.join(__dirname, 'fixtures', 'bad-length.csv')

test.describe('@p1 权重画图', { tag: ['@p1'] }, () => {
  test.beforeEach(async ({ page }) => {
    // 「不应有控制台错误」的监听必须装在 goto 之前（lessons R2④）
    page.on('console', (m) => {
      if (m.type() === 'error') throw new Error(`console error: ${m.text()}`)
    })
  })

  test('14 组渲染、整组开关不删表行、均值展开到 70 行、xlsx 能下载', async ({ page }) => {
    await gotoApp(page, '/weight')
    await expect(page.getByTestId('weight-empty-hint')).toBeVisible()   // 空态真实存在

    await page.locator('input[type="file"]').first().setInputFiles(FIXTURE)
    await expect(page.getByTestId('weight-chart')).toBeVisible()
    // 真实渲染证据：容器里有 canvas **或** svg 且尺寸非零 —— canvas 档下没有 svg，只找 svg 会假绿（R2⑤）
    const painted = page.locator('[data-testid="weight-chart"] canvas, [data-testid="weight-chart"] svg').first()
    await expect(painted).toBeVisible()
    await expect(page.locator('.weight-chip')).toHaveCount(14)
    await expect(page.getByText('WT0001_1', { exact: true })).toBeVisible()
    const rows = page.locator('[data-testid="weight-rows"] .el-table__row')
    await expect(rows).toHaveCount(56)

    await page.locator('.weight-chip').first().click()
    // 源稿 §6 规则：未勾选组的**表格行保留**，只是不进图 —— 所以行数仍 56
    await expect(rows).toHaveCount(56)
    // 选中态按本仓既有写法断 class（e2e/analysis/kde-curve.spec.ts:54,64,71 同形）；
    // Element Plus 的 aria-checked 不在 .weight-chip 这个 label 根节点上，别照记忆写。
    await expect(page.locator('.weight-chip').first()).not.toHaveClass(/is-checked/)
    await expect(painted).toBeVisible()

    await page.locator('.weight-chip').first().click()
    await expect(page.locator('.weight-chip').first()).toHaveClass(/is-checked/)

    await page.getByRole('button', { name: '均值' }).click()
    await expect(rows).toHaveCount(70)                     // 56 → 70：加的正是 14 条均值行
    await expect(page.getByText('WT0001_Avg', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: '隐藏均值' }).click()
    await expect(rows).toHaveCount(56)                     // 文案随状态翻转，且真能收回

    // waitForEvent 必须注册在触发之前（R2①）；这里**不** .catch(() => null)：
    // 下载没发生就是红，而不是「跳过断言」——对照 e2e/exports/exports.spec.ts:170 那种被吞掉的等待
    const dl = page.waitForEvent('download', { timeout: 30_000 })
    await page.getByRole('button', { name: '导出 Excel' }).click()
    # 注意素材名：e2e 注入的是夹具 `trim_weight_ci.csv`，不是那份私有样例，
    # 精确的模板渲染由 T1（test_weight_export_api）断，这里只断前缀 + 素材名 + 日期段 + 扩展名。
    expect((await dl).suggestedFilename()).toMatch(/^Weight_Plot_trim_weight_ci_\d{8}\.xlsx$/)
  })

  test('解析失败保留现图，并把行号显示出来', async ({ page }) => {
    await gotoApp(page, '/weight')
    await page.locator('input[type="file"]').first().setInputFiles(FIXTURE)
    await expect(page.locator('.weight-chip')).toHaveCount(14)
    await page.locator('input[type="file"]').first().setInputFiles(BAD)
    await expect(page.getByTestId('weight-error')).toContainText('第 2 行')
    await expect(page.locator('.weight-chip')).toHaveCount(14)           // 现图与状态没被清掉
  })
})
```
页面侧必须落实的 DOM 契约（Task 8 的组件按此命名，两边不一致就是红，不是「测试写得松」）：
`data-testid="weight-empty-hint" / weight-chart / weight-error / weight-rows`；chip 根节点
`class="weight-chip"` 且用 `el-checkbox`（选中态体现在根节点的 `is-checked` class 上）；均值按钮文案随状态在
「均值 / 隐藏均值」之间翻（源稿 §6 同口径）。系列数、轴范围、线型一律不在这里断 —— 那是 T2 的活。

`frontend/e2e/weight/fixtures/bad-length.csv` 内容（自建、自清、不依赖外部）：
```
double A[3] = {1.0, 2.0, 3.0};
double B[2] = {1.0};
```

- [ ] **Step 2: 定向跑（必带 project）**

```bash
cd frontend && npx playwright test e2e/weight/weight-plot.spec.ts --project=P1
```
Expected: 2 例 PASS。若报「no tests found」= 标签或项目名不对，先查 `grep: /@p1/`（`playwright.config.ts:138`），
**不要**为了跑通而摘标签。

- [ ] **Step 3: 冒烟路由表加一项 + 夜视性**

`test-data.ts` 的 `ROUTES` 里 `{ path: '/sftp', … },` 之后加：
```ts
  { path: '/weight', title: '权重画图', menu: '权重画图' },
```
`global.spec.ts:29-35` 的顺序断言只查前 4 项，新项在最后 ⇒ 不用改它（改了反而把它变成脆弱断言）。
`night-visibility.spec.ts` 的页面清单里加 `/weight`。

- [ ] **Step 4: 受影响门禁 + 静态体检**

```bash
cd frontend && npm run lint:e2e && npm run test:e2e:affected
```
Expected: affected 命中 `@p1 权重画图` 与 smoke/global（`pages.spec.ts` 依赖 ROUTES）。
若打印 `NO AFFECTED TESTS`，说明 `scripts/affected-rules.mjs` 没有 `pages/weight/**` 的规则 ——
**先把它当缺口报告，别顺手放宽判据**（testing-gates §3 的兜底方向不许改）。

- [ ] **Step 5: Commit**

```bash
git add frontend/e2e/weight frontend/e2e/fixtures/test-data.ts frontend/e2e/theme/night-visibility.spec.ts
git commit -m "test(weight): e2e 接线用例与冒烟路由覆盖"
```

---

## Task 10: 打包前置件 + 文档 + 收口验证

**Files:**
- Modify: `lq_dataprase.spec:74-92`（`_hiddenimports`）
- Modify: `docs/user-guide/**`（本机 gitignore，不入库）

**Interfaces:**
- Consumes: 前 9 个任务的全部产物
- Produces: 打包版能起、两个端点能被点到

- [ ] **Step 1: 补 hiddenimports（漏了就是打包版起来 500，本地完全看不出来）**

`lq_dataprase.spec` 里，紧跟现有 `'apps.jobs',` 那组之后加：
```python
    'apps.weight',
    'apps.weight.apps',
    'apps.weight.urls',
    'apps.weight.views',
    'apps.weight.parser',
    'apps.weight.xlsx',
```

- [ ] **Step 2: 用户指南一页（含必须存在的可见提示）**

写 `docs/user-guide/` 里权重画图一节：入口位置、支持的文件形态（C 声明文本，扩展名 .csv/.txt/.h/.c）、
「组内四条按线型区分（实/虚/点/点划）」的提示、导出文件里**没有整组开关**这件事、
以及「刷新即丢，本功能不写入数据库」。文案里指向的页面/按钮必须是前端真实存在的（lessons 那条硬规矩）。

- [ ] **Step 3: 收口全量（先清孤儿，再跑）**

```bash
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'runserver 2[12]\d{3}' } | Select-Object ProcessId, CommandLine
node scripts/e2e_pool.mjs --slots=4
```
Expected: 池判 `verdict` 非 `VOID (infra)`；墙钟与用例数一起看（289≠396 说明有 slot 中途死，
那种轮的红绿都不作数，**重跑才是结论**）。跑完回查端口与 `runserver` 孤儿并清掉。
⚠ 池在跑的时候**不要并跑任何别的测试、不要改产品代码**（lessons 2026-10-18 两条崩池成因）。

- [ ] **Step 4: 后端全套 + 前端三件套**

```bash
python manage.py test
cd frontend && npx vitest run && npm run lint:e2e && npm run build
```

- [ ] **Step 5: 打包验证（需要用户点头再做）**

打包脚本会 `taskkill` 别的会话进程（memory「共享工作区的毁人操作」），
所以这一步**必须先问用户能不能跑**，跑完再验：`dist` 版起来 → 登录 → `#/weight` 选真实样例 →
导出一次 → 真实 Excel 打开，图里系列数与页面可见集合一致。

- [ ] **Step 6: 历史自检（本仓有先例事故）**

```bash
git log --oneline origin/master..HEAD
git diff --stat origin/master..HEAD | tail -3
git log --diff-filter=A --name-only origin/master..HEAD | grep -E '^Data/|Trim_Weight|\.xls' || echo "no-sensitive-additions"
```
Expected: `no-sensitive-additions`，且 `origin/master..HEAD` 里每条提交都是自己的。
（push 不在本计划范围内，要点名才推。）

---

## 完成判据（对照 spec §15）

- `python manage.py test test.backend.test_weight_parser test.backend.test_weight_api test.backend.test_weight_xlsx test.backend.test_weight_export_api` 全绿；
- `cd frontend && npx vitest run` 全绿、`npm run build` 与 `npm run lint:e2e` 无错；
- `node scripts/e2e_pool.mjs --slots=4` 非 VOID 且绿；
- `tasks/probe_openpyxl_chart3.py` 的三个结论已写进 `apps/weight/xlsx.py` 的注释（marker 断 XML、`yVal` 而非 `val`、`NumericAxis`）；
- **色板没有新增**：组间基色仍取 `echarts-theme.ts` 那两份 8 色（spec §6.1/§6.2）。
  若实施中途想改成 14 个独立基色，必须先 `node tasks/cvd_verify.mjs` 加一组候选跑出 protan+deutan
  成环相邻 ΔE≥15 的实测输出并贴进台账，验不过就停在现方案 —— 不许「注明口径」了事（spec §6.4、§15）。
- 打包版起过一次并两端点各调一次（或用户明确免掉这一步并记在 spec §14）；
- `git log --diff-filter=A --name-only origin/master..HEAD | grep -E '^Data/|Trim_Weight'` 为空。
