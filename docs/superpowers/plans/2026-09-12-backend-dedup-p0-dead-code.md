# 后端死代码清除（P0）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除后端约 700 行零引用死代码与陈旧分叉实现，不改变任何运行行为。

**Architecture:** 纯删除式重构。按"gage 死代码链 → 解析器分叉死方法 → 兼容 shim / 零星死代码 / 未使用 import"三批推进，每批一个 commit、独立可 revert。删除前先用现有测试锁定 live 路径（`test_gage_builder` 驱动唯一 live 的 gage builder），删除后以全量测试证明行为未变。

**Tech Stack:** Django 4 + DRF、pandas、pytest 风格的 Django TestCase/SimpleTestCase（`manage.py test`）、excelize。

**Spec:** `docs/superpowers/specs/2026-09-12-backend-dedup-cleanup-design.md` §3

---

## 铁律（每个 Task 都适用）

1. **删错方向的代价**：`apps/gage/gage_legacy_builder.py` 是 Gage 导出**唯一 live 实现**，`gage_summary_builder.py` / `services/rr_analysis.py` 才是死掉的参考实现。两者文件名互为镜像，动手前复述一遍这句话。
2. **不碰工作区里不属于本计划的文件**（`frontend/`、`docs/` 下的他人改动）。每个 commit 只 `git add` 本 Task 列出的路径。
3. **每批结束前**跑 `git status --short` + `git diff --stat` 确认没有意外文件被卷入（lessons R1）。
4. 命令一律在仓库根目录 `c:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase` 执行，Python 用 `.venv/Scripts/python.exe`。

---

## Task A0: 锁定测试基线

**Files:**
- Modify: `docs/tasks/todo.md`（追加基线条目，勿动他人条目）

- [ ] **Step 1: 跑全量测试拿真实基线**

Run:
```bash
mkdir -p tasks
.venv/Scripts/python.exe manage.py test > tasks/p0-baseline-test.log 2>&1; echo "exit=$?"
grep -nE "^(Ran |OK|FAILED|ERROR)" tasks/p0-baseline-test.log
```
Expected: `exit=0`，grep 出 `Ran NNN tests in M.MMs` + `OK`（可能带 `skipped=N`）。**记下这个 NNN**。

⚠️ **不要用 `manage.py test 2>&1 | tail -N` 取汇总行**（2026-09-13 实测踩坑）：stdout 在被 pipe 时是块缓冲，`Seed users completed.` 这类 stdout 行会在进程退出时才 flush，排到 stderr 的 `Ran/OK` **之后**，于是 `tail` 恰好把汇总行挤掉，看起来像"没有汇总 = 没跑完"。一律先重定向到日志文件再 grep。本计划后续所有 Task 的 `| tail -4` 只在"确认绿色"这种粗判场合可用；**凡是要读用例总数的步骤，都按上面的重定向方式取数**。

注意：不要用记忆里的数字（历史记录在 888 / 899 之间漂移过），本步的唯一目的就是拿到当前 HEAD 的真值。

- [ ] **Step 2: 记录基线到 todo.md**

在 `docs/tasks/todo.md` 末尾追加（保留原有全部内容，只追加）：

```markdown
## 2026-09-12 后端死代码清除 P0 — 基线

- L0 基线：`manage.py test` → `Ran <NNN> tests`，OK / skipped=<n>（串行）
- 工作树起点：`git rev-parse --short HEAD` = <hash>
```

Run: `git add docs/tasks/todo.md && git commit -m "docs(tasks): P0 死代码清除基线账目"`

- [ ] **Step 3: 确认 gage live 路径当前是绿的（后续删除的对照组）**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_gage_builder apps.gage 2>&1 | tail -4`
Expected: `OK`。若此处已红，**停止**并向用户报告——说明起点带病，不能把别人的失败算在本次删除账上。

---

## Task A1: 删除 gage 死代码链（commit 1，约 640 行）

**Files:**
- Delete: `apps/gage/gage_summary_builder.py`（363 行）
- Delete: `apps/gage/services/rr_analysis.py` + `apps/gage/services/__init__.py`（178 行）
- Delete: `apps/gage/gage_styles.py`（57 行）
- Delete: `apps/gage/excelize_layout.py`（32 行）
- Modify: `apps/gage/gage_legacy_builder.py:12-14`（改 import + 补 2 个常量）
- Modify: `apps/gage/views.py:53`（改 import 指向）

- [ ] **Step 1: 再确认一次"无人引用"（防工作树漂移）**

Run:
```bash
grep -rn "gage_summary_builder\|services.rr_analysis\|rr_analysis import\|excelize_layout import" --include="*.py" apps/ config/ test/ scripts/
```
Expected: **只**出现下面这些行（即本 Task 要删/改的位置），无任何 app 外的引用者：
- `apps/gage/excelize_layout.py:27` `from .gage_summary_builder import (`
- `apps/gage/views.py:53` `from apps.gage.excelize_layout import build_gage_summary_excel`
- `apps/gage/gage_summary_builder.py:16` `from apps.gage.services.rr_analysis import ...`

出现任何其它文件 → **停止**，那说明有引用没被审计发现，向用户报告后再定。

**Step 1b（实施时补的漏网之鱼）：还要 grep 非 `.py` 的构建配置。**

Run: `grep -rn "apps.gage.services\|gage_summary_builder\|rr_analysis\|gage_styles" --include="*.spec" --include="*.json" --include="*.yml" --include="*.yaml" --include="*.toml" --include="*.ini" --include="*.bat" . 2>/dev/null | grep -v node_modules`
Expected: 命中 `lq_dataprase.spec` 的 `'apps.gage.services'`（`hiddenimports` 列表）→ 一并删掉该条目。

2026-09-13 实测教训：本计划原版只 grep `*.py`，这条漏了，补成第 4 个 commit。**更糟的是它不报错**：
`git rm` 后磁盘上残留 `apps/gage/services/`（只剩 `__pycache__`），该空目录让这个名字以
namespace package 身份被 `find_spec` 命中，PyInstaller 的 "Hidden import not found" 分支因此
根本不会触发，悬空引用被静默吞掉。所以 Step 6 之后还要 `rm -rf apps/gage/services`
（确认里面只有 `__pycache__`：`find apps/gage/services -type f`）。

- [ ] **Step 2: 删三个死文件 + services 目录**

```bash
git rm apps/gage/gage_summary_builder.py
git rm apps/gage/services/rr_analysis.py apps/gage/services/__init__.py
```

- [ ] **Step 3: 把 gage_styles 的存活常量搬进 legacy，再删文件**

`gage_legacy_builder.py` 只消费 `gage_styles` 的 3 个常量（`NON_NUMERIC_KEYWORDS` 在 :47、`FILL_GRAY_HEX` 在 :654/:663、`FILL_LIGHT_BLUE_HEX` 在 :645），其余 7 个样式工厂 + `_set_cell` 只被 Step 2 删掉的死代码用。与其留一个"只剩常量"的文件，不如把常量并入唯一消费者。

Modify `apps/gage/gage_legacy_builder.py`，把 :12-14 三行 import：

```python
from apps.analysis.services.statistics import ensure_numeric
from apps.datafiles.parsers.base import SYSTEM_COLUMNS
from .gage_styles import NON_NUMERIC_KEYWORDS, FILL_GRAY_HEX, FILL_LIGHT_BLUE_HEX
```

替换为：

```python
from apps.analysis.services.statistics import ensure_numeric
from apps.common.constants import NON_NUMERIC_KEYWORDS
from apps.datafiles.parsers.base import SYSTEM_COLUMNS

FILL_GRAY_HEX = "E0E0E0"
FILL_LIGHT_BLUE_HEX = "D6EAF8"
```

（两个 HEX 常量值与原 `gage_styles.py:9-10` 一致，逐字符照搬；定义在模块级，函数体内 :645/:654/:663 的引用无需改动。）

Run: `git rm apps/gage/gage_styles.py`

- [ ] **Step 4: 让 views 直连 live builder，删掉纯转发层**

Modify `apps/gage/views.py:53`：

```python
        from apps.gage.excelize_layout import build_gage_summary_excel
```
→
```python
        from apps.gage.gage_legacy_builder import build_gage_summary_excel
```

Run: `git rm apps/gage/excelize_layout.py`

- [ ] **Step 5: 确认 `views.py` 顶部两个死 import 不被本次改动波及**

`apps/gage/views.py:10` 的 `get_parser` 与 `:12` 的 `save_excelize` 是**本 Task 之前就存在**的未使用 import（2026-09-13 复核：在 `views.py` 内各仅出现 1 次 = 只有 import 行）。本 Task 不处理它们（A3 只清 analysis 两个 views 的 import；这两个由 **Plan B Task B7** 收），避免一个 commit 混两件事。

**不得顺手删**同行区的 `:9 DataFile` 与 `:11 get_cached_parsed_file`：复核确认它们在 `views.py:31` / `:32` 有实际使用，是 live 的。

- [ ] **Step 6: 导入完整性检查（最快证伪方式）**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_gage_builder -v 1 2>&1 | tail -4`
Expected: `OK`，**11** 个用例（实测；计划原稿误写 12。`test_main_known_values` 等，见 `test/backend/test_gage_builder.py:91-259`；连同 `apps/gage/tests.py` 的 2 例共 **13** —— A0 Step 3 的对照组数就是 13）。若报 `ModuleNotFoundError: apps.gage.gage_styles` 之类 → Step 3 漏了某个常量。

Run: `.venv/Scripts/python.exe manage.py test apps.gage apps.export 2>&1 | tail -4`
Expected: `OK`

- [ ] **Step 7: 全量回归 + 提交**

Run: `.venv/Scripts/python.exe manage.py test 2>&1 | tail -4`
Expected: `Ran <NNN - k> tests`（k 为随死文件一起消失的用例数，审计为 0，故应与 A0 Step 1 的 NNN 相同），`OK`

```bash
git add apps/gage/
git status --short
git commit -m "$(cat <<'EOF'
refactor(gage): 删除 gage 死代码链

gage_summary_builder / services.rr_analysis 两个模块头部已自述 DEAD CODE，
唯一 live 路径是 gage_legacy_builder.build_gage_summary_excel（views.py →
excelize_layout re-export）。随其 re-export 层与仅服务于死代码的样式工厂
一并移除，常量并入唯一消费者。

净删约 640 行，导出行为不变（test_gage_builder 12 例 + 全量回归绿）。
EOF
)"
```

---

## Task A2: 删除解析器里修复前的陈旧分叉（commit 2，52 行 + 4 行 import）

**Files:**
- Modify: `apps/datafiles/parsers/base.py:1-11`（删失效 import）
- Modify: `apps/datafiles/parsers/base.py:20-70`（删两个方法）

**为什么必须删（不是"等价重复"）**：这两个方法是 `apps/analysis/services/statistics/limits.py:19-40 / :104-165` 的**修复前版本**，保留三处已修缺陷：

| | `base.py`（死） | `limits.py`（live） |
|---|---|---|
| bin 为 NaN 的行 | `:48` `!= 1` → 判为 FAIL | `:116-120` `notna() & (!=1)`，2026-09-05 审查 L3 |
| 限值为字面 `'Min'/'Max'` | `:50-51` 裸 `float()` → `ValueError` → 500 | `:128-140` `resolve_spec_limit` + None 守卫 |
| 10 万行全 fail | `:68` 每行重建 `set()` → O(n²) | `:153-162` 集合复用 |

任何人 `parser.detect_fail_data(...)` 就会同时复活这三个 bug。

- [ ] **Step 1: 确认零调用者（含动态调用）**

Run:
```bash
grep -rn "detect_fail_data\|get_columns_with_limits" --include="*.py" apps/ config/ test/ scripts/ | grep -E "self\.|parser\.|get_parser\("
```
Expected: 只有 `apps/datafiles/parsers/base.py:45`（被删方法之间的内部自调）。

判读口径（2026-09-13 复核）：**要判的是"没有方法绑定调用者"，不是"符号名在仓库里不出现"**。`detect_fail_data` / `get_columns_with_limits` 这两个名字在全仓另有约 40 处出现，但它们 import 的是 `apps.analysis.services.statistics.limits` 里的同名 live 实现（如 `apps/analysis/views/analysis_views.py:28`、`statistics_views.py:15,25`、`apps/dashboard/views.py:18`、`apps/datafiles/services.py:11`），与本 Task 要删的两个方法无关，**不是**Stop 条件。`grep self.` / `parser.` / `get_parser(` 已把它们滤掉。

Run: `grep -rn "getattr(.*parser\|importlib" --include="*.py" apps/ | grep -i "fail\|limits"`
Expected: 无输出（排除动态派发的可能）。复核补充：`apps/` 内 `importlib` 零命中；`getattr(` 21 处全是 settings / user / paramiko / 测试 patch 目标，无一派发 parser 方法；`parsers/__init__.py:1-4` 是静态映射表。

- [ ] **Step 2: 删除两个方法**

删除 `apps/datafiles/parsers/base.py` 的第 20-70 行，即从

```python
    def get_columns_with_limits(self, df: pd.DataFrame, metadata: Dict) -> List[str]:
```

到 `detect_fail_data` 的结束行

```python
        return fail_indices, fail_columns, fail_cells
    
```

删完后 `parse` 抽象方法（:16-18）的下一个成员应直接是 `@staticmethod` + `def make_column_names_unique`（原 :72-73）。

- [ ] **Step 3: 清掉因此失效的 import**

Run: `grep -nE "\bnp\.|\blogger\.|NON_NUMERIC_KEYWORDS|\bPath\b" apps/datafiles/parsers/base.py`
Expected: 无输出 → 这 4 个符号在文件内已无消费者。

复核补充（判读口径，2026-09-13）：删 20-70 后各符号的真实状态是 `Path` 仅 `:2`、`np` 仅 `:5`、`NON_NUMERIC_KEYWORDS` 的 import 在 `:11` 而唯一使用点 `:29` 落在被删区间内 → 三者都变成"只剩 import"，必须一起删。`logger` 则是**本 Task 之前就已经**只出现在 `:9` 的 `logger = logging.getLogger(__name__)` 自身赋值行（全文件无 `logger.` 使用），所以上面这条 grep 在删除前后都是空——它证明的是 `np` / `Path` / `NON_NUMERIC_KEYWORDS`，不证明 `logger`。`logger` + `import logging` 一并删属于"顺带清除既有死变量"，commit message 不需为它单列。

Modify `apps/datafiles/parsers/base.py:1-11`，把

```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple, Dict, List
import pandas as pd
import numpy as np
import re
import logging

logger = logging.getLogger(__name__)

from apps.common.constants import NON_NUMERIC_KEYWORDS
```

替换为

```python
from abc import ABC, abstractmethod
from typing import Optional, Tuple, Dict, List
import pandas as pd
import re
```

（`List`/`Dict` 仍被 `make_column_names_unique:73` 与 `extract_header_metadata:145` 用；`Optional`/`Tuple` 被 `parse:17` 用；`re` 被 `TAIL_META_PATTERN`/`extract_header_metadata` 用；`pd` 被 `drop_tail_metadata_rows` 用。）

- [ ] **Step 4: 回归**

Run: `.venv/Scripts/python.exe manage.py test apps.datafiles apps.analysis apps.export test.backend.test_spec_limits_and_correlation 2>&1 | tail -4`
Expected: `OK`

Run: `.venv/Scripts/python.exe manage.py test 2>&1 | tail -4`
Expected: `Ran <与 A0 相同的 NNN> tests`，`OK`

- [ ] **Step 5: 提交**

```bash
git add apps/datafiles/parsers/base.py
git commit -m "$(cat <<'EOF'
refactor(parsers): 删除 base.py 里修复前的 fail 判定分叉

get_columns_with_limits / detect_fail_data 全仓零调用者（唯一引用是同文件
自调），且是 analysis/services/statistics/limits.py 同名实现的修复前版本，
保留三处已修缺陷：bin=NaN 误判 FAIL、裸 float() 遇字面 'Min'/'Max' 抛
ValueError 致 500、每行重建 set 的 O(n²) 去重。

留着会被误用而复活这三个 bug，删除即收敛为单一事实源。
EOF
)"
```

---

## Task A3: 兼容 shim + 零星死代码 + 未使用 import（commit 3，约 66 行）

**Files:**
- Modify: `apps/export/charts.py:32-45`（删 shim）
- Modify: `apps/export/tests.py:474-494`（删 pin 它的测试类）
- Modify: `test/backend/test_export_histogram_grid.py:26,171-181,280-295,224`
- Modify: `apps/export/histogram_grid.py:8`（文档提及改名）
- Modify: `apps/analysis/services/statistics/helpers.py:104-107` + `statistics/__init__.py:23,95`
- Modify: `apps/datafiles/serializers.py:146-148`
- Modify: `apps/datafiles/views/_helpers.py:163-171` + `views/__init__.py:14` + `views/file_views.py:33`
- Modify: `apps/export/excelize_helpers.py:12`、`apps/gage/gage_legacy_builder.py:83`
- Modify: `apps/analysis/views/analysis_views.py`、`statistics_views.py`（未使用 import）

- [ ] **Step 1: 删 `charts.build_histogram_bins` shim**

删除 `apps/export/charts.py` 第 32-45 行整段（`def build_histogram_bins(...)` 到 `return bins, data_gap`，含其 docstring）。删后 `_get_export_dpi`（:26-29）之后直接是 `def _render_histogram_payload(`（原 :48）。

- [ ] **Step 2: 删掉 `apps/export/tests.py` 里 pin 它的测试类**

删除 `apps/export/tests.py` 第 474-494 行（`class BuildHistogramBinsTests(SimpleTestCase):` 到文件末尾，含两个方法）。

**为什么是删而不是改写**：该类的两条事实早已被别处钉住，再指向新实现只会造出重复用例（违反 DRY）。2026-09-13 复核后的**准确**出处是：`gap = 范围/20` 由 `test/backend/test_export_histogram_grid.py:92`（`GridMatchesScreenTests.test_bin_width_equals_gap`，`assertAlmostEqual(self.gap, 1.0)` 且行尾注释 `# (20-0)/20`）钉；"26 个 bin 中心 + 首中心不再是旧平移值"由本 Task Step 3d 替换后的 `GridGeometryTests` 继续钉（原 `:292-295` 属于将被整类替换的 `LegacyBinsShimTests`，`:291` 是空行——**不要**再引用它当作既有出处）。

Run: `.venv/Scripts/python.exe manage.py test apps.export 2>&1 | tail -4`
Expected: `OK`

- [ ] **Step 3: 让 `test_export_histogram_grid.py` 脱离 shim（保留其回归价值）**

该文件对 shim 的依赖共 **5 处**：模块级 import `:26`、调用 `:177`、调用 `:287`（在将被整类替换的 `LegacyBinsShimTests` 内）、文档提及 `:224` 与 `:281`。旧几何只是纯算术，把公式就近放进测试文件即可继续钉住"旧网格会丢光 8 个点"这一前置事实，无需在生产代码里留死函数。

⚠️ **`:26` 是模块级 import，最容易出事**：shim 删掉后若这行没同步改，`test_export_histogram_grid.py` 整个文件 import 失败 → 连 `GridMatchesScreenTests`（钉住**新**几何 26 中心 / gap=范围÷20 的那批用例）一起静默消失，而 `manage.py test` 的总数只少几个用例，看上去像"删了 shim 的正常结果"。**所以 Step 5 必须核对用例总数只比基线少 2**，不能只看 `OK`。

3a. Modify 第 26 行，删掉 `build_histogram_bins`：

```python
from apps.export.charts import _render_histogram_payload, build_histogram_bins
```
→
```python
from apps.export.charts import _render_histogram_payload
```

3b. 在 `TEMP = np.array([...])`（第 28 行）之后插入模块级 helper：

```python
def _legacy_bins_geometry(low, high):
    """已删除的 charts.build_histogram_bins 旧几何（26 条有限边界、两端外扩
    2.5·gap、无 ±inf 兜底）。留在测试里只为复现"旧网格把点全丢了"的前置事实，
    防止相关用例因两侧都修好而空转。
    """
    data_gap = (high - low) / 20 if (high - low) > 0 else 1.0
    bin_start = low - 2.5 * data_gap
    return np.array([bin_start + j * data_gap for j in range(26)]), data_gap
```

3c. Modify `test_precondition_legacy_grid_captures_nothing`（方法 `:172-181`，调用行 `:177`）：

```python
        legacy_bins, legacy_gap = build_histogram_bins(0.0, 0.0)
```
→
```python
        legacy_bins, legacy_gap = _legacy_bins_geometry(0.0, 0.0)
```

3d. 把 `LegacyBinsShimTests`（`:280-295`，它是文件最后一个类、`:295` 即 EOF）整类替换为不依赖 shim 的版本（保留"两侧几何不再平移 0.5·gap"这一断言，去掉对已删函数的依赖）。该类自带 shim 的**第二处调用 `:287`** 与 **docstring 提及 `:281`**，整类替换后二者一并消失——替换完再 grep 一次 `build_histogram_bins`，此文件内应只剩 Step 3b helper 的 docstring。

⚠️ **替换类必须仍是 2 个用例**（实施时发现的计划缺陷）：`LegacyBinsShimTests` 有 2 个方法，而下面这段只有 1 个，照抄会让全量数变 916、破掉 Step 8 的 917 门禁（本 Task 只该少 `BuildHistogramBinsTests` 的 2 例）。实际提交保留两条：下面这条 `test_grid_geometry_matches_screen_side` 原样，外加一条用 Step 3b helper 钉住旧几何自身（26 条边界 / `bins[0]=7.5` / `bins[-1]=32.5`）的 `test_legacy_geometry_stays_the_buggy_reference`——后者正是 helper 存在的理由，也顺带承接了随 `BuildHistogramBinsTests` 一起消失的末边界 pin：

```python
class GridGeometryTests(SimpleTestCase):
    """导出网格几何：25 内边界 + ±inf = 26 bin，且不得回到旧几何的平移起点。

    旧 shim charts.build_histogram_bins 已删除；其几何（首中心 7.5 = 10 - 2.5·gap
    + 0.5·gap）与屏幕侧平移 0.5·gap，正是缺陷 #4/#5 的根因，这里把"不再如此"钉住。
    """

    def test_grid_geometry_matches_screen_side(self):
        _, centers, gap = build_histogram_grid(10.0, 30.0)
        self.assertEqual(len(centers), 26)
        self.assertAlmostEqual(gap, 1.0, places=9)
        self.assertNotAlmostEqual(centers[0], 7.5, places=9)
```

3e. Modify 第 224 行 `PptxPhantomLimitTests` docstring 里的 ``build_histogram_bins(0.0, 0.0)`` → ``旧几何（``_legacy_bins_geometry``）``，使全文不再出现已删符号。

- [ ] **Step 4: 更新 `histogram_grid.py` 的历史提及**

Modify `apps/export/histogram_grid.py:8`，把

```
* 网格构造此前在 ``charts.build_histogram_bins`` 里另算一套（26 条有限边界、
```
→
```
* 网格构造此前在 charts 里另算一套 shim（26 条有限边界、
```

- [ ] **Step 5: 验证 shim 已彻底消失**

Run: `.venv/Scripts/python.exe manage.py test test.backend.test_export_histogram_grid apps.export 2>&1 | tail -4`
Expected: `OK`

Run: `grep -rn "build_histogram_bins" --include="*.py" apps/ test/`
Expected: 只命中 `test/backend/test_export_histogram_grid.py` 里 helper 的 docstring 与类注释（提及历史），无任何 import 或调用。

- [ ] **Step 6: 零星死代码四连删**

6a. `apps/analysis/services/statistics/helpers.py`：删 `:104-107`

```python
def get_1d(series_or_df):
    if isinstance(series_or_df, pd.DataFrame):
        return series_or_df.iloc[:, 0]
    return series_or_df
```

同步删 `apps/analysis/services/statistics/__init__.py:23` 的 `    get_1d,` 与 `:95` 的 `    'get_1d',`（**保留 `get_1d_from`，它才是 live 的那个**）。

6b. `apps/datafiles/serializers.py`：删 `:146-148`（含前面的空行分隔）

```python
class FileUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
```

6c. `apps/datafiles/views/_helpers.py`：删 `:163-171` 的 `def _disk_mtime(file_path):` 整函数
（**勿动 `apps/datafiles/services.py:115` 的 `_disk_mtime_ns`，那是 live 的**）。
同步删 `apps/datafiles/views/__init__.py:14` 的 `    _disk_mtime,` 与 `apps/datafiles/views/file_views.py:33` 的 `    _disk_mtime,`。

Run: `grep -n "timezone" apps/datafiles/views/_helpers.py`
Expected: 仍有 `:11` import 与 `:183-185` 使用 → **保留** `from django.utils import timezone`。

6d. `apps/export/excelize_helpers.py:12` 与 `apps/gage/gage_legacy_builder.py:83`：各删一行 `COLOR_ALT_ROW = "EDF2F7"`

Run: `grep -rnE "COLOR_ALT_ROW|FileUploadSerializer|get_1d([^_]|$)" --include="*.py" apps/ config/ test/ scripts/`
Expected: 无输出。`get_1d` 用 `([^_]|$)` 排除 live 的 `get_1d_from`（`\b` 无法区分两者，故不用词边界）。

- [ ] **Step 7: 未使用 import（26 个符号）**

7a. `apps/analysis/views/analysis_views.py`：
- 删 `:8` `import os`
- 删 `:9` `from typing import Dict, Optional, Set`
- 删 statistics import 块内的 6 行：`:20 compute_correlation_matrix,`、`:21 compute_boxplot_stats,`、`:22 compute_range_statistics,`、`:23 compute_site_stats,`、`:34 ensure_numeric,`、`:38 compute_low_cpk_test_items,`

7b. `apps/analysis/views/statistics_views.py`：
- 删 `:3` `import os`
- 删 `:7` `from django.shortcuts import get_object_or_404`
- 删 `:13` `from apps.datafiles.models import DataFile`
- 删 `:42` `from apps.datafiles.services import get_cached_parsed_file`

**不得删**（易误判）：`apps/sftp/views.py:4,6` 的 `paramiko` / `status` —— `views.py:2-3` 注释明示它们是测试的 monkey-patch 目标（lessons R6③）。

Run（逐个确认删对了）:
```bash
for s in os Dict Optional Set compute_correlation_matrix compute_boxplot_stats compute_range_statistics compute_site_stats ensure_numeric compute_low_cpk_test_items; do printf "%s in analysis_views: " $s; grep -cE "\b$s\b" apps/analysis/views/analysis_views.py; done
```
Expected: 全部为 `0`

Run:
```bash
.venv/Scripts/python.exe manage.py test apps.analysis apps.datafiles apps.export apps.gage 2>&1 | tail -4
```
Expected: `OK`

- [ ] **Step 8: 全量回归**

Run: `.venv/Scripts/python.exe manage.py test 2>&1 | tail -4`
Expected: `Ran <NNN - 2> tests`（比基线少 2 = Step 2 删掉的 `BuildHistogramBinsTests` 两个用例），`OK`，零 failed / error。

若少掉的不是 2：说明还连带删了别的用例，`git diff --stat` 查测试文件改动量后修正。

- [ ] **Step 9: 提交**

```bash
git add apps/export/charts.py apps/export/tests.py apps/export/histogram_grid.py \
        test/backend/test_export_histogram_grid.py \
        apps/analysis/services/statistics/helpers.py apps/analysis/services/statistics/__init__.py \
        apps/analysis/views/analysis_views.py apps/analysis/views/statistics_views.py \
        apps/datafiles/serializers.py apps/datafiles/views/_helpers.py \
        apps/datafiles/views/__init__.py apps/datafiles/views/file_views.py \
        apps/export/excelize_helpers.py apps/gage/gage_legacy_builder.py
git status --short
git commit -m "$(cat <<'EOF'
chore: 清除零星死代码与未使用 import

- charts.build_histogram_bins 兼容 shim（自述 deprecated，生产已走
  build_histogram_grid）；其回归事实并入测试本地 helper，不重复 pin
- get_1d / FileUploadSerializer / _disk_mtime / COLOR_ALT_ROW 全仓零引用
- analysis 两个 views 的 10+ 处未使用 import

sftp/views.py 的 paramiko/status 按注释保留（monkey-patch 目标），未计入。
EOF
)"
```

---

## Task A4: 仓内遗留备份文件（需用户确认后执行）

**Files:**
- Delete（未跟踪）: `apps/gage/excelize_layout.py.bak`（18,438 B，2026-05-31）

- [ ] **Step 1: 确认它不是 git 跟踪文件（删了无法用 git 找回）**

Run: `git ls-files apps/gage/ | grep bak`
Expected: 无输出（说明未跟踪）。

- [ ] **Step 2: 向用户请求确认**

该文件不是本会话产生的，且删除不可用 git 恢复。**必须等用户明确同意**再删。可选两案，交用户选：
- (a) `rm apps/gage/excelize_layout.py.bak`
- (b) 移入 scratch 区保留：`mv apps/gage/excelize_layout.py.bak tasks/gage-excelize_layout.py.bak-20260531`

无同意则跳过本 Task（不阻塞 A0-A3 的交付）。

---

## Task A5: P0 收尾验收

- [ ] **Step 1: DoD grep（审计残留）**

Run:
```bash
grep -rn "gage_summary_builder\|rr_analysis\|build_histogram_bins\|FileUploadSerializer" --include="*.py" apps/ config/ test/ | grep -v "test_export_histogram_grid"
grep -rnE "_disk_mtime(?!_ns)" --include="*.py" apps/
```
Expected: 第一条无输出；第二条无输出（`_disk_mtime_ns` 不算）。

- [ ] **Step 2: 行数核对**

Run: `git diff --stat HEAD~3 HEAD | tail -3`
Expected: 删除行数 ≈ 700（A0 的基线 commit 不算入），新增行极少（测试本地 helper）。

- [ ] **Step 3: 全量 + 端口核查**

Run: `.venv/Scripts/python.exe manage.py test 2>&1 | tail -4`
Expected: `OK`
Run: `netstat -ano | grep -E ":8000|:3000" | grep LISTEN`
Expected: 无输出（CLAUDE.md 要求测试后释放端口）。

- [ ] **Step 4: 在 todo.md 记验证账目**

追加一段（格式对齐项目既有写法）：

```markdown
- [x] 验证：全量 `manage.py test` <NNN-2> OK（基线 <NNN>，差值=删掉的 shim 用例 2）；
      apps.gage / apps.datafiles / apps.export / apps.analysis 定向全绿；
      净删 ~700 行；端口 8000/3000 无监听。
- 未做：A4 的 .bak 清理（等用户确认）。
```

Run: `git add docs/tasks/todo.md && git commit -m "docs(tasks): P0 死代码清除验证账目"`

---

## 遗留到下一份计划（P1+P2）的事项

本计划**故意不含**以下内容，勿顺手扩做到：

- 解析器三胞胎参数化 + `BIN_COLUMN_MAPPING` 单源（Plan B Task B1）
- SFTP 下载端点守卫链（Plan B Task B2）
- gage/excelize 样式与 `save_excelize` 复用共享层（Plan B Task B3）
- 视图与服务层小重复抽取（Plan B Task B4）
- `analysis_views.py` 689 行拆分（Plan B Task B5，决策 D4）
- `filtered_cpk` 单源 + CL 守卫收敛（Plan B Task B6，决策 D3）
- 文件加载 7 处内联复制（Plan B Task B7，决策 D1）
- 600 行违规项 `gage_legacy_builder.py`（901 → A1 后约 894）：决策 D4 定为另立项目
- `parse_limit_string` / `t_cdf` 两个"生产零调用但被测试当等价 oracle 有意 pin"的函数：**保留**，不属死代码
