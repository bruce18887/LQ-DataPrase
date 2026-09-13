# 后端结构重复合并（P1+P2）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 合并后端跨文件/跨模块的结构重复（解析器三胞胎、SFTP 守卫、Excel 样式、视图小重复），并按决策 D1–D4 收敛口径分歧。

**Architecture:** 每处合并先把"副本间的真实差异"列成参数或显式契约，禁止"取其一为准"。每个 Task 一个 commit、独立可 revert；除 B2/B7 外均以现有测试 + 全量回归为门禁，B1 额外加真实样本解析对拍，B3 加导出样式前后对拍。

**Tech Stack:** Django + DRF、pandas/numpy、excelize、`manage.py test`、Playwright e2e。

**前置：** Plan A（`2026-09-12-backend-dedup-p0-dead-code.md`）已合入。
**Spec：** `docs/superpowers/specs/2026-09-12-backend-dedup-cleanup-design.md` §4 §5

---

## ⚠️ 计划阶段对 spec 的三处修正（已核实，执行前请读）

写本计划时逐条复核了 spec 的假设，发现三处与实际代码不符。**已按实际情况调整任务**，不是照抄 spec：

| # | spec 原假设 | 实测事实 | 调整 |
|---|---|---|---|
| **F1** | P1-2「SFTP 落盘/注册/清理链 5 份可一起抽走」省 ~55 行 | 落盘链的异常清理依赖调用方在 `try` 之前持有的 `file_path`（`views.py:272-295`：`file_path = None` → try 内赋值 → except 内 `remove_partial(file_path)`）。若把 `upload_dir`/`resolve_local_path`/`get`/`register` 移进 helper，异常时调用方拿不到已落地的半截路径 → **失败会留下孤儿残片**，正是 `local_paths.py` 文档头声明要防的事故 | B2 缩到只抽**守卫**（无副作用、可等价抽取），收益 ~25 行；落盘链保持内联并在 Task 内注明原因 |
| **F2** | P2-1「文件加载 7 处内联复制可收敛」省 ~50 行 | 其中 5 处是 `for fid in file_ids:` 里的 `get_object_or_404` + `get_cached_parsed_file` + `if df is None: continue`（`gage/views.py:30-34`、`buyoff/views.py:30-34`、`:69-73`、`batch_report/views.py:341-344`）。现有 `common/file_loading.py:16` 是**抛出式**，改成 try/except 后仍需一行 `if df is None: continue`，**行数不降**；且 `browse_views.py:203-220` 用 `'File not found on disk'`+404、`dashboard/views.py:246-252` 用 200 状态返回错误码——**与 common 的错误码集合不同**，按决策 D1 不得改。**进一步核实**：连唯一逐字等价的 `dashboard/views.py` 也不值得转——它的 `datafile` 在上游已由「`file_id` 缺失时 `.first()` 回退」的分支解析好（`views.py:236-243`），再调 `load_user_file(request, datafile.pk)` 会重复一次 `get_object_or_404` 查询：**省 2 行换 1 次额外查询，净收益为负** | **P2-1 整体撤销代码收敛**，降级为文档级修正（B7）：只修 `common/file_loading.py` 的失真 docstring（声称 8 个消费者，实际 1 个）+ 在被评估后保留的站点加"已评估、不统一"的说明注释，并删 `gage/views.py` 两个死 import。收益 ~10 行，风险从"高"降为"无" |
| **F3** | P1-6「`export_ppt.py:91-97` 是 sigma 循环第三份副本」 | 它读的是服务端预计算的 `stats['s3'/'s4'/'s6']` **裁剪带**（filtered bands），不是 `mean ± σ*std` 的本地重算——与 `charts.py:122-129/174-181` 语义不同 | B4 的 sigma 项**不动 export_ppt**，只合并 charts.py 内部两处真副本 |

另外两条澄清（不影响执行，但影响验收数字）：
- **P1-8 的数值列候选**：`analysis/views/_helpers.py:130-142` 是"遍历 params 并处理重名列/全 NaN"的另一形状，**不并入**共享谓词（强行合并会把它的去重逻辑拍平）。共享的是最易写错的那条规则：`is_numeric_dtype and not is_bool_dtype`（`Dut_Pass` 陷阱，R4①）。
- **P1-5 的文件名碰撞**：`file_views.py:312-317`/`:413-418` 用 `_{ts}_{df.pk}` 后缀（同请求内多文件移动需按 pk 保唯一），与 `local_paths.resolve_local_path` 的 `_{ts}[_{seq}]` 是**不同策略**，不能合一。只有 `file_views.py:567-571`（上传单文件）语义与后者一致，可复用。

---

## 铁律

1. 每个 Task 开工前 `git status --short` 确认工作树干净（Plan A 的 3 个 commit 之后）。
2. 只 `git add` 本 Task 列出的路径。
3. **守卫/状态码类改动（B2）必须跑 e2e**，不能只靠单测——400/500 的差异正是 lessons R3① 的雷区。
4. 任一步的 Expected 不成立 → **停下报告**，不要"顺手改到通过"。

---

## Task B1: 解析器家族参数化 + Bin 列单源（最大结构收益）

**Files:**
- Create: （无新文件，模板类落在既有 `apps/datafiles/parsers/base.py`）
- Modify: `apps/datafiles/parsers/base.py`（加 `assign_columns` + `OffsetHeaderParser` + `get_bin_column_name` 读映射）
- Modify: `apps/datafiles/parsers/cta8290d.py`（95 → ~20 行）
- Modify: `apps/datafiles/parsers/cta8280f.py`（95 → ~20 行）
- Modify: `apps/datafiles/parsers/sts8200.py`（103 → ~35 行）
- Modify: `apps/datafiles/parsers/ets88.py`（170 → ~155 行，仅复用 `assign_columns` 与 bin 列）
- Modify: `apps/common/constants.py`（新增 `BIN_COLUMN_MAPPING` / `DEFAULT_BIN_COLUMN`）
- Modify: `apps/analysis/services/statistics/helpers.py:14-23`（改为读 common 的映射）
- Test: `test/backend/test_parsers_sample_golden.py`（新建，样本对拍）

**实测重复**（行级脚本，规整化后逐行比对）：`cta8280f.py:12-61` ≡ `cta8290d.py:12-61` ≡ `sts8200.py:12-61`（**40 行三方逐字节相同**）；`cta8280f.py:82-95` ≡ `cta8290d.py:82-95`；`ets88.py:113-130` 共享其中 15 行列名赋值块；`cta8280f` 与 `cta8290d` 整文件 diff 仅 22 行 / 5 处。

**必须保留的真实差异**（4 条，全部参数化）：
1. `format_type`（类名与格式串）
2. program name 关键字与分隔符：`'TestFileName'`/`'TestFile'` + `split(',', 1)` vs STS8200 的 `'Program:'` + `split(':', 1)`
3. `header_labels` 映射表（3 个 CTA 变体的 `station`/`device_name`/`tester_type`/`handler` 标签不同；STS8200 又是另一套且无 `device_name` 键）
4. STS8200 独有后处理：`station` 取首行、`device_name` 从 Program 名剥 `.pgs`/`.DLL` 与 `JAV` 前缀

- [ ] **Step 1: 先建立"行为不变"的硬门禁——样本对拍测试**

Create `test/backend/test_parsers_sample_golden.py`：

```python
"""四格式真实样本解析指纹测试（重构前后必须逐位不变）。

解析器是所有分析/导出的入口，参数化改动一旦影响 metadata 或列名，
下游会以"统计值悄悄变了"的形式暴露，单测难以覆盖。故这里对 Data/ 下
真实样本取指纹（列名/dtype/前 20 行/metadata 全字段）并与基线 JSON 比对。

基线生成：tasks/make_parse_golden.py（一次性脚本，跑完删除，基线 JSON 入库）。
"""
import json
from pathlib import Path

from django.test import SimpleTestCase

from apps.datafiles.parsers import get_parser
from apps.datafiles.parsers.base import BaseATEParser

GOLDEN = Path(__file__).resolve().parents[1] / 'backend' / 'data' / 'parse_golden.json'


def _fingerprint(path: Path):
    head = path.read_text(encoding='utf-8', errors='ignore')[:4096]
    fmt = BaseATEParser.identify_format(head)
    if fmt == 'Unknown':
        return None
    df, metadata = get_parser(fmt).parse(str(path))
    if df is None:
        return {'format': fmt, 'df_none': True}
    return {
        'format': fmt,
        'shape': list(df.shape),
        'columns': [str(c) for c in df.columns],
        'dtypes': {str(c): str(df[c].dtype) for c in df.columns},
        'head': df.head(20).to_csv(index=False),
        'meta': {k: _plain(v) for k, v in sorted(metadata.items())},
    }


def _plain(value):
    """metadata 值转可 JSON 化的稳定形态（dict 按键排序，集合转有序 list）。"""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return str(value)


class ParserSampleGoldenTests(SimpleTestCase):
    """每个格式各取 2 个真实样本，解析结果必须与基线 JSON 完全相等。"""

    def test_samples_match_golden(self):
        golden = json.loads(GOLDEN.read_text(encoding='utf-8'))
        seen = {}
        for path in sorted(Path('Data').glob('*.csv')):
            fp = _fingerprint(path)
            if not fp:
                continue
            fmt = fp['format']
            seen.setdefault(fmt, [])
            if len(seen[fmt]) >= 2:
                continue
            seen[fmt].append(path.name)
            self.assertIn(path.name, golden, f'基线缺少样本 {path.name} 的指纹')
            self.assertEqual(fp, golden[path.name],
                             f'{path.name}（{fmt}）解析结果与基线不一致')
        for fmt in ('CTA8290D', 'CTA8280F', 'ETS88', 'STS8200'):
            self.assertTrue(seen.get(fmt), f'Data/ 下找不到 {fmt} 样本，门禁未生效')
```

- [ ] **Step 2: 生成基线 JSON**

Create `tasks/make_parse_golden.py`（一次性，用完删）：

```python
"""一次性：为 test_parsers_sample_golden 生成基线指纹 JSON。"""
import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
import django
django.setup()

from test.backend.test_parsers_sample_golden import _fingerprint  # noqa: E402

out, seen = {}, {}
for path in sorted((ROOT / 'Data').glob('*.csv')):
    fp = _fingerprint(path)
    if not fp:
        continue
    fmt = fp['format']
    seen.setdefault(fmt, 0)
    if seen[fmt] >= 2:
        continue
    seen[fmt] += 1
    out[path.name] = fp
    print(f'{fmt:10} {path.name}')

dst = ROOT / 'test' / 'backend' / 'data'
dst.mkdir(parents=True, exist_ok=True)
(dst / 'parse_golden.json').write_text(
    json.dumps(out, indent=1, ensure_ascii=False), encoding='utf-8')
print('formats:', seen)
```

Run: `mkdir -p test/backend/data && .venv/Scripts/python.exe tasks/make_parse_golden.py`
Expected: 打印四行 `CTA8290D/CTA8280F/ETS88/STS8200` 各 2 个文件名，末行 `formats: {'CTA8290D': 2, 'CTA8280F': 2, 'ETS88': 2, 'STS8200': 2}`。
若某格式为 0：`Data/` 下缺该格式样本，**停下**向用户要样本文件（门禁不成立就不能继续）。

- [ ] **Step 3: 跑测试确认基线自洽（此时必绿）**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_parsers_sample_golden 2>&1 | tail -4`
Expected: `OK`

- [ ] **Step 4: Bin 列映射移到中性层（消除双份事实源）**

`apps/common/constants.py` 末尾追加：

```python
# 各测试格式的「软件 Bin」列名。单一事实源：解析器（``BaseATEParser``）与
# 分析侧（``statistics.helpers.get_bin_column_name``）共读本表。
# 此前解析器用 4 个类方法各返回一个字面串、分析侧另有一份 dict —— 同一知识
# 两份记录，加新格式时必然漏改一边。
BIN_COLUMN_MAPPING = {
    'CTA8290D': 'SW_Bin',
    'CTA8280F': 'SW_Bin',
    'ETS88': 'Bin',
    'STS8200': 'SOFT_BIN',
}
DEFAULT_BIN_COLUMN = 'SW_Bin'
```

Modify `apps/analysis/services/statistics/helpers.py`：删 `:14-20` 的本地 `BIN_COLUMN_MAPPING`，把 `:10` 附近的 import 补成
`from apps.common.constants import NON_NUMERIC_KEYWORDS, BIN_COLUMN_MAPPING, DEFAULT_BIN_COLUMN`
（按该文件现有 import 行合并，勿新增重复行），并将 `:22-23` 改为

```python
def get_bin_column_name(format_type: str) -> str:
    return BIN_COLUMN_MAPPING.get(format_type, DEFAULT_BIN_COLUMN)
```

- [ ] **Step 5: `base.py` 加列名赋值 helper + 家族模板类**

在 `apps/datafiles/parsers/base.py` 的 `import re` 之后补 `import os`（模板方法要用 `os.path.basename`）。

把 `BaseATEParser` 的 `get_bin_column_name`（当前 `:88-90` 的 `@staticmethod` 返回 `'SW_Bin'`）替换为实例方法：

```python
    def get_bin_column_name(self) -> str:
        """本格式的软件 Bin 列名（读 common 的单一映射）。"""
        return BIN_COLUMN_MAPPING.get(self.format_type, DEFAULT_BIN_COLUMN)
```

并在同一文件 `class BaseATEParser` 内 `make_column_names_unique` 之后追加静态 helper：

```python
    @staticmethod
    def assign_columns(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
        """把表头列名套到已读出的数据块上：列数相等直接命名，多则截断，
        少则补空列（各格式尾部列数不一致时的历史兜底语义）。"""
        if len(df.columns) == len(columns):
            df.columns = columns
        elif len(df.columns) > len(columns):
            df = df.iloc[:, :len(columns)]
            df.columns = columns
        else:
            for _ in range(len(columns) - len(df.columns)):
                df[len(df.columns)] = None
            df.columns = columns
        return df
```

在 `BaseATEParser` 之后（`NON_NUMERIC_COLUMNS` 定义之前或文件末尾均可，建议紧随基类）新增模板类：

```python
class OffsetHeaderParser(BaseATEParser):
    """`[Data]` 标记 + 固定行偏移表头的格式家族（CTA8290D / CTA8280F / STS8200）。

    三者此前的 ``parse()`` 有 40 行逐字节相同，差异全在下面三个类属性与
    ``post_process_header_meta`` 里。ETS88 的表头位置靠关键字搜索，不属本家族，
    自持 ``parse()``（只复用 ``assign_columns``）。
    """

    program_keyword: str = ''
    program_separator: str = ','
    header_labels: Dict[str, List[str]] = {}

    def _extract_program_name(self, lines: List[str]) -> str:
        for line in lines[:50]:
            if self.program_keyword in line:
                parts = line.strip().split(self.program_separator, 1)
                if len(parts) >= 2:
                    return os.path.basename(parts[1].strip(' ,"'))
                break
        return ''

    def post_process_header_meta(self, header_meta, lines, program_name):
        """家族扩展点：格式独有的表头字段推导（默认不改动）。"""
        return header_meta

    def parse(self, file_path: str) -> Tuple[Optional[pd.DataFrame], Optional[Dict]]:
        config = DATA_FORMAT_CONFIG.get(self.format_type)
        if not config:
            return None, None

        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        data_start = None
        for i, line in enumerate(lines):
            if config['marker'] in line:
                data_start = i
                break
        if data_start is None:
            return None, None

        header_line = lines[data_start + config['header_offset']].strip()
        unit_line = lines[data_start + config['unit_offset']].strip()
        min_line = lines[data_start + config['min_offset']].strip()
        max_line = lines[data_start + config['max_offset']].strip()

        columns = self.make_column_names_unique(
            [col.strip().strip('"') for col in header_line.split(',')])
        units = [unit.strip().strip('"') for unit in unit_line.split(',')]
        mins = [min_val.strip().strip('"') for min_val in min_line.split(',')]
        maxs = [max_val.strip().strip('"') for max_val in max_line.split(',')]

        df = pd.read_csv(file_path, skiprows=data_start + config['data_offset'],
                         header=None, on_bad_lines='skip', encoding='utf-8')
        df = self.assign_columns(df, columns)

        non_numeric = NON_NUMERIC_COLUMNS.get(self.format_type, [])
        for col in df.columns:
            if col not in non_numeric and df[col].dtype == object:
                df[col] = self.convert_to_numeric(df[col])

        program_name = self._extract_program_name(lines)
        header_meta = self.extract_header_metadata(lines, self.header_labels)
        header_meta = self.post_process_header_meta(header_meta, lines, program_name)

        metadata = {
            'format': self.format_type,
            'units': dict(zip(columns, units)),
            'mins': dict(zip(columns, mins)),
            'maxs': dict(zip(columns, maxs)),
            'program_name': program_name,
            'file_path': file_path,
            **header_meta,
        }
        return df, metadata
```

在 `base.py` 顶部 import 区补：
```python
from apps.common.constants import BIN_COLUMN_MAPPING, DEFAULT_BIN_COLUMN
```

- [ ] **Step 6: 三个子类瘦成声明**

`apps/datafiles/parsers/cta8290d.py` 全文替换为：

```python
from .base import OffsetHeaderParser
import logging

logger = logging.getLogger(__name__)


class CTA8290DParser(OffsetHeaderParser):
    format_type = 'CTA8290D'
    program_keyword = 'TestFile'
    program_separator = ','
    header_labels = {
        'start_time': ['StartTime'],
        'end_time': ['EndTime'],
        'lot_id': ['LotID'],
        'operator': ['Operator'],
        'station': ['Station'],
        'device_name': ['Device_Name'],
        'tester_type': ['Tester_Type'],
        'test_type': ['TestType'],
        'total_test_time': ['AllTestTime'],
        'handler': ['HandlerName'],
    }
```

`apps/datafiles/parsers/cta8280f.py` 全文替换为（注意关键字是 `TestFileName`，与上面**不是**同一个串）：

```python
from .base import OffsetHeaderParser
import logging

logger = logging.getLogger(__name__)


class CTA8280FParser(OffsetHeaderParser):
    format_type = 'CTA8280F'
    program_keyword = 'TestFileName'
    program_separator = ','
    header_labels = {
        'start_time': ['StartTime'],
        'end_time': ['EndTime'],
        'lot_id': ['LotID'],
        'operator': ['Operator'],
        'station': ['Test Station'],
        'device_name': ['Device Name'],
        'tester_type': ['Tester type'],
        'test_type': ['TestType'],
        'total_test_time': ['AllTestTime'],
        'handler': ['HandlerType'],
    }
```

`apps/datafiles/parsers/sts8200.py` 全文替换为：

```python
from .base import OffsetHeaderParser
import logging

logger = logging.getLogger(__name__)


class STS8200Parser(OffsetHeaderParser):
    format_type = 'STS8200'
    program_keyword = 'Program:'
    program_separator = ':'
    header_labels = {
        'start_time': ['Beginning Time'],
        'end_time': ['Ending Time'],
        'lot_id': ['LOT_ID'],
        'operator': ['User'],
        'station': ['Tester ID'],
        'tester_type': ['Tester ID'],
        'total_test_time': ['Total Testing Time'],
        'handler': ['Handler'],
    }

    def post_process_header_meta(self, header_meta, lines, program_name):
        # STS8200 的 station 名在首行（如 "STS8200-43 StationA"）
        if lines and 'station' not in header_meta:
            header_meta['station'] = lines[0].strip()
        # device_name 从 Program 路径推导：JAVBN281R3CYCAAV1.6.pgs → 剥扩展名与 JAV 前缀
        if program_name and 'device_name' not in header_meta:
            dev = program_name.replace('.pgs', '').replace('.DLL', '').replace('.dll', '')
            if dev.upper().startswith('JAV'):
                dev = dev[3:]
            header_meta['device_name'] = dev
        return header_meta
```

- [ ] **Step 7: ETS88 复用共享块并删自身 bin 列覆写**

`apps/datafiles/parsers/ets88.py`：

7a. 把 `:113-122` 的列名赋值块整段替换：

```python
        if len(df.columns) == len(columns):
            df.columns = columns
        elif len(df.columns) > len(columns):
            df = df.iloc[:, :len(columns)]
            df.columns = columns
        else:
            cols_to_pad = len(columns) - len(df.columns)
            for _ in range(cols_to_pad):
                df[len(df.columns)] = None
            df.columns = columns
```
→
```python
        df = self.assign_columns(df, columns)
```

7b. 删 `:168-170`：

```python
    @staticmethod
    def get_bin_column_name() -> str:
        return 'Bin'
```

7c. 确认 `:1` import 行仍需要 `BaseATEParser`（`class ETS88Parser(BaseATEParser)` 保持不动，ETS88 **不**改继承）。

- [ ] **Step 8: 检查 bin 列取名的调用形态未破**

`get_bin_column_name` 由 `@staticmethod` 变实例方法，唯一外部调用者是 `browse_views.py:316` 的 `parser.get_bin_column_name()`（实例上调用，兼容）。

Run: `grep -rn "get_bin_column_name()" --include="*.py" apps/ test/ scripts/`
Expected: 只有 `apps/datafiles/views/browse_views.py:316` 一处（`parser.` 形式）与 base.py 内部（若 Plan A 已删则无）。出现 `类名.get_bin_column_name()` 形式 → 停下，那需要实例。

- [ ] **Step 9: 验证**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_parsers_sample_golden 2>&1 | tail -4`
Expected: `OK` —— 这是本 Task 的核心门禁，四格式 8 个样本的列名/dtype/前 20 行/metadata 必须逐字段等于基线。
失败时打印的 diff 会指出哪个字段漂了：多半是 `program_name`（关键字/分隔符）、`station`/`device_name`（标签表或后处理）。

Run: `.venv/Scripts/python.exe manage.py test apps.datafiles apps.analysis apps.export apps.dashboard test.backend 2>&1 | tail -4`
Expected: `OK`

Run: `.venv/Scripts/python.exe manage.py test 2>&1 | tail -4`
Expected: `Ran <基线 + 新增样本用例数> tests`，`OK`

Run: `wc -l apps/datafiles/parsers/*.py`
Expected: `cta8290d.py` 与 `cta8280f.py` 各 ~22 行、`sts8200.py` ~37 行、`base.py` 由 ~165 涨到 ~250（模板类），四文件合计较改前**净减约 90 行**（原 698 含 `__init__`）。`base.py` 仍 <600 行。

- [ ] **Step 10: 提交（含基线 JSON，脚本删掉）**

```bash
rm tasks/make_parse_golden.py
git add apps/common/constants.py apps/analysis/services/statistics/helpers.py \
        apps/datafiles/parsers/ test/backend/test_parsers_sample_golden.py \
        test/backend/data/parse_golden.json
git status --short
git commit -m "$(cat <<'EOF'
refactor(parsers): CTA/STS 家族参数化 + Bin 列名单一事实源

cta8280f/cta8290d/sts8200 的 parse() 有 40 行逐字节相同（cta8280f 与
cta8290d 整文件仅 5 处差异），差异全在 program 关键字/分隔符、表头标签
映射与 STS8200 的 station/device_name 推导 —— 下沉为类属性与一个扩展点。
ETS88 表头靠关键字搜索，保持自持 parse()，仅复用列名赋值块。

同时把 4 处 get_bin_column_name 覆写与 analysis 侧 BIN_COLUMN_MAPPING
这份双记录合并到 common/constants（parser import analysis 会成环，
故落在中性层）。

新增样本指纹测试作为门禁：四格式各 2 个真实文件，列名/dtype/前 20 行/
metadata 全字段与基线逐位相等。
EOF
)"
```

---

## Task B2: SFTP 下载端点守卫抽取（R3 高危，必须跑 e2e）

**Files:**
- Modify: `apps/sftp/views.py`（新增 2 个守卫 helper + 6 处端点改调用）
- Test: `apps/sftp/tests.py`、`frontend/e2e/sftp/*.spec.ts`

**守卫矩阵（各端点现有语义，必须逐格保持）**：

| 端点 | 位置 | path 非空 | CSV 校验 | timeout 解析 | not_connected |
|---|---|---|---|---|---|
| `download` | :257-270 | ✅ 400 `缺少 path 参数` | ✅ 400 `仅支持 CSV 文件` | — | ✅ |
| `download_file_stream` | :297-314 | ✅ | ✅ | 连接**之后** | ✅ |
| `download_dir` | :344-362 | ✅ | ❌ **无**（收目录） | 连接**之前** | ✅ |
| `download_batch` | :389-402 | `paths` 空 → 400 `未选择文件`（不同码） | 列表过滤 | — | ✅ |
| `download_and_parse` | :439-455 | `elif` 分支 → 400 `需要 path 或 paths 参数` | ✅（两分支各自） | — | 在下游私有方法里 |
| `_single_download_parse` | :457-460 | —（上游已校验） | — | — | ✅ |
| `_batch_download_parse` | :486-489 | — | — | — | ✅ |

`views.py:260-262` 注释记录过一次真实事故：`request.data.get(k, default)` 的 default 只在键缺失时生效，值为 `None` 时拿到 `None` → `os.path.splitext(None)` → 500。守卫抽取不得改变这条判断的顺序或语义。

- [ ] **Step 1: 加两个守卫 helper（放在 `# Helpers` 段 :537 之前）**

```python
    # ------------------------------------------------------------------
    # Download guards
    # ------------------------------------------------------------------

    @staticmethod
    def _guard_remote_path(remote_path, *, require_csv=True):
        """远端路径校验。通过返回 ``None``，否则返回应直接 return 的 400 Response。

        ``require_csv=False`` 给 ``download_dir`` —— 它收的是目录路径，历史上
        从不做 CSV 校验，这是既有契约而非遗漏（前端不会因此拿到不同响应）。
        先判 ``not remote_path`` 再碰 ``os.path.splitext``：值为 None 时
        ``_is_csv`` 会抛 TypeError → 500（见 download 原注释记录的事故）。
        """
        if not remote_path:
            return Response({'error': '缺少 path 参数'}, status=400)
        if require_csv and not _is_csv(remote_path):
            return Response({'error': '仅支持 CSV 文件'}, status=400)
        return None

    def _get_connection_or_error(self, request):
        """取 SFTP 连接：返回 ``(sftp, None)`` 或 ``(None, 400 not_connected)``。"""
        sftp = self._get_connection(request)
        if not sftp:
            return None, Response({'error': 'not_connected'}, status=400)
        return sftp, None
```

- [ ] **Step 2: 逐端点替换（严格保持原顺序）**

2a. `download`（:259-270）改为：

```python
        remote_path = request.data.get('path')
        err = self._guard_remote_path(remote_path)
        if err is not None:
            return err

        sftp, err = self._get_connection_or_error(request)
        if err is not None:
            return err
```
（其下 `file_path = None` / `try:` / 落盘链**原样保留** —— 见 F1，异常清理依赖调用方持有的 `file_path`。）

2b. `download_file_stream`（:306-314）同样两段替换；其后的 `timeout_sec` 解析块位置不变（原本就在连接之后）。

2c. `download_dir`（:351-362）：

```python
        remote_path = request.data.get('path')
        err = self._guard_remote_path(remote_path, require_csv=False)
        if err is not None:
            return err
        timeout_sec = request.data.get('timeout')
        if timeout_sec is None:
            setting, _ = UserSetting.objects.get_or_create(user=request.user)
            timeout_sec = setting.sftp_download_timeout
        timeout_sec = clamp_timeout(timeout_sec)

        sftp, err = self._get_connection_or_error(request)
        if err is not None:
            return err
```

2d. `download`/`download_dir` 之外的 `_single_download_parse`（:457-460）与 `_batch_download_parse`（:486-489）：只把连接守卫两行换成

```python
        sftp, err = self._get_connection_or_error(request)
        if err is not None:
            return err
```

2e. `download_batch`（:391-402）与 `download_and_parse`（:442-455）**不改** path/csv 部分——它们的错误文案与判据不同（`未选择文件` / `无 CSV 文件` / `需要 path 或 paths 参数`），套 helper 会改响应体。只改 `download_batch` 的连接守卫两行。

Run: `grep -n "not_connected" apps/sftp/views.py`
Expected: 命中数由 7 降为 **2**（helper 内 1 处 + 未改动的 `download_batch`? 不，2e 已改）→ 实际应为 helper 内 1 处 + 其余端点通过 helper。逐行看：helper 的 `Response({'error': 'not_connected'}` 1 处；若还有第二处，说明有个端点漏改，补上。

Run: `grep -c "缺少 path 参数\|仅支持 CSV 文件" apps/sftp/views.py`
Expected: 2（helper 内各 1；`download_and_parse` 的 `需要 path 或 paths 参数` 不计入）

- [ ] **Step 3: 单测回归**

Run: `.venv/Scripts/python.exe manage.py test apps.sftp 2>&1 | tail -4`
Expected: `OK`

Run: `.venv/Scripts/python.exe manage.py test 2>&1 | tail -4`
Expected: `OK`

- [ ] **Step 4: e2e（本 Task 强制，状态码是唯一风险面）**

Run: `cd frontend && npx playwright test e2e/sftp --project=P1 2>&1 | tail -12`
Expected: 全绿（0 failed）。失败后按 lessons R2③：先对基线复跑区分存量失败，再单文件隔离复跑排 flake。

Run: `cd .. && netstat -ano | grep -E ":8000|:3000" | grep LISTEN`
Expected: 无输出。

- [ ] **Step 5: 提交**

```bash
git add apps/sftp/views.py
git commit -m "$(cat <<'EOF'
refactor(sftp): 下载端点守卫抽成显式 helper

6 个下载端点各自重写 path 非空 / CSV 白名单 / not_connected 三段守卫
（not_connected 7 份、CSV 校验 6 份）。抽成 _guard_remote_path(require_csv=)
与 _get_connection_or_error，并把 download_dir 不校验 CSV 这一既有契约
写成签名上的显式参数而非散落的遗漏。

落盘/注册/半截清理链保持内联：异常处理依赖调用方在 try 前持有的
file_path，移进 helper 会让失败时留下未注册的孤儿残片。
EOF
)"
```

---

## Task B3: Excel 样式与 save_excelize 复用共享层

**Files:**
- Modify: `apps/export/excelize_helpers.py`（`save_excelize` 补 close 保证 + 新增 `make_bordered_style`）
- Modify: `apps/gage/gage_legacy_builder.py`（:89-100/:101-106/:117-127 换共享工厂；:128-215 的 8 个 thick_* 换本地工厂；:644-680 换 `thin_border`；:883-901 换 `save_excelize`）
- Test: `test/backend/test_gage_builder.py`、`apps/gage/tests.py`

**已核实**：两个 gage 测试文件对 style/fill/border/color **零断言**（只读值）→ 样式改造必须由**导出前后对拍**兜底，见 Step 5。

**逐字段等价表**（决定哪些能直接换）：

| legacy 位置 | 内容 | 共享等价物 | 处置 |
|---|---|---|---|
| :90-100 `header_style` | bold12 白字 + `COLOR_HEADER_BG` + 4 边 style=2 + center | `make_header_style(f, 12)` | ✅ 直接换 |
| :101-106 `title_style` | bold16 + 同底色，无边框 | `make_title_style(f)` | ✅ 直接换 |
| :117-127 `data_style` | size10 + `COLOR_DATA_BG` + 4 边 style=1 | `make_data_style(f)` | ✅ 直接换 |
| :128-215 `thick_top_style` 等 8 个 | 各边 style 混搭（2/1） | 无 | 本地参数化工厂 |
| :644-680 4 个 | fill + 4 边 `color="000000"` style=1 | `thin_border("000000")` | ✅ 换 border 列表 |
| :883-901 保存 | 临时文件 + read + `finally` close/unlink | `save_excelize` | 先补强 helpers 再复用 |

- [ ] **Step 1: 先给 `save_excelize` 补上 legacy 的 close 保证**

Modify `apps/export/excelize_helpers.py:198-209`：

```python
def save_excelize(f):
    """Save excelize workbook to bytes via temp file."""
    with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        f.save_as(tmp_path)
        f.close()
        with open(tmp_path, 'rb') as fh:
            return fh.read()
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
```
→
```python
def save_excelize(f):
    """Save excelize workbook to bytes via a temp file.

    ``close`` 放在 ``finally``：``save_as`` / 读取抛错时句柄与临时文件都必须
    释放（gage 侧记为 defect #10），否则 Windows 上会留文件锁。
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
            tmp_path = tmp.name
        f.save_as(tmp_path)
        with open(tmp_path, 'rb') as fh:
            return fh.read()
    finally:
        try:
            f.close()
        except Exception:
            pass
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
```

Run: `.venv/Scripts/python.exe manage.py test apps.export apps.buyoff test.backend.test_gage_builder 2>&1 | tail -4`
Expected: `OK`（现有 `save_excelize` 消费者：export/buyoff/gage views）

- [ ] **Step 2: gage 的三个等价样式改调共享工厂**

Modify `apps/gage/gage_legacy_builder.py`：把 :90-127 的 `header_style` / `title_style` / `data_style` 三段 `f.new_style(excelize.Style(...))` 整体替换为：

```python
    header_style = make_header_style(f, 12)
    title_style = make_title_style(f)
    data_style = make_data_style(f)
```

并在文件顶部 import 区补（与 Plan A Step 3 改后的 import 并列）：

```python
from apps.export.excelize_helpers import (
    make_header_style, make_title_style, make_data_style, thin_border, save_excelize,
)
```

- [ ] **Step 3: 8 个 thick_* 样式换本地参数化工厂**

Modify `apps/gage/gage_legacy_builder.py:128-215`（`thick_top_style` 到 `thick_bottom_right_style` 共 8 段），整段替换为：

```python
    def bordered(fill_color, left, top_, bottom, right):
        """data 底色 + 各边可指定粗细的样式（表头收尾线的历史布局需要）。"""
        return f.new_style(excelize.Style(
            font=excelize.Font(size=10, color=COLOR_FONT_DARK, family="Calibri"),
            fill=excelize.Fill(type="pattern", color=[fill_color], pattern=1),
            border=[
                excelize.Border(type="left", color=COLOR_BORDER, style=left),
                excelize.Border(type="top", color=COLOR_BORDER, style=top_),
                excelize.Border(type="bottom", color=COLOR_BORDER, style=bottom),
                excelize.Border(type="right", color=COLOR_BORDER, style=right),
            ],
            alignment=excelize.Alignment(horizontal="center", vertical="center"),
        ))

    DATA = COLOR_DATA_BG
    thick_top_style = bordered(DATA, 2, 2, 1, 1)
    thick_top_mid_style = bordered(DATA, 1, 2, 1, 1)
    thick_top_right_style = bordered(DATA, 1, 2, 1, 2)
    thick_left_style = bordered(DATA, 2, 1, 1, 1)
    thick_right_style = bordered(DATA, 1, 1, 1, 2)
    thick_bottom_style = bordered(DATA, 2, 1, 2, 1)
    thick_bottom_mid_style = bordered(DATA, 1, 1, 2, 1)
    thick_bottom_right_style = bordered(DATA, 1, 1, 2, 2)
```

（粗细取值逐个照搬原 :131-134、:143-146、:154-157、:165-168、:176-179、:187-190、:198-201、:209-212 的 `(left, top, bottom, right)`，**不得凭记忆填**。）

Run: 用 Read 复核 `git diff apps/gage/gage_legacy_builder.py` 里 8 组四元组与原文件一一对应
Expected: 8 行 diff 全部匹配原 style 值

- [ ] **Step 4: 分文件表样式复用 `thin_border`**

Modify `:644-680` 四个样式定义：

```python
    light_blue_style = f.new_style(excelize.Style(
        fill=excelize.Fill(type="pattern", color=[FILL_LIGHT_BLUE_HEX], pattern=1),
        border=thin_border("000000"),
    ))
    gray_style = f.new_style(excelize.Style(
        fill=excelize.Fill(type="pattern", color=[FILL_GRAY_HEX], pattern=1),
        border=thin_border("000000"),
    ))
    stats_gray_style = f.new_style(excelize.Style(
        fill=excelize.Fill(type="pattern", color=[FILL_GRAY_HEX], pattern=1),
        border=thin_border("000000"),
        alignment=excelize.Alignment(horizontal="right"),
    ))
    stats_border_style = f.new_style(excelize.Style(
        border=thin_border("000000"),
        alignment=excelize.Alignment(horizontal="right"),
    ))
```

- [ ] **Step 5: 导出样式前后对拍（本 Task 的等价性证明）**

先取改前的样式快照：

```bash
git stash push -- apps/gage/gage_legacy_builder.py
.venv/Scripts/python.exe tasks/gage_style_snapshot.py > tasks/gage_style_before.txt
git stash pop
```

Create `tasks/gage_style_snapshot.py`（一次性）：

```python
"""导出 gage 工作簿的逐单元格样式指纹（font/fill/border/alignment）。"""
import io, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
import django
django.setup()

import pandas as pd
from openpyxl import load_workbook
from apps.gage.gage_legacy_builder import build_gage_summary_excel

cols = {'V1': [1.0, 2.0, 3.0, 4.0], 'V2': [2.0, 2.0, 2.0, 2.0]}
ds = [{'filename': f'f{i}.csv', 'df': pd.DataFrame(cols),
       'metadata': {'format': 'CTA8290D', 'mins': {'V1': '0', 'V2': '0'},
                    'maxs': {'V1': '4', 'V2': '4'}, 'units': {'V1': 'u', 'V2': 'u'},
                    'tester_id': 'T', 'program_name': 'P', 'start_time': 'x'}}
      for i in (1, 2)]
wb = load_workbook(io.BytesIO(build_gage_summary_excel(ds, False)))
for ws in wb.worksheets:
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 130),
                            max_col=min(ws.max_column, 30)):
        for c in row:
            if c.has_style:
                print(f'{ws.title}!{c.coordinate} font={c.font.bold},{c.font.size},'
                      f'{c.font.color.rgb if c.font.color else None} '
                      f'fill={c.fill.fgColor.rgb} b={c.border.left.style},'
                      f'{c.border.top.style},{c.border.bottom.style},'
                      f'{c.border.right.style} al={c.alignment.horizontal}')
```

Run（改后）: `.venv/Scripts/python.exe tasks/gage_style_snapshot.py > tasks/gage_style_after.txt && diff tasks/gage_style_before.txt tasks/gage_style_after.txt && echo "STYLES IDENTICAL"`
Expected: `STYLES IDENTICAL`（零 diff）
若有 diff：**停下**，逐格核对是 style 编号变了还是属性真变了；属性变了说明等价表有一格判断错，回退该处替换。

- [ ] **Step 6: 保存段复用 `save_excelize`**

Modify `apps/gage/gage_legacy_builder.py` 末尾（原 :883-901）：把整段 try/finally 临时文件逻辑替换为

```python
    return save_excelize(f)
```

Run: `grep -n "tempfile\|NamedTemporaryFile" apps/gage/gage_legacy_builder.py`
Expected: 无输出 → 同删顶部 `import tempfile`（`import os` 若仍被其他行使用则保留，用 `grep -c "os\." apps/gage/gage_legacy_builder.py` 判断）。

- [ ] **Step 7: 回归 + 提交**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_gage_builder apps.gage apps.export apps.buyoff 2>&1 | tail -4`
Expected: `OK`
Run: `.venv/Scripts/python.exe manage.py test 2>&1 | tail -4`
Expected: `OK`，用例数与基线一致
Run: `wc -l apps/gage/gage_legacy_builder.py`
Expected: 由 ~894 降到约 770（本 Task 净减 ~110 行，仍 >600 → 拆分按决策 D4 另立项目）

```bash
rm tasks/gage_style_snapshot.py tasks/gage_style_before.txt tasks/gage_style_after.txt
git add apps/export/excelize_helpers.py apps/gage/gage_legacy_builder.py
git commit -m "$(cat <<'EOF'
refactor(excel): gage 样式与保存逻辑复用共享 helper

header/title/data 三个样式与 export.excelize_helpers 的同名工厂逐字段等价，
直接改调；8 个粗细混搭的 thick_* 收成 8 行调用；分文件表 4 个样式的
4×Border 字面量改用现成的 thin_border("000000")。

save_excelize 补上 legacy 侧的 close-in-finally 保证（defect #10：读取失败
也须释放句柄与临时文件，否则 Windows 留锁），随后删除 gage 内那份注释自称
"避免跨模块依赖"的本地副本 —— apps/gage/views.py 早已 import 该 helper。

等价性由逐单元格样式指纹前后 diff 为零证明（测试仅断言值，不断言样式）。
EOF
)"
```

---

## Task B4: 视图与服务层小重复抽取

**Files & 具体项：**
- Modify: `apps/analysis/services/data_services/serial_distribution.py:71-124`
- Modify: `apps/export/charts.py:122-129,174-181`
- Modify: `apps/datafiles/views/_helpers.py`（+`batch_views.py` 2 处、`_helpers.py` 2 处调用）
- Modify: `apps/analysis/views/_helpers.py`（新增 `require_param`）+ `analysis_views.py:630-641` + `statistics_views.py:99-110`
- Modify: `apps/analysis/views/statistics_views.py:351-390`（boxplot 双分支）
- Modify: `apps/analysis/views/file_correlation_views.py:71-85,105-119`
- Modify: `apps/common/constants.py` + 4 处数值列谓词消费点
- Modify: `apps/datafiles/utils.py` + `apps/sftp/local_paths.py` + `file_views.py:567-571`

- [ ] **Step 1: `require_param`（直接服务 lessons R3①：相似端点守卫必须对齐）**

`apps/analysis/views/_helpers.py` 末尾新增（该文件已 import `Response`；若无则补 `from rest_framework.response import Response` 与 `from apps.common.params import get_param`）：

```python
def require_param(request, df):
    """取 ``param`` 并校验其存在于 df 列中。

    返回 ``(param, None)`` 或 ``(None, 400 Response)``——调用方 ``if err: return err``。
    此前 histogram/qqplot/site_stats 等端点各写一份同样的 11 行守卫，一份改了
    另一份漏改就会让同类端点一个返 400 一个 500（审查 R3①）。
    """
    param = get_param(request, 'param')
    if not param:
        return None, Response({'error': 'param_required'}, status=400)
    if param not in df.columns:
        return None, Response({
            'error': 'param_not_found',
            'detail': f'参数 {param!r} 不在该文件中',
        }, status=400)
    return param, None
```

把 `analysis_views.py:636-641` 与 `statistics_views.py:104-110` 的两段守卫各替换为：

```python
        param, err = require_param(request, df)
        if err is not None:
            return err
```

并在两文件的 `from ._helpers import (...)` 块内补 `require_param,`。

Run: `grep -rn "param_required" apps/analysis/views/`
Expected: 只剩 `_helpers.py` 内 1 处（原 3+ 处）

- [ ] **Step 2: `serial_distribution` 有/无 Site 双分支合并**

`apps/analysis/services/data_services/serial_distribution.py` 新增模块级私有函数（放在 `MAX_POINTS` 等常量之后、首个 public 函数之前）：

```python
def _group_last(work, keys, value_cols, expected_cols):
    """按 ``keys`` 分组取 ``.last()`` 并把列归位到 ``expected_cols``。

    retest 行追加在后面，最后一行才是该 die 的最终结果（.last() 的语义依据）。
    groupby 的输出列序不保证与 keys 顺序一致，故按期望列名重贴标签；
    MultiIndex 与单层两种情况都要归一化索引名，否则 reset_index 后列位漂移。
    """
    grouped = work.groupby(keys)[value_cols].last()
    if isinstance(grouped.index, pd.MultiIndex):
        grouped.index.names = [f'__idx_{i}__' for i in range(grouped.index.nlevels)]
    else:
        grouped.index.name = '__idx_0__'
    grouped = grouped.reset_index()
    grouped = grouped.iloc[:, :len(expected_cols)]
    grouped.columns = expected_cols
    return grouped


def _expected_cols(*names):
    """去重保序（同名列只出现一次；bin 可能与 param/serial 同名）。"""
    seen, out = set(), []
    for n in names:
        if n is not None and n not in seen:
            seen.add(n)
            out.append(n)
    return out
```

把 :71-124 的 if/else 双分支替换为：

```python
    if site_col:
        cols = _expected_cols(serial_col, site_col, param, bin_col)
        work = df[cols].copy()
        work[site_col] = get_1d_from(work, site_col)
        keys = [get_1d_from(work, site_col), get_1d_from(work, serial_col)]
        expected = _expected_cols(site_col, serial_col, param, bin_col)
    else:
        cols = _expected_cols(serial_col, param, bin_col)
        work = df[cols].copy()
        keys = [get_1d_from(work, serial_col)]
        expected = _expected_cols(serial_col, param, bin_col)

    work[param] = pd.to_numeric(work[param], errors='coerce')
    work = work[np.isfinite(work[param].values) | work[param].isna().values]
    work = work.reset_index(drop=True)
    work[serial_col] = pd.to_numeric(work[serial_col], errors='coerce')
    value_cols = [c for c in (param, bin_col) if c is not None]
    serial_grouped = _group_last(work, keys, value_cols, expected)
```

**注意等价性细节**：原 site 分支把 `sws[serial_col] = pd.to_numeric(...)` 放在 isfinite 过滤**之后**（:80），无 site 分支同样在过滤后（:108）—— 上面代码保持了这个顺序（先 param 过滤，再转 serial）。原分支的 `group_cols = [param] + ([bin_col] if bin_col else [])` 与新 `value_cols` 一致。

Run: `.venv/Scripts/python.exe manage.py test apps.analysis tests_serial_column 2>&1 | tail -4`
Expected: `OK`
Run: `.venv/Scripts/python.exe manage.py test apps.analysis 2>&1 | tail -4`
Expected: `OK`（`apps/analysis/` 有 173+ 例覆盖序列分布）

- [ ] **Step 3: `charts.py` sigma 带循环收敛（不动 export_ppt，见 F3）**

`apps/export/charts.py` 新增模块级函数（放在 `_render_histogram_payload` 之前）：

```python
SIGMA_PALETTE = ((3, COLOR_SIGMA_3), (4, COLOR_SIGMA_4), (6, COLOR_SIGMA_6))


def _sigma_bands(mean_val, std_val, flags):
    """[(sigma, lower, upper, color, label)]；std<=0 或该 sigma 未勾选则跳过。

    同一函数内画线与加标签两处此前各写一遍 mean±σ*std 与调色板三元组
    （:122-129 / :174-181），改一处忘改另一处会让图上虚线有、标签无。
    """
    if not std_val > 0:
        return []
    return [(s, mean_val - s * std_val, mean_val + s * std_val, color, f'{s}σ')
            for s, color in SIGMA_PALETTE if flags.get(s)]
```

原 :122-129 替换为：

```python
    for sigma, lower, upper, color, _label in _sigma_bands(
            mean_val, std_val,
            {3: show_3sigma, 4: show_4sigma, 6: show_6sigma}):
        ax.axvline(x=lower, color=color, linewidth=2, linestyle=':')
        ax.axvline(x=upper, color=color, linewidth=2, linestyle=':')
```

原 :174-181 替换为：

```python
    for sigma, lower, upper, color, label_prefix in _sigma_bands(
            mean_val, std_val,
            {3: show_3sigma, 4: show_4sigma, 6: show_6sigma}):
        _add_vline_label(ax, lower, f'{label_prefix}下限', color)
        _add_vline_label(ax, upper, f'{label_prefix}上限', color)
```

- [ ] **Step 4: 已注册批量路径集合单源**

`apps/datafiles/views/_helpers.py` 新增（`_user_upload_dir` 之后）：

```python
def _registered_batch_paths(user, batch_name=None):
    """用户已注册批量文件的**归一化磁盘路径**集合。

    两侧同时 normpath + resolve_file_path 是必须的：DB 存相对路径
    （``data/<user>/...``）而 os.walk 给绝对路径，不归一化则集合永不相交
    → 重复导入 / 把已导入的批次误报为未注册（历史 bug）。
    """
    qs = DataFile.objects.filter(owner=user, file_type='batch')
    if batch_name is not None:
        qs = qs.filter(batch_name=batch_name)
    return {os.path.normpath(resolve_file_path(p))
            for p in qs.values_list('file_path', flat=True)}
```

替换 3 个 set 形态站点（**第 4 处 `batch_views.py:38-60` 是 `dict[batch_name] -> set`，形状不同，不改**）：
- `apps/datafiles/views/batch_views.py:157-162` → `existing_paths = _registered_batch_paths(request.user, dir_name)`（并把 :154-156 的 "Mirrors … above" 注释删掉，现在同源了）
- `apps/datafiles/views/_helpers.py:399-403` → `existing_paths = _registered_batch_paths(user, batch_name)`
- `apps/datafiles/views/_helpers.py:462-467` → `registered_paths = _registered_batch_paths(user)`

在 `apps/datafiles/views/__init__.py` 的 `_helpers` re-export 块内补 `_registered_batch_paths,`。

Run: `grep -rn "os.path.normpath(resolve_file_path" apps/datafiles/views/`
Expected: 只剩 `_helpers.py` 内 helper 自身 1 处

Run: `.venv/Scripts/python.exe manage.py test apps.datafiles 2>&1 | tail -4`
Expected: `OK`（批次一致性/孤儿扫描相关用例）

- [ ] **Step 5: boxplot by_site/by_bin 双分支合并**

`apps/analysis/views/statistics_views.py` 新增模块级 helper（放文件末尾或 `clean_data` 附近）：

```python
def _boxplot_by_group(data_series, group_idx, spec_limits, iqr_multiplier):
    """按分组索引逐组算箱线图统计；NaN 分组值不参与分组。

    by_site 与 by_bin 此前各写一份同样的 unique→跳过 NaN→mask→Series 转
    ndarray→compute_boxplot_stats 循环，差异只在分组索引列。
    """
    out = {}
    for val in group_idx.unique():
        if pd.isna(val):
            continue
        mask = group_idx == val
        if isinstance(mask, pd.Series):
            mask = mask.values
        out[str(val)] = compute_boxplot_stats(
            data_series[mask], spec_limits, iqr_multiplier)
    return out
```

:351-365 → 
```python
            if group_by == 'site':
                site_col = get_site_column(df)
                if site_col:
                    param_result['by_site'] = _boxplot_by_group(
                        data_series, get_1d_from(df, site_col),
                        spec_limits, iqr_multiplier)
```

:367-390 → 保留 bin 列回退逻辑（那段"优先按格式映射、否则扫含 bin 的列"是有意的历史修正，注释已记录），只把内层循环换成
```python
                if bin_col:
                    param_result['by_bin'] = _boxplot_by_group(
                        data_series, get_1d_from(df, bin_col),
                        spec_limits, iqr_multiplier)
```

- [ ] **Step 6: `file_correlation_views` 同文件双份 body**

`apps/analysis/views/file_correlation_views.py` 新增模块级函数：

```python
def _compute_correlation(request):
    """加载两文件 → 计算相关性。返回 ``(result, None)`` 或 ``(None, err_tuple)``，
    ``err_tuple = (body, status)`` 由调用方包成 Response（导出端点还要拿 result）。

    file_correlation 与 file_correlation_export 此前各写一遍 load+compute+
    NoCommonParamsError 的 13 行，两个端点的"无相同测试项"文案必须一致。
    """
    payload, err = _load_file_correlation_pair(request)
    if err is not None:
        return None, err
    try:
        result = compute_file_correlation(
            payload['ate_df'], payload['metadata_a'],
            payload['bench_df'], payload['metadata_b'],
            _parse_fc_config(request),
            file1_name=payload['file1_name'], file2_name=payload['file2_name'])
    except NoCommonParamsError:
        return None, ({'error': 'no_common_params',
                       'detail': '两个文件没有相同的测试项'}, 400)
    return result, None
```

:72-85 与 :106-119 两处各替换为：

```python
        result, err = _compute_correlation(request)
        if err is not None:
            return Response(err[0], status=err[1])
```

Run: `.venv/Scripts/python.exe manage.py test apps.analysis.test 2>&1 | tail -4`
Run: `.venv/Scripts/python.exe manage.py test apps.analysis 2>&1 | tail -4`
Expected: `OK`（`tests_file_correlation.py`、`tests_file_correlation_service.py` 覆盖两端的 400 与正常路径）

- [ ] **Step 7: 数值参数列谓词单源（R4①）**

`apps/analysis/services/statistics/helpers.py` 新增：

```python
def is_numeric_param(series: pd.Series) -> bool:
    """是否「可测量的数值参数」：数值 dtype 且非 bool。

    bool 必须显式排除 —— ``is_numeric_dtype`` 对 bool 返回 True，而真实数据里的
    ``Dut_Pass`` 是 pass/fail 标志，不是可测量参数：为它算箱线图/相关矩阵无意义，
    且 ``ensure_numeric`` 加 ``.astype(float)`` 之前它还会让 ``.quantile()``
    抛 "numpy boolean subtract"。
    """
    return bool(pd.api.types.is_numeric_dtype(series)
                and not pd.api.types.is_bool_dtype(series))
```

在 `statistics/__init__.py` 的 import 与 `__all__` 各加 `is_numeric_param`。

四个调用点改为使用该谓词（**各自的附加条件原样保留**，它们是真实差异）：
- `apps/analysis/views/analysis_views.py:119-123`：`[c for c in df.columns if is_numeric_param(df[c]) and not df[c].dropna().empty and c not in _meta_cols]`
- `apps/analysis/services/data_services/multi_lot.py:36-41`：`[c for c in df.columns if str(c).strip() and is_numeric_param(df[c])]`
- `apps/analysis/services/file_correlation.py:80-83`：`[c for c in df.columns if c not in excluded and is_numeric_param(df[c])]`
- `apps/analysis/services/statistics/site_yield.py:207`：`if not is_numeric_param(df[col]): continue`

四个调用点**各自补 import**（按该文件既有风格二选一，勿混用两条来源）：
`analysis_views.py` 在已有的 `from apps.analysis.services.statistics import (...)` 块内加 `is_numeric_param,`；
`multi_lot.py` / `file_correlation.py` 同法（它们已从 `apps.analysis.services.statistics` 或 `.statistics` 批量 import）；
`site_yield.py` 在 `statistics` 包内，用 `from .helpers import is_numeric_param`（与该文件现有 helper 导入合并）。

Run: `.venv/Scripts/python.exe -c "
import os,django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.development');django.setup()
import apps.analysis.views.analysis_views, apps.analysis.services.data_services.multi_lot
import apps.analysis.services.file_correlation, apps.analysis.services.statistics.site_yield
print('imports ok')"`
Expected: `imports ok`

三处调用点上方那段重复的注释（"dtype 白名单漏 int32/float32…pandas 3.0 下 str 不是 object…bool 会被纳入"）压缩为一行 `# 候选口径单一来源见 is_numeric_param（bool/Dut_Pass 陷阱）`，事实移到谓词 docstring（上面已写）。
**`analysis/views/_helpers.py:130-142` 不动**（遍历 params 且处理重名列/全 NaN，形状不同）。

Run: `grep -rn "is_bool_dtype" apps/analysis/`
Expected: 只有 `helpers.py` 的谓词 1 处（+ `_helpers.py:142` 那处保留）

- [ ] **Step 8: 上传文件名碰撞复用（只改语义一致的那一处）**

`apps/datafiles/utils.py` 新增（`resolve_file_path` 附近）：

```python
def unique_local_path(upload_dir, filename):
    """``upload_dir`` 下不与既有文件冲突的落地路径：``name_<ts><ext>``，
    同秒再次碰撞追加序号（批量里 ``/a/dup.csv`` 与 ``/b/dup.csv`` 会同秒）。
    """
    candidate = os.path.join(upload_dir, filename)
    if not os.path.exists(candidate):
        return candidate
    name, ext = os.path.splitext(filename)
    ts = int(time.time())
    candidate = os.path.join(upload_dir, f'{name}_{ts}{ext}')
    seq = 1
    while os.path.exists(candidate):
        candidate = os.path.join(upload_dir, f'{name}_{ts}_{seq}{ext}')
        seq += 1
    return candidate
```
（已核实 `apps/datafiles/utils.py` 顶部只有 `import os` / `import re` / `from django.conf import settings`，**需新增 `import time`**。）

- `apps/sftp/local_paths.py:16-34` 的 `resolve_local_path` 函数体改为 `return unique_local_path(upload_dir, filename)`（顶部 `from apps.datafiles.utils import unique_local_path`；其 `import time` 随原函数体一起删除）。sftp 的 5 处调用点不动（`views.py:21` 仍从 `.local_paths` import；已核实全仓 `test/` 无对 `resolve_local_path` 的直接引用，故不会破坏 monkeypatch）。
- `apps/datafiles/views/file_views.py:566-571`（上传单文件碰撞）替换为：

```python
            file_path = unique_local_path(upload_dir, base_name)
```
（已核实 `_ext` 仅在被替换的 :570-571 两行内出现、块外无引用者，可安全删除；`file_views.py` 顶部 import 补 `unique_local_path`。）

`file_views.py:312-317` 与 `:413-418` **保持不动**（`_{ts}_{df.pk}` 是批内按 pk 保唯一的另一策略，见 F2 段的 P1-5 澄清）。

Run: `.venv/Scripts/python.exe manage.py test apps.datafiles apps.sftp 2>&1 | tail -4`
Expected: `OK`

- [ ] **Step 9: 全量回归 + 提交**

Run: `.venv/Scripts/python.exe manage.py test 2>&1 | tail -4`
Expected: `OK`，用例数与基线一致
Run: `cd frontend && npx playwright test e2e/analysis --project=P1 2>&1 | tail -10`
Expected: 全绿（Step 1/5/6 都改了 analysis 端点的响应路径）
Run: `cd .. && netstat -ano | grep -E ":8000|:3000" | grep LISTEN`
Expected: 无输出

```bash
git add apps/analysis/ apps/export/charts.py apps/datafiles/ apps/sftp/local_paths.py apps/common/constants.py
git status --short
git commit -m "$(cat <<'EOF'
refactor: 视图与服务层结构重复收敛

- require_param：histogram/qqplot/site_stats 各写一份的 11 行参数守卫对齐
  （R3①：一个改了另一个漏改就是把 400 变 500）
- serial_distribution 有/无 Site 两分支 → _group_last
- charts 同函数内两遍 mean±σ*std → _sigma_bands
- 已注册批量路径集合 3 份 → _registered_batch_paths（normpath 是历史 bug 点）
- boxplot by_site/by_bin 双循环 → _boxplot_by_group
- file_correlation 两端点重复 body → _compute_correlation
- is_numeric_param：Dut_Pass(bool) 陷阱的单一谓词（R4①）
- unique_local_path 落在 datafiles/utils，sftp 与上传碰撞共用

export_ppt 的 σ 带读服务端预计算的裁剪带，语义不同，未并入。
EOF
)"
```

---

## Task B5: 拆分 `analysis_views.py`（689 → 约 360 行，决策 D4）

**Files:**
- Create: `apps/analysis/views/histogram_views.py`（`histogram` 原 :73-237，165 行）
- Create: `apps/analysis/views/multi_lot_views.py`（`multi_lot` 原 :284-456，173 行）
- Modify: `apps/analysis/views/analysis_views.py`（删这两个方法 + 加 mixin import/继承）
- Modify: `apps/analysis/views/__init__.py`（如需 re-export）

**遵循既有模式**：`file_correlation_views.py` 已用 `FileCorrelationActions` mixin 混入 `AnalysisViewSet`（`analysis_views.py:53,69`）——为绕 600 行上限而设的同款约定。路由（`urls.py` 注册 `AnalysisViewSet`）、权限声明、OpenAPI 分组均不变。

- [ ] **Step 0: 先算出当前真实边界（不要照抄任何写死的行号）**

Task B4 会压缩本文件（`require_param` 抽取、数值列谓词各删若干行），所以 spec/计划里出现过的行号此刻**都已漂移**。执行时先跑：

```bash
.venv/Scripts/python.exe - <<'PY'
import re
from pathlib import Path
lines = Path('apps/analysis/views/analysis_views.py').read_text(encoding='utf-8').splitlines(keepends=True)
marks = []
for i, ln in enumerate(lines):
    m = re.match(r'    def (\w+)\(self', ln)
    if m:
        start = i - 1 if lines[i - 1].lstrip().startswith('@action') else i
        marks.append((start, m.group(1)))
for j, (start, name) in enumerate(marks):
    end = marks[j + 1][0] if j + 1 < len(marks) else len(lines)
    print(f'{name:22} {start + 1}-{end}')
PY
```
Expected: 打印 8 行方法名与区间，含 `histogram` 与 `multi_lot` 两行。**记下这两行给出的区间**，下面用 `<HIST_A>-<HIST_B>` / `<ML_A>-<ML_B>` 指代它们。`histogram` 的区间应以 `wafer_map` 前一行结束（脚本已保证），`multi_lot` 以 `correlation` 前一行结束。

- [ ] **Step 1: 建 `histogram_views.py`（机械搬运，不改一个字符）**

先写文件头：

```python
"""单文件直方图端点（从 analysis_views 拆出，绕开 600 行上限）。

与 FileCorrelationActions 同款 mixin 约定：路由、权限声明与 OpenAPI 分组不变。
方法体逐行照搬，未改语义。
"""

from rest_framework.decorators import action
from rest_framework.response import Response

from apps.analysis.services.statistics import (
    compute_range_statistics, detect_fail_data, ensure_numeric,
    filter_bin1_rows, filter_finite, get_bin_column_name, get_site_column,
    get_columns_with_limits, resolve_spec_limits, safe_gap,
)
from apps.analysis.services.data_services import compute_histogram_stats
from apps.common.params import get_param, get_param_bool, get_param_float

from ._helpers import (
    _load_df_from_request, clean_data, require_param,
    _filter_blank_params, _sanitize_numeric_params,
)


class HistogramActions:
```

再追加方法体（缩进本就是 4 空格，正好落在 `class` 内）：

```bash
sed -n '<HIST_A>,<HIST_B>p' apps/analysis/views/analysis_views.py >> apps/analysis/views/histogram_views.py
```

- [ ] **Step 2: 建 `multi_lot_views.py`**

同样先写文件头（docstring 改成"多文件分布对比端点"，类名 `MultiLotActions`，import 区先按下面起步，Step 4 再裁剪）：

```python
"""多文件分布对比端点（从 analysis_views 拆出）。

与 FileCorrelationActions 同款 mixin 约定：路由、权限声明与 OpenAPI 分组不变。
方法体逐行照搬，未改语义。
"""

from rest_framework.decorators import action
from rest_framework.response import Response

from apps.analysis.services.data_services import (
    compute_multi_lot_distribution, compute_common_params,
)
from apps.common.params import get_param, get_param_bool, get_param_list

from ._helpers import (
    _load_files_from_request, clean_data, _filter_blank_params,
    _sanitize_numeric_params,
)


class MultiLotActions:
```

追加方法体：

```bash
sed -n '<ML_A>,<ML_B>p' apps/analysis/views/analysis_views.py >> apps/analysis/views/multi_lot_views.py
```

- [ ] **Step 3: 原文件接上 mixin**

Modify `apps/analysis/views/analysis_views.py`：
- 删除 Step 0 算出的两个方法区间——**先删靠后的 `<ML_A>-<ML_B>`，再删靠前的 `<HIST_A>-<HIST_B>`**（反序删除才不会让第二次删除用错行号）
- import 区补 `from .histogram_views import HistogramActions` 与 `from .multi_lot_views import MultiLotActions`
- 类声明改为

```python
class AnalysisViewSet(FileCorrelationActions, HistogramActions, MultiLotActions,
                      viewsets.GenericViewSet):
```
（各 mixin 方法名互不重叠，MRO 无遮蔽风险；`urls.py` 仍注册 `AnalysisViewSet`，故路由不变。）

- [ ] **Step 4: 裁剪三个文件的 import 并用 pyflakes 验证**

搬完后 `analysis_views.py` 顶部会残留只服务于已搬走方法的 import；两个新文件也可能多引。逐个裁剪：

```bash
.venv/Scripts/python.exe -m pyflakes apps/analysis/views/analysis_views.py \
    apps/analysis/views/histogram_views.py apps/analysis/views/multi_lot_views.py
```
Expected: **无输出**。
- `undefined name` → 新文件漏了某个 import，补上；
- `imported but unused` → 删掉该行。

若环境无 pyflakes，用等价检查（只报未使用与未定义，不改动文件）：

```bash
.venv/Scripts/python.exe -c "
import ast, sys
for f in ['apps/analysis/views/analysis_views.py','apps/analysis/views/histogram_views.py','apps/analysis/views/multi_lot_views.py']:
    src = open(f, encoding='utf-8').read(); tree = ast.parse(src)
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            imported |= {(a.asname or a.name).split('.')[0] for a in n.names}
        elif isinstance(n, ast.Import):
            imported |= {(a.asname or a.name).split('.')[0] for a in n.names}
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    used |= {n.value.id for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
    print(f, 'unused:', sorted(imported - used))
"
```
Expected: 三行 `unused: []`（或对 `analysis_views.py` 列出的项逐条删掉后再跑一次）。

- [ ] **Step 5: 验证路由与响应未变**

Run: `.venv/Scripts/python.exe manage.py test apps.analysis 2>&1 | tail -4`
Expected: `OK`
Run: `.venv/Scripts/python.exe manage.py show_urls 2>/dev/null | grep analysis || .venv/Scripts/python.exe -c "
import os,django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.development');django.setup()
from apps.analysis.urls import urlpatterns
print(sorted(str(u.pattern) for u in urlpatterns))"`
Expected: URL 列表与拆分前**完全一致**（`histogram/`、`multi_lot/` 仍在 `analysis` 前缀下）

Run: `.venv/Scripts/python.exe manage.py test 2>&1 | tail -4`
Expected: `OK`
Run: `cd frontend && npx playwright test e2e/analysis/analysis-histogram.spec.ts e2e/analysis --project=P1 2>&1 | tail -8`
Expected: 全绿（至少覆盖 histogram 与 multi_lot 两个页面的 e2e 各跑通一次）
Run: `wc -l apps/analysis/views/*.py`
Expected: `analysis_views.py` < 600（约 360），两个新文件各 <200。全部合规。

- [ ] **Step 6: 提交**

```bash
git add apps/analysis/views/
git commit -m "$(cat <<'EOF'
refactor(analysis): 拆出 histogram / multi_lot 端点族

analysis_views.py 689 行超项目 600 行硬规则。沿用仓内既有的
FileCorrelationActions mixin 约定拆成 HistogramActions 与
MultiLotActions 两个文件，AnalysisViewSet 多重继承合入：路由、权限声明
与 OpenAPI 分组均不变（show_urls 前后一致）。

方法体逐行照搬未改语义；先做的 require_param 抽取让公共守卫不随拆分复制。
EOF
)"
```

---

## Task B6: 裁剪统计单一来源 + CL 判据对齐（决策 D3）

**Files:**
- Modify: `apps/analysis/services/statistics/filters.py`（新增 `iqr_filtered_stats`，改 `_display_cpk`）
- Modify: `apps/analysis/services/data_services/histogram.py:112-139`（改用 `iqr_filtered_stats`）
- Modify: `apps/analysis/services/statistics/limits.py`（新增 `has_custom_limits`）+ 6 处调用点

**为什么 D3 选"立即抽"**：`filters.py:90-105` 的注释自认 "mirrors histogram.py"，两份手抄一旦漂移，同一页面上的「低 CPK 筛选」与统计卡数值就会自相矛盾；且这是纯计算、无对外契约影响。

- [ ] **Step 1: 新增 `iqr_filtered_stats`（放 `filters.py`，紧邻 `_display_cpk`）**

```python
def iqr_filtered_stats(series, outlier_info):
    """IQR 裁剪后子集的 (mean, std, min, max)；无有效子集返回 None。

    守卫链是口径的一部分，必须同源：有异常值 且 normal_count>1 → 取边界内子集
    → 子集 >1 个 → std>0（std 用 ddof=0，与 histogram 卡片一致）。
    此前 histogram 与 filters 各手抄一份这套守卫（filters 注释自称 "mirrors
    histogram.py"），漂移会让同页面的「低 CPK 筛选」与统计卡自相矛盾。
    """
    if not (outlier_info['has_outliers'] and outlier_info['normal_count'] > 1):
        return None
    normal = series[(series >= outlier_info['lower_bound']) &
                    (series <= outlier_info['upper_bound'])]
    if len(normal) < 2:
        return None
    std = float(normal.std(ddof=0))
    if std <= 0:
        return None
    return (float(normal.mean()), std, float(normal.min()), float(normal.max()))
```

- [ ] **Step 2: 补两个消费文件的 import（新函数跨文件可见）**

- `apps/analysis/services/statistics/filters.py`：`iqr_filtered_stats` 定义在本文件内（Step 1），`_display_cpk` 同文件直接调用，**无需新增 import**。
- `apps/analysis/services/data_services/histogram.py`：顶部 import 区补

```python
from apps.analysis.services.statistics.filters import iqr_filtered_stats
```

若该文件已有 `from apps.analysis.services.statistics import (...)` 块，则把 `iqr_filtered_stats` 加进该块（并在 `statistics/__init__.py` 的 import 与 `__all__` 各补一行 `iqr_filtered_stats,` / `'iqr_filtered_stats',`），二选一，不要同时存在两条来源。

Run: `.venv/Scripts/python.exe -c "
import os,django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.development');django.setup()
from apps.analysis.services.statistics import iqr_filtered_stats
from apps.analysis.services.data_services import compute_histogram_stats
print('imports ok')"`
Expected: `imports ok`（无 ImportError / AttributeError）

- [ ] **Step 3: `_display_cpk` 改用它**

`filters.py:90-105` 替换为：

```python
    fs = iqr_filtered_stats(series, outlier_info)
    if fs:
        cpk = compute_cpk(fs[0], fs[1], rdl[0], rdl[1])['cpk']
    return cpk
```

- [ ] **Step 4: histogram 改用它**

`histogram.py:112-139` 的裁剪块替换为（保留其独有的 min/max 与 σ 带输出，round 仍在输出侧做）：

```python
    fs = iqr_filtered_stats(data_series, outlier_info)
    if fs:
        filtered_mean, filtered_std, filtered_data_min, filtered_data_max = (
            round(fs[0], 6), round(fs[1], 6), round(fs[2], 6), round(fs[3], 6))
        filtered_sigma3_min = round(filtered_mean - 3 * filtered_std, 6)
        filtered_sigma3_max = round(filtered_mean + 3 * filtered_std, 6)
        filtered_sigma4_min = round(filtered_mean - 4 * filtered_std, 6)
        filtered_sigma4_max = round(filtered_mean + 4 * filtered_std, 6)
        filtered_sigma6_min = round(filtered_mean - 6 * filtered_std, 6)
        filtered_sigma6_max = round(filtered_mean + 6 * filtered_std, 6)
        filtered_normal_curve = None  # 需 bin_min/bin_max，响应前计算
        filtered_cpk_result = compute_cpk(
            filtered_mean, filtered_std, stats['rdl'][0], stats['rdl'][1])
        filtered_cpk = round(filtered_cpk_result['cpk'], 4)
        filtered_cpk_level = filtered_cpk_result['cpk_level']
        filtered_cpk_color = filtered_cpk_result['cpk_color']
```

**等价性要点**：原代码用 `len(normal_data) > 1` 与 `if filtered_std > 0`，helper 的 `len < 2` 与 `std <= 0` 是同一判据的反面；原 `normal_data` 还供 min/max 使用，helper 已一并返回，无二次取子集。

Run: `.venv/Scripts/python.exe manage.py test apps.analysis test.backend.test_spec_limits_and_correlation 2>&1 | tail -4`
Expected: `OK`
Run（口径对拍）: `.venv/Scripts/python.exe manage.py test apps.analysis --verbosity 2 2>&1 | grep -ci "cpk\|outlier"`
Expected: 数字 >0，确认 CPK/异常值相关用例真的跑到了（别在零覆盖上宣布等价）

- [ ] **Step 5: `has_custom_limits` 判据单源**

`apps/analysis/services/statistics/limits.py` 新增：

```python
def has_custom_limits(range_type, custom_low, custom_high) -> bool:
    """CL 模式是否给出了完整的自定义上下限。

    六个端点的 CL 语义必须同一判据（R3①）：单边缺失时不能只信一侧，
    否则同一 range_type='CL' 在不同端点会落到不同的限值来源。
    """
    return range_type == 'CL' and custom_low is not None and custom_high is not None
```

替换 6 处完整判据（**保留各处返回值的差异**）：
- `histogram.py:90`、`histogram.py:162`
- `multi_lot.py:98`、`multi_lot.py:190`
- `serial_distribution.py:184`
- `statistics_views.py:133`

`histogram.py:313-314` 的两个 `custom_low is not None` / `custom_high is not None` 是**逐侧回填响应字段**、不是完整判据，**不改**。
`analysis_views.py:180` 的 `low > high` 额外校验属行为增强，按 spec 保持在其原位（不下沉，留 TODO 注释说明"是否推广到全部 CL 端点待产品确认"）。

在 `statistics/__init__.py` 的 import 与 `__all__` 补 `has_custom_limits`。

Run: `grep -rn "range_type == 'CL' and custom_low is not None" apps/analysis/`
Expected: 无输出（`histogram.py:313-314` 是 `range_type == 'CL' and custom_low is not None else None` 形式，若命中请确认是逐侧回填那一处，允许保留）

- [ ] **Step 6: 全量 + 提交**

Run: `.venv/Scripts/python.exe manage.py test 2>&1 | tail -4`
Expected: `OK`

```bash
git add apps/analysis/services/ apps/analysis/views/statistics_views.py
git commit -m "$(cat <<'EOF'
refactor(analysis): IQR 裁剪统计与 CL 自定义限判据单源

filters._display_cpk 此前手抄 histogram 的裁剪守卫链（注释自认 mirrors），
漂移会让同一页面的「低 CPK 筛选」与统计卡数值矛盾 —— 抽 iqr_filtered_stats
返回裁剪后的 mean/std/min/max 供两侧共用。

CL 完整判据（range_type=='CL' 且双侧非空）在 6 处各写一遍，抽
has_custom_limits；各站点的返回值差异保持不动，histogram 的逐侧响应回填
与 analysis_views 的 low>high 校验属不同语义，未强行合一。
EOF
)"
```

---

## Task B7: 文档级修正（按 F2 撤销代码收敛）+ gage 死 import

**Files:**
- Modify: `apps/common/file_loading.py:1-6`（docstring 事实修正）
- Modify: `apps/dashboard/views.py:246`（保留说明注释）
- Modify: `apps/dashboard/views.py:74-79`（决策 D2 的交叉引用注释）
- Modify: `apps/common/constants.py`（目录准入约定）
- Modify: `apps/gage/views.py:10,12`（删 2 个死 import）

**为什么本 Task 没有代码收敛**：见 §「计划阶段对 spec 的修正」F2。7 处内联复制里没有一处能被现有 helper 等价且更省地替换——5 处是批量循环 `continue` 形状（抛出式 helper 省不下行数，且 `get_object_or_404` 的 404 必须保留给越权访问），1 处错误码/状态码不同（`browse_views`），1 处会引入额外查询（`dashboard`）。因此 P2-1 降级为**把事实写清楚**，防止后人反复评估同一件事。

- [ ] **Step 1: 修正 `common/file_loading.py` 的失真 docstring**

`apps/common/file_loading.py:1-6` 替换为：

```python
"""用户文件加载 helper（抛出式）。

现状：唯一消费者是 ``apps/export/views.py``。其余视图里的加载代码**不是**
漏收敛，而是语义确实不同，已逐处评估（2026-09-12 后端重复冗余审计）：

- ``analysis/views/_helpers.py`` 的 ``_load_df_from_request`` 会去重重名列，
  并把"磁盘缺失/解析失败"合成单一 code ``file_not_found_or_parse_failed``；
- ``browse_views.py`` 用 ``'File not found on disk'`` + 404；
- ``dashboard/views.py`` 用 200 状态返回 ``'file_not_found'``/``'parse_failed'``，
  且其 datafile 在上游已由 ``file_id`` 缺失时的 ``.first()`` 回退分支解析好，
  改用本 helper 会多一次 ``get_object_or_404``；
- ``buyoff`` / ``gage`` / ``batch_report`` 是 ``for fid in file_ids`` 里的
  ``if df is None: continue`` 形状（抛出式改写省不下行数，且越权访问必须
  继续由 ``get_object_or_404`` 返回 404）。

统一这些 error code / 状态码属前后端契约变更，本模块不承担（设计文档决策 D1）。
"""
```

- [ ] **Step 2: 在被评估后保留的站点留一行指路注释**

`apps/dashboard/views.py` 的 `file_path = resolve_file_path(datafile.file_path)`（:246）之前插入：

```python
            # 刻意不调 common.file_loading.load_user_file：本视图的 datafile 已由
            # 上面的 .first() 回退分支解析好，再走 helper 会重复一次 get_object_or_404，
            # 且必须保持"错误也返回 200 + code"的既有契约。理由全见该模块 docstring。
```

- [ ] **Step 3: 决策 D2 的口径分叉留痕（补 spec P2-4）**

`apps/dashboard/views.py:74-79` 的 `_has_valid_limit` 上方补注释（**不改其判定集合**）：

```python
    # ⚠️ 与 analysis 侧的限值占位符口径**有意不同**，勿"顺手统一"：
    # 这里只把 ''/nan/none/n/a 视为无效，故字面 'Min'/'Max' 在本页算「有规格限」；
    # apps/analysis/services/statistics/limits.py 的 resolve_spec_limit 用
    # NON_NUMERIC_KEYWORDS（排除 min/max/...），故同一文件在两页的
    # "有规格限参数个数"天然不同。哪个是权威口径待产品定夺后再统一（改这里会动
    # dashboard 卡片数字并可能破 e2e 断言）—— 设计文档决策 D2。
```

Run: `grep -n "NON_NUMERIC_KEYWORDS" apps/dashboard/views.py`
Expected: 无输出（确认 dashboard 确实没用共享集合，注释描述属实）

- [ ] **Step 4: `apps/common/` 准入约定（补 spec P2-6）**

`apps/common/constants.py` 文件头 docstring（若无则新建）写明准入规则：

```python
"""跨 app 共享常量。

准入约定：只有**≥2 个 app** 消费的常量才放这里，单 app 专用值留在其自身模块内
（否则 ``common/`` 会持续积累"看起来公共、其实一处用"的错位工具——
审计发现 ``common/params.py`` 实际仅 analysis 使用）。
"""
```

- [ ] **Step 5: gage 死 import**

Run: `for s in get_parser save_excelize; do echo "$s: $(grep -cE "\b$s\b" apps/gage/views.py)"; done`
Expected: 各 `1`（即只有 import 行本身）
删 `apps/gage/views.py:10`（`from apps.datafiles.parsers import get_parser`）与 `:12`（`from apps.export.excelize_helpers import save_excelize`）两行。

Run: `.venv/Scripts/python.exe manage.py test apps.gage test.backend.test_gage_builder 2>&1 | tail -4`
Expected: `OK`

- [ ] **Step 6: 全量回归 + 提交**

Run: `.venv/Scripts/python.exe manage.py test 2>&1 | tail -4`
Expected: `OK`，用例数与基线一致（本 Task 无行为改动，任何失败都属意外）

```bash
git add apps/common/file_loading.py apps/common/constants.py apps/dashboard/views.py apps/gage/views.py
git commit -m "$(cat <<'EOF'
docs(common): 记录文件加载 helper 的真实消费面与不可统一原因

file_loading docstring 原声称覆盖 export/dashboard/analysis/buyoff/gage/
batch_report 七处，实际只有 export 一处。逐处评估后确认其余不是技术债：
批量循环 continue 形状、error code 与状态码各不相同、dashboard 复用还会多
一次查询 —— 统一契约属功能变更（决策 D1），本轮不做。

顺带留痕 dashboard 与 analysis 的限值占位符口径差异（决策 D2，待产品定夺），
并给 common/ 加"≥2 消费者"准入约定；删 gage views 两个死 import。
EOF
)"
```

---

## Task B8: P1+P2 收尾验收

- [ ] **Step 1: DoD grep**

```bash
grep -rn "def get_bin_column_name" apps/datafiles/parsers/*.py | grep -v base.py   # 期望：无输出
grep -rn "mirrors histogram" apps/analysis/                                          # 期望：无输出
grep -c "range_type == 'CL'" apps/analysis/services/data_services/*.py               # 期望：仅 histogram 的逐侧回填
grep -n "excelize.Border(" apps/gage/gage_legacy_builder.py | wc -l                  # 期望：由 56 降到 <10
wc -l apps/gage/gage_legacy_builder.py apps/analysis/views/*.py                      # 期望：除 gage(另立项目) 外全部 <600
```

- [ ] **Step 2: 全量 + e2e + 端口**

Run: `.venv/Scripts/python.exe manage.py test 2>&1 | tail -4` → `OK`，用例数 ≥ 基线（B1 新增了样本指纹用例）
Run: `cd frontend && npm run test:e2e:quick 2>&1 | tail -15` → 0 failed
Run: `cd .. && netstat -ano | grep -E ":8000|:3000" | grep LISTEN` → 无输出

- [ ] **Step 3: todo.md 记账（含偏差说明）**

```markdown
## 2026-09-12 后端结构重复合并 P1+P2

- [x] B1 解析器家族参数化 + Bin 列单源（+ 四格式样本指纹门禁）
- [x] B2 SFTP 守卫抽取（落盘链按 F1 保持内联）
- [x] B3 Excel 样式/save_excelize 复用（样式指纹 diff=0）
- [x] B4 视图/服务层小重复 7 项
- [x] B5 analysis_views 拆分（689→<360，show_urls 前后一致）
- [x] B6 filtered 统计 + CL 判据单源（D3）
- [x] B7 file_loading docstring + dashboard 单点 + gage 死 import（F2 缩减）
- 与 spec 偏差：F1（SFTP ~55→~25 行）、F2（文件加载 ~50→~10 行，风险由高降低）、
  F3（export_ppt σ 带语义不同未并入）。净减总数低于 spec 估计，理由见计划内表格。
- 未做（另行立项）：gage_legacy_builder 600 行违规（D4）；dashboard/analysis
  限值占位符口径统一（D2）；error code 契约统一（D1）。
```

Run: `git add docs/tasks/todo.md && git commit -m "docs(tasks): P1+P2 结构合并验证账目"`

---

## 遗留（不在本计划）

| 项 | 归属决策 | 说明 |
|---|---|---|
| `gage_legacy_builder.py` ~770 行仍超 600 | D4 | 单函数 + 闭包捕获（`_set_cell`@:243、`_calc_d2`@:66），拆文件要先解作用域，另立项目 |
| dashboard 与 analysis 限值占位符口径不一致 | D2 | 改会让 dashboard「有规格限参数个数」变化并可能破 e2e 断言，需产品定权威口径 |
| 文件加载三套 error code 统一 | D1 | 属前后端契约变更 |
| `parse_limit_string` / `t_cdf` | — | 生产零调用但被测试当等价 oracle **有意** pin 住，非死代码 |
| openpyxl 与 excelize 双库并存 | 非目标 | `export_batch_charts_xlsx.py` 依赖 openpyxl 的 Image 嵌入 |
| `analysis_views.py:180` 的 `low > high` 校验是否推广到全部 CL 端点 | B6 留 TODO | 推广会新增 400 拒绝路径，属行为变更 |
