# 批量参数分布图：测试项归类 + 每页上限装箱 Implementation Plan

**状态：已实施（2026-11-15）**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让批量参数分布图导出支持「按测试项名前缀/后缀/包含归类」并按每页最大项数装箱，总览超链接逐项指向实际 sheet 的块起始行。

**Architecture:** 前端只负责规则编辑、匹配与预览，导出时把**解析后的分组**发给后端；后端只做结构校验、装箱与 xlsx 装配，不复制匹配逻辑。无分组时保持现状（每项一 sheet），只享受已修复的超链接。

**Tech Stack:** Vue 3 + Element Plus + vitest；Django + openpyxl + unittest；Playwright。

**Spec:** `docs/superpowers/specs/2026-11-15-export-grouping-design.md`

## Global Constraints

- 单文件 ≤ 600 行；新后端测试不得加进 `apps/jobs/tests_jobs.py`（该文件按精确行数冻结在豁免表里，多一行即红）。
- 不新增任何依赖（前端无 zip 库，T3 不解析 xlsx）。
- 匹配规则：大小写不敏感；同一分类内多条件为「或」；未命中进「其他」且永远最后；冲突策略三选一，默认「首个命中」。
- 每页最大项数只允许 **30/50/100**，默认 **50**；装箱是「装满、末页余数」，不均分。
- 规则只存前端 localStorage（`lqdp.export.grouping.<fileId>`）；后端不接收规则。
- 新错误码 `invalid_groups` / `invalid_page_size` / `groups_not_supported` 必须同步 `frontend/src/utils/error.ts` 的 `ERROR_CODE_MAP`。
- 所有用户可见文案与注释用中文；样式走现有 `--token`。
- 每批提交前按 `docs/reference/testing-gates.md` 选门禁档；测试分层：纯函数 T2（vitest）、后端结构与契约 T1、导出下载接线 T3（Playwright）。

## 文件结构

| 文件 | 职责 |
|---|---|
| `frontend/src/pages/data/composables/exportGrouping.ts`（新） | 纯逻辑：匹配、冲突策略、预览计数、配置解析/持久化结构 |
| `frontend/test/unit/exportGrouping.spec.ts`（新） | 上述纯逻辑的 T2 判据 |
| `frontend/src/pages/data/components/export/ExportGroupingCard.vue`（新） | 归类规则编辑卡片 + 预览 |
| `frontend/src/pages/data/ExportToolsTab.vue`（改） | 挂载卡片、读写 localStorage、导出时附带分组 |
| `frontend/src/pages/data/components/export/ExportChartConfig.vue`（改） | 步骤号 2 → 3 |
| `frontend/src/pages/data/components/export/ExportActions.vue`（改） | 步骤号 3 → 4 |
| `frontend/src/utils/error.ts`（改） | 三个新错误码 |
| `apps/export/grouping.py`（新） | 纯函数：分组请求校验、错误码 |
| `apps/export/export_batch_charts_xlsx.py`（改） | 块布局重构、分页装配、总览分类列与锚点链接 |
| `apps/jobs/views.py`（改） | 提交时校验并写回归一化分组 |
| `apps/jobs/executor.py`（改） | task 携带 groups / max_items_per_sheet |
| `apps/jobs/runner.py`（改） | 把分组参数传给 builder（仅 xlsx） |
| `apps/export/tests_grouping.py`（新） | 校验 + 装箱 + 分页/锚点/多属的 T1 判据 |
| `apps/jobs/tests_batch_groups.py`（新） | task 携带分组字段的 T1 判据（不碰 tests_jobs.py） |
| `frontend/e2e/exports/grouped-export.spec.ts`（新） | 归类 UI → 导出 202 → 下载的 T3 接线证明 |

---

### Task 0: 基线整理与隔离工作树

**Files:** 无源码改动（仅 git 操作）。

**Interfaces:**
- Produces: 一个包含「导出图版式/口径/链接修复」提交的基线，供后续任务在隔离工作树执行。

**背景：** 当前工作树混有批3a 的未提交改动（`apps/datafiles/views/_duplicate_files.py`、`apps/datafiles/views/browse_views.py`、`test/backend/test_duplicate_keep_selection.py`），**不得**把它们带进本功能。

- [x] **Step 1: 确认工作树与待提交文件**

```bash
git status --porcelain
git diff --stat
```

预期：批3a 三个文件保持未提交；导出相关改动如下。

- [x] **Step 2: 经用户确认后，按三个逻辑提交归档导出侧改动**

```bash
git add apps/export/charts.py apps/export/tests_histogram_style.py test/backend/test_export_histogram_grid.py
git commit -m "feat(export): 导出直方图版式对齐屏幕（标题/双轴/All Site/色板）"

git add apps/export/export_batch_charts_xlsx.py
git commit -m "fix(export): Site 百分比对齐屏幕口径（全量分母+索引对齐+混合类型排序）"

git add apps/common/sheet_names.py apps/weight/xlsx.py apps/export/tests_sheet_links.py
git commit -m "fix(export): sheet 命名与总览超链接指向实际表（共享命名规则）"

git add docs/superpowers/specs/2026-11-15-export-grouping-design.md
git commit -m "docs(export): 测试项归类与分页设计稿"
```

注意：`export_batch_charts_xlsx.py` 同时含「unit 传参 + Site 口径 + 链接修复」，按主导变更归入第二笔即可；若用户不接受拆单，可改为一笔 `feat(export)` 并说明。

- [x] **Step 3: 建隔离工作树**

```bash
git worktree add .worktrees/feat-export-grouping -b feat/export-grouping HEAD
cd .worktrees/feat-export-grouping
```

预期：工作树干净；批3a 的未提交文件留在原工作树，不进入本分支。

---

### Task 1: 前端归类纯函数

**Files:**
- Create: `frontend/src/pages/data/composables/exportGrouping.ts`
- Test: `frontend/test/unit/exportGrouping.spec.ts`

**Interfaces:**
- Produces（后续任务按这些名字与类型使用）：
  - `type PatternType = 'prefix' | 'suffix' | 'contains'`
  - `type ConflictStrategy = 'first' | 'specific' | 'multi'`
  - `interface GroupPattern { type: PatternType; text: string }`
  - `interface GroupRule { id: string; name: string; patterns: GroupPattern[] }`
  - `interface GroupAssignment { name: string; params: string[] }`
  - `interface GroupingConfig { groups: GroupRule[]; strategy: ConflictStrategy; maxItemsPerSheet: number }`
  - `OTHER_GROUP_NAME`、`DEFAULT_MAX_ITEMS`、`MAX_ITEMS_OPTIONS`
  - `resolveGroups(params: string[], rules: GroupRule[], strategy: ConflictStrategy): GroupAssignment[]`
  - `countConflicts(params: string[], rules: GroupRule[]): number`
  - `estimateSheetCount(groups: GroupAssignment[], maxItems: number): number`
  - `hasGroupingRules(config: GroupingConfig): boolean`
  - `defaultGroupingConfig(): GroupingConfig`
  - `parseGroupingConfig(raw: string | null): GroupingConfig`
  - `newGroupId(): string`

- [x] **Step 1: 写失败测试**

```ts
// frontend/test/unit/exportGrouping.spec.ts
import { describe, expect, it } from 'vitest'

import {
  DEFAULT_MAX_ITEMS,
  OTHER_GROUP_NAME,
  countConflicts,
  defaultGroupingConfig,
  estimateSheetCount,
  hasGroupingRules,
  parseGroupingConfig,
  resolveGroups,
  type GroupRule,
} from '../../src/pages/data/composables/exportGrouping'

const rule = (id: string, name: string, patterns: GroupRule['patterns']): GroupRule => ({ id, name, patterns })

const RULES: GroupRule[] = [
  rule('r1', 'LKG', [{ type: 'prefix', text: 'LKG_' }]),
  rule('r2', 'TRIM', [{ type: 'contains', text: 'Trim' }]),
  rule('r3', 'POST', [{ type: 'suffix', text: 'Trim_Post' }]),
]

describe('resolveGroups', () => {
  it('大小写不敏感，前缀/后缀/包含都命中', () => {
    const out = resolveGroups(['lkg_en', 'xx_trim_yy', 'zz_trim_post'], RULES, 'multi')
    expect(out.map((g) => g.name)).toEqual(['LKG', 'TRIM', 'POST'])
    expect(out[0].params).toEqual(['lkg_en'])
    expect(out[1].params).toEqual(['xx_trim_yy', 'zz_trim_post'])
    expect(out[2].params).toEqual(['zz_trim_post'])
  })

  it('首个命中：按规则顺序归类', () => {
    const out = resolveGroups(['lkg_trim_post'], RULES, 'first')
    expect(out).toEqual([{ name: 'LKG', params: ['lkg_trim_post'] }])
  })

  it('最具体：后缀优先于包含，包含优先于前缀', () => {
    const out = resolveGroups(['lkg_trim_post'], RULES, 'specific')
    expect(out).toEqual([{ name: 'POST', params: ['lkg_trim_post'] }])
  })

  it('未命中进其他且永远最后', () => {
    const out = resolveGroups(['misc_a', 'lkg_b'], RULES, 'first')
    expect(out.map((g) => g.name)).toEqual(['LKG', OTHER_GROUP_NAME])
    expect(out[1].params).toEqual(['misc_a'])
  })

  it('空名称/空条件的分类不参与匹配', () => {
    const rules = [rule('x', ' ', [{ type: 'prefix', text: 'A' }]), rule('y', 'B', [{ type: 'prefix', text: '  ' }])]
    expect(resolveGroups(['ABC'], rules, 'first')).toEqual([{ name: OTHER_GROUP_NAME, params: ['ABC'] }])
  })
})

describe('preview helpers', () => {
  it('冲突数 = 命中 >1 分类的参数个数', () => {
    expect(countConflicts(['lkg_trim_post', 'lkg_x', 'misc'], RULES)).toBe(1)
  })

  it('预计 sheet 数 = 1 + Σ ceil(组大小 / 上限)', () => {
    expect(estimateSheetCount([{ name: 'A', params: Array(120).fill('p') }], 50)).toBe(4)
    expect(estimateSheetCount([], 50)).toBe(1)
  })

  it('hasGroupingRules 只看「有名字且有非空条件」', () => {
    expect(hasGroupingRules(defaultGroupingConfig())).toBe(false)
    expect(hasGroupingRules({ groups: RULES, strategy: 'first', maxItemsPerSheet: 50 })).toBe(true)
  })

  it('parseGroupingConfig 容错：坏 JSON / 脏字段回退默认', () => {
    expect(parseGroupingConfig('not-json')).toEqual(defaultGroupingConfig())
    const parsed = parseGroupingConfig(JSON.stringify({
      groups: [{ name: 'A', patterns: [{ type: 'bogus', text: 'x' }, { type: 'prefix', text: 'P' }] }],
      strategy: 'nope',
      maxItemsPerSheet: 7,
    }))
    expect(parsed.strategy).toBe('first')
    expect(parsed.maxItemsPerSheet).toBe(DEFAULT_MAX_ITEMS)
    expect(parsed.groups[0].patterns).toEqual([{ type: 'prefix', text: 'P' }])
  })
})
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run test/unit/exportGrouping.spec.ts
```

预期：FAIL（模块不存在）。

- [x] **Step 3: 实现**

```ts
// frontend/src/pages/data/composables/exportGrouping.ts
export type PatternType = 'prefix' | 'suffix' | 'contains'
export type ConflictStrategy = 'first' | 'specific' | 'multi'

export interface GroupPattern { type: PatternType; text: string }
export interface GroupRule { id: string; name: string; patterns: GroupPattern[] }
export interface GroupAssignment { name: string; params: string[] }
export interface GroupingConfig {
  groups: GroupRule[]
  strategy: ConflictStrategy
  maxItemsPerSheet: number
}

export const OTHER_GROUP_NAME = '其他'
export const MAX_ITEMS_OPTIONS = [30, 50, 100] as const
export const DEFAULT_MAX_ITEMS = 50

const TYPE_RANK: Record<PatternType, number> = { suffix: 3, contains: 2, prefix: 1 }
const STRATEGIES: ConflictStrategy[] = ['first', 'specific', 'multi']

export function newGroupId(): string {
  return `g_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`
}

export function defaultGroupingConfig(): GroupingConfig {
  return { groups: [], strategy: 'first', maxItemsPerSheet: DEFAULT_MAX_ITEMS }
}

function validRules(rules: GroupRule[]): GroupRule[] {
  return rules.filter((r) => r.name.trim() && r.patterns.some((p) => p.text.trim()))
}

function matchScore(param: string, rule: GroupRule): { rank: number; len: number } | null {
  const name = param.toLowerCase()
  let best: { rank: number; len: number } | null = null
  for (const pattern of rule.patterns) {
    const text = pattern.text.trim().toLowerCase()
    if (!text) continue
    const hit = pattern.type === 'prefix' ? name.startsWith(text)
      : pattern.type === 'suffix' ? name.endsWith(text)
        : name.includes(text)
    if (!hit) continue
    const score = { rank: TYPE_RANK[pattern.type], len: text.length }
    if (!best || score.rank > best.rank || (score.rank === best.rank && score.len > best.len)) best = score
  }
  return best
}

export function resolveGroups(
  params: string[], rules: GroupRule[], strategy: ConflictStrategy,
): GroupAssignment[] {
  const valid = validRules(rules)
  const buckets = new Map<string, string[]>(valid.map((r) => [r.id, []]))
  const other: string[] = []
  for (const param of params) {
    const hits = valid
      .map((r) => ({ rule: r, score: matchScore(param, r) }))
      .filter((h): h is { rule: GroupRule; score: { rank: number; len: number } } => h.score !== null)
    if (hits.length === 0) { other.push(param); continue }
    if (strategy === 'multi') {
      for (const h of hits) buckets.get(h.rule.id)!.push(param)
      continue
    }
    let chosen = hits[0]
    if (strategy === 'specific') {
      for (const h of hits.slice(1)) {
        if (h.score.rank > chosen.score.rank
          || (h.score.rank === chosen.score.rank && h.score.len > chosen.score.len)) chosen = h
      }
    }
    buckets.get(chosen.rule.id)!.push(param)
  }
  const out = valid
    .map((r) => ({ name: r.name.trim(), params: buckets.get(r.id)! }))
    .filter((g) => g.params.length > 0)
  if (other.length) out.push({ name: OTHER_GROUP_NAME, params: other })
  return out
}

export function countConflicts(params: string[], rules: GroupRule[]): number {
  const valid = validRules(rules)
  return params.filter((p) => valid.filter((r) => matchScore(p, r) !== null).length > 1).length
}

export function estimateSheetCount(groups: GroupAssignment[], maxItems: number): number {
  const cap = maxItems > 0 ? maxItems : DEFAULT_MAX_ITEMS
  return 1 + groups.reduce((sum, g) => sum + Math.ceil(g.params.length / cap), 0)
}

export function hasGroupingRules(config: GroupingConfig): boolean {
  return validRules(config.groups).length > 0
}

export function parseGroupingConfig(raw: string | null): GroupingConfig {
  const fallback = defaultGroupingConfig()
  if (!raw) return fallback
  try {
    const data = JSON.parse(raw) as Partial<GroupingConfig>
    const groups = Array.isArray(data.groups) ? data.groups : []
    const cleaned: GroupRule[] = groups
      .filter((g): g is GroupRule => !!g && typeof g.name === 'string' && Array.isArray(g.patterns))
      .map((g) => ({
        id: typeof g.id === 'string' && g.id ? g.id : newGroupId(),
        name: g.name,
        patterns: g.patterns
          .filter((p) => !!p && ['prefix', 'suffix', 'contains'].includes(p.type) && typeof p.text === 'string')
          .map((p) => ({ type: p.type, text: p.text })),
      }))
    return {
      groups: cleaned,
      strategy: STRATEGIES.includes(data.strategy as ConflictStrategy)
        ? (data.strategy as ConflictStrategy) : 'first',
      maxItemsPerSheet: (MAX_ITEMS_OPTIONS as readonly number[]).includes(data.maxItemsPerSheet as number)
        ? (data.maxItemsPerSheet as number) : DEFAULT_MAX_ITEMS,
    }
  } catch {
    return fallback
  }
}
```

- [x] **Step 4: 跑测试确认通过**

```bash
cd frontend && npx vitest run test/unit/exportGrouping.spec.ts
```

预期：PASS。

- [x] **Step 5: 提交**

```bash
git add frontend/src/pages/data/composables/exportGrouping.ts frontend/test/unit/exportGrouping.spec.ts
git commit -m "feat(export): 测试项归类纯函数（匹配/策略/预览计数）"
```

---

### Task 2: 后端分组校验纯函数

**Files:**
- Create: `apps/export/grouping.py`
- Test: `apps/export/tests_grouping.py`

**Interfaces:**
- Produces：
  - `OTHER_GROUP_NAME`、`DEFAULT_MAX_ITEMS_PER_SHEET = 50`、`ALLOWED_MAX_ITEMS_PER_SHEET = (30, 50, 100)`
  - `class GroupingError(ValueError)`，属性 `code: str`、`field: str`
  - `normalize_batch_grouping(raw_groups, raw_max, params, fmt='xlsx') -> (list[dict] | None, int)`

- [x] **Step 1: 写失败测试**

```python
# apps/export/tests_grouping.py
"""批量参数分布图分组契约与装箱的 T1 判据。"""

import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from apps.export.grouping import (
    DEFAULT_MAX_ITEMS_PER_SHEET, GroupingError, normalize_batch_grouping,
)


def _normalize(*args, **kwargs):
    return normalize_batch_grouping(*args, **kwargs)


class NormalizeGroupingTests(SimpleTestCase):
    PARAMS = ['A', 'B', 'C']

    def test_absent_groups_returns_legacy(self):
        self.assertEqual(_normalize(None, None, self.PARAMS), (None, DEFAULT_MAX_ITEMS_PER_SHEET))

    def test_valid_groups_are_trimmed(self):
        groups, max_items = _normalize(
            [{'name': ' LKG ', 'params': ['A']}, {'name': '其他', 'params': ['B', 'C']}],
            None, self.PARAMS)
        self.assertEqual(groups[0], {'name': 'LKG', 'params': ['A']})
        self.assertEqual(max_items, DEFAULT_MAX_ITEMS_PER_SHEET)

    def test_union_must_equal_params(self):
        with self.assertRaises(GroupingError) as ctx:
            _normalize([{'name': 'A', 'params': ['A']}], None, self.PARAMS)
        self.assertEqual((ctx.exception.code, ctx.exception.field), ('invalid_groups', 'groups'))

    def test_duplicate_within_group_rejected(self):
        with self.assertRaises(GroupingError):
            _normalize([{'name': 'A', 'params': ['A', 'A', 'B', 'C']}], None, self.PARAMS)

    def test_unknown_param_rejected(self):
        with self.assertRaises(GroupingError):
            _normalize([{'name': 'A', 'params': ['A', 'B', 'C', 'X']}], None, self.PARAMS)

    def test_bad_page_size_rejected(self):
        for bad in (20, '50', True):
            with self.assertRaises(GroupingError) as ctx:
                _normalize([{'name': 'A', 'params': ['A', 'B', 'C']}], bad, self.PARAMS)
            self.assertEqual((ctx.exception.code, ctx.exception.field),
                             ('invalid_page_size', 'max_items_per_sheet'))

    def test_pptx_with_groups_rejected(self):
        with self.assertRaises(GroupingError) as ctx:
            _normalize([{'name': 'A', 'params': ['A', 'B', 'C']}], 50, self.PARAMS, 'pptx')
        self.assertEqual((ctx.exception.code, ctx.exception.field),
                         ('groups_not_supported', 'groups'))

    def test_multi_assign_allowed_across_groups(self):
        groups, _ = _normalize(
            [{'name': 'A', 'params': ['A', 'B']}, {'name': 'B', 'params': ['A', 'C']}],
            None, self.PARAMS)
        self.assertEqual([g['params'] for g in groups], [['A', 'B'], ['A', 'C']])
```

- [x] **Step 2: 跑测试确认失败**

```bash
.venv/Scripts/python.exe manage.py test apps.export.tests_grouping.NormalizeGroupingTests
```

预期：FAIL / ERROR（模块不存在）。

- [x] **Step 3: 实现**

```python
# apps/export/grouping.py
"""批量参数分布图的测试项分组契约（纯函数，不依赖 Django）。

规则匹配只在**前端**执行；本模块只校验前端发来的「已解析分组」并收敛每页上限。
"""

OTHER_GROUP_NAME = '其他'
DEFAULT_MAX_ITEMS_PER_SHEET = 50
ALLOWED_MAX_ITEMS_PER_SHEET = (30, 50, 100)


class GroupingError(ValueError):
    """带机器码与字段名的校验错误（视图转成 400 + extra.field）。"""

    def __init__(self, code: str, field: str):
        super().__init__(code)
        self.code = code
        self.field = field


def normalize_batch_grouping(raw_groups, raw_max, params, fmt='xlsx'):
    """校验并收敛分组请求；无分组返回 ``(None, DEFAULT_MAX_ITEMS_PER_SHEET)``。

    只做结构校验：参数是否真的存在于文件列由装配层按现有语义过滤
    （当前 ``params`` 同样只跳过不存在的列）。
    """
    if raw_groups in (None, [], ()):
        return None, DEFAULT_MAX_ITEMS_PER_SHEET
    if fmt == 'pptx':
        raise GroupingError('groups_not_supported', 'groups')
    if not isinstance(raw_groups, list):
        raise GroupingError('invalid_groups', 'groups')

    max_items = DEFAULT_MAX_ITEMS_PER_SHEET if raw_max is None else raw_max
    if isinstance(max_items, bool) or not isinstance(max_items, int) \
            or max_items not in ALLOWED_MAX_ITEMS_PER_SHEET:
        raise GroupingError('invalid_page_size', 'max_items_per_sheet')

    selected = set(params or [])
    normalized = []
    union = set()
    for group in raw_groups:
        if not isinstance(group, dict):
            raise GroupingError('invalid_groups', 'groups')
        name = group.get('name')
        members = group.get('params')
        if not isinstance(name, str) or not name.strip():
            raise GroupingError('invalid_groups', 'groups')
        if not isinstance(members, list) or not members \
                or not all(isinstance(m, str) for m in members):
            raise GroupingError('invalid_groups', 'groups')
        if len(set(members)) != len(members) or not set(members) <= selected:
            raise GroupingError('invalid_groups', 'groups')
        union |= set(members)
        normalized.append({'name': name.strip(), 'params': list(members)})
    if union != selected:
        raise GroupingError('invalid_groups', 'groups')
    return normalized, max_items
```

- [x] **Step 4: 跑测试确认通过**

```bash
.venv/Scripts/python.exe manage.py test apps.export.tests_grouping.NormalizeGroupingTests
```

预期：PASS。

- [x] **Step 5: 提交**

```bash
git add apps/export/grouping.py apps/export/tests_grouping.py
git commit -m "feat(export): 分组请求校验纯函数（结构/页上限/PPT 拒绝）"
```

---

### Task 3: xlsx 块布局重构（现状逐字不变）

**Files:**
- Modify: `apps/export/export_batch_charts_xlsx.py`
- Test: `apps/export/tests_grouping.py`（追加 `BlockLayoutTests`）

**Interfaces:**
- Produces:
  - `_block_height(entry) -> int`：无 site 时 32；`max(8, site行数+3) + 24`
  - `_write_block(ws, start_row, title, entry, png, df, metadata, site_col, flags) -> BytesIO | None`
    （空图返回 None，不写任何内容）
  - `_block_image_row(start_row, site_rows) -> int` = `start_row + max(8, site_rows + 3)`
- Consumes: 现有 `_create_histogram_chart`、`unique_sheet_names`、`_render_chart_pngs`。

- [x] **Step 1: 写失败测试（现状不变量 + 行距公式）**

```python
# 追加到 apps/export/tests_grouping.py
from apps.export.export_batch_charts_xlsx import (
    _block_height, _block_image_row, build_batch_charts_xlsx_with_charts,
)


class BlockLayoutTests(SimpleTestCase):
    PARAMS = ['P00', 'P01', 'P02']

    def _build(self, **kwargs):
        rng = np.random.default_rng(0)
        df = pd.DataFrame({p: rng.normal(10, 1, 40) for p in self.PARAMS})
        metadata = {
            'units': {p: 'V' for p in self.PARAMS},
            'mins': {p: '0' for p in self.PARAMS},
            'maxs': {p: '20' for p in self.PARAMS},
            'format': 'CTA8290D',
        }
        return build_batch_charts_xlsx_with_charts(
            df, metadata, self.PARAMS, dpi=72, workers=1, **kwargs)

    def test_block_math(self):
        self.assertEqual(_block_height({}), 32)
        self.assertEqual(_block_height({'site_stats': [{}] * 3}), 32)
        self.assertEqual(_block_height({'site_stats': [{}] * 10}), 37)
        self.assertEqual(_block_image_row(1, 0), 9)
        self.assertEqual(_block_image_row(1, 10), 14)
        self.assertEqual(_block_image_row(33, 0), 41)

    def test_legacy_sheet_layout_unchanged(self):
        from openpyxl import load_workbook
        import io
        wb = load_workbook(io.BytesIO(self._build()))
        self.assertEqual(wb.sheetnames, ['总览', 'P00', 'P01', 'P02'])
        ws = wb['P00']
        self.assertEqual(ws.cell(1, 1).value, '统计项')
        self.assertEqual(ws.cell(2, 1).value, 'P00')
        self.assertEqual(ws.cell(8, 5).value, '← 返回总览')
        self.assertEqual(len(ws._images), 1)
        # 总览链接仍指向 A1
        self.assertEqual(wb['总览'].cell(2, 2).hyperlink.target, "#'P00'!A1")
```

- [x] **Step 2: 跑测试确认失败**

```bash
.venv/Scripts/python.exe manage.py test apps.export.tests_grouping.BlockLayoutTests
```

预期：FAIL / ERROR（`_block_height` 不存在）。

- [x] **Step 3: 实现块布局**

把现有 `_write_detail_sheet` 改造成「在给定起始行写一个块」，行号统一以 `start_row` 偏移（`S=1` 时与现状逐字一致）：

```python
def _block_image_row(start_row: int, site_rows: int) -> int:
    """图块锚点行：统计/Site 表下方，至少留到 S+8（现状 S=1 → 第 9 行）。"""
    return start_row + max(8, site_rows + 3)


def _block_height(entry) -> int:
    """一个块占用的行数：图锚点行距 + 450px（≈23 行）+ 1 行间隔。"""
    return max(8, len(entry.get('site_stats') or []) + 3) + 24


def _write_block(ws, start_row, title, entry, png, df, metadata, site_col, flags):
    """在 ws 的 start_row 起写一个「统计 + 图」块；返回图片 buffer（或 None）。

    调用方须保留返回的 buffer 到 ``wb.save()`` 之后。
    """
    stats_data = entry.get('stats_data', {})
    site_stats_list = entry.get('site_stats', [])
    chart_data = entry.get('chart_data', {})

    if png is None:
        img_buffer = _create_histogram_chart(
            df, metadata, title, chart_data['data_series'],
            chart_data['mean_val'], chart_data['std_val'],
            chart_data['rdl_min'], chart_data['rdl_max'],
            show_limit=flags.show_limit, show_3sigma=flags.show_3sigma,
            show_4sigma=flags.show_4sigma, show_6sigma=flags.show_6sigma,
            show_normal=flags.show_normal, show_kde=flags.show_kde, site_col=site_col,
            dpi=flags.dpi, unit=stats_data.get('unit', ''),
        )
    else:
        img_buffer = io.BytesIO(png)
    if img_buffer.getbuffer().nbytes == 0:
        img_buffer.close()
        return None

    for col_idx, header in enumerate(DETAIL_HEADERS, 1):
        cell = ws.cell(row=start_row, column=col_idx, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGNMENT

    if stats_data:
        row_param = start_row + 1
        ws.cell(row=row_param, column=1, value=stats_data.get('param_name', ''))
        ws.cell(row=row_param, column=2, value=stats_data.get('low_limit', 0)).number_format = '0.0000'
        ws.cell(row=row_param, column=3, value=stats_data.get('high_limit', 0)).number_format = '0.0000'
        ws.cell(row=row_param, column=4, value=stats_data.get('unit', ''))

        left_labels = [("Mean", "mean_val", start_row + 3, 1), ("STD", "std_val", start_row + 4, 1),
                       ("Range", "data_range", start_row + 5, 1), ("数据点数", "count", start_row + 6, 1),
                       ("CPK", "cpk_str", start_row + 7, 1)]
        for label, key, row, col in left_labels:
            ws.cell(row=row, column=col, value=label).fill = STATS_LABEL_FILL
            ws.cell(row=row, column=col).alignment = CENTER_ALIGNMENT
            cell = ws.cell(row=row, column=col + 1, value=str(stats_data.get(key, '')))
            cell.alignment = CENTER_ALIGNMENT
            if key == "cpk_str":
                _apply_cpk_style(cell, stats_data.get('cpk_color', 'gray'))
            elif key in ("mean_val", "std_val"):
                cell.number_format = '0.0000'

    if site_stats_list:
        ws.cell(row=start_row, column=6, value="Site统计").fill = HEADER_FILL
        ws.cell(row=start_row, column=6).font = HEADER_FONT
        ws.cell(row=start_row, column=6).alignment = HEADER_ALIGNMENT
        for col_idx, header in enumerate(SITE_HEADERS, 1):
            cell = ws.cell(row=start_row + 1, column=col_idx + 5, value=header)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = HEADER_ALIGNMENT
        for row_offset, site_info in enumerate(site_stats_list):
            is_fail = _site_fail_count(site_info) > 0
            is_all = site_info.get('Site') == 'ALL Site'
            for col_idx, key in enumerate(SITE_HEADERS, 1):
                cell = ws.cell(row=start_row + 2 + row_offset, column=col_idx + 5,
                               value=site_info.get(key, ''))
                cell.alignment = CENTER_ALIGNMENT
                if is_fail:
                    cell.fill = FAIL_FILL
                    cell.font = FAIL_FONT
                elif is_all:
                    cell.fill = ALL_FILL
                else:
                    cell.fill = NORMAL_FILL

    return_cell = ws.cell(row=start_row + 7, column=5, value="← 返回总览")
    return_cell.hyperlink = "#'总览'!A1"
    return_cell.font = LINK_FONT

    img_buffer.seek(0)
    image = XlImage(img_buffer)
    image.width = 800
    image.height = 450
    ws.add_image(image, f'A{_block_image_row(start_row, len(site_stats_list))}')
    return img_buffer
```

同时在页面装配处设置列宽（每张 sheet 一次）：

```python
def _set_detail_column_widths(ws):
    for col in range(1, 6):
        ws.column_dimensions[get_column_letter(col)].width = 18
    for col in range(6, 11):
        ws.column_dimensions[get_column_letter(col)].width = 14
```

把 builder 的逐参数循环临时替换为「每参数一页、块起始行 1」的等价路径（本任务先保持行为不变）：

```python
    rows_by_title = dict(rows)
    open_buffers = []
    png_results = _render_chart_pngs(rows, flags, workers)
    for idx, (title, entry) in enumerate(rows):
        if progress_cb:
            progress_cb(idx + 1)
        ws = wb.create_sheet(title=sheet_names[title])
        _set_detail_column_widths(ws)
        buffer = _write_block(ws, 1, title, entry, png_results.get(title),
                              df, metadata, site_col, flags)
        if buffer is not None:
            open_buffers.append(buffer)
```

删除旧 `_write_detail_sheet`。

- [x] **Step 4: 跑测试与全套回归**

```bash
.venv/Scripts/python.exe manage.py test apps.export.tests_grouping.BlockLayoutTests apps.export test.backend.test_export_histogram_grid
```

预期：全部 PASS（现有用例钉住版式未变）。

- [x] **Step 5: 提交**

```bash
git add apps/export/export_batch_charts_xlsx.py apps/export/tests_grouping.py
git commit -m "refactor(export): 明细 sheet 改为可偏移的块布局（S=1 与现状逐字一致）"
```

---

### Task 4: 分组分页装配（分类列 / 锚点 / 多属）

**Files:**
- Modify: `apps/export/export_batch_charts_xlsx.py`
- Test: `apps/export/tests_grouping.py`（追加 `GroupedLayoutTests`）

**Interfaces:**
- Consumes: Task 2 的 `DEFAULT_MAX_ITEMS_PER_SHEET`；Task 3 的 `_write_block` / `_block_height`。
- Produces（builder 新参数）：
  - `build_batch_charts_xlsx_with_charts(..., groups=None, max_items_per_sheet=DEFAULT_MAX_ITEMS_PER_SHEET)`
  - `_plan_pages(rows, groups, max_items) -> list[tuple[str, list[str]]]`（页基础名 + 块标题列表）
  - `_groups_by_param(titles, groups) -> dict[str, list[str]]`
  - `_plan_targets(pages, sheet_names, rows_by_title) -> dict[str, tuple[str, int]]`

- [x] **Step 1: 写失败测试**

```python
# 追加到 apps/export/tests_grouping.py
class GroupedLayoutTests(SimpleTestCase):
    PARAMS = ['P00', 'P01', 'P02', 'P03', 'P04']

    def _build(self, groups, max_items=50):
        rng = np.random.default_rng(0)
        df = pd.DataFrame({p: rng.normal(10, 1, 40) for p in self.PARAMS})
        metadata = {
            'units': {p: 'V' for p in self.PARAMS},
            'mins': {p: '0' for p in self.PARAMS},
            'maxs': {p: '20' for p in self.PARAMS},
            'format': 'CTA8290D',
        }
        return build_batch_charts_xlsx_with_charts(
            df, metadata, self.PARAMS, dpi=72, workers=1,
            groups=groups, max_items_per_sheet=max_items)

    @staticmethod
    def _wb(payload):
        import io
        from openpyxl import load_workbook
        return load_workbook(io.BytesIO(payload))

    def test_groups_sheets_links_and_category_column(self):
        wb = self._wb(self._build([
            {'name': 'A', 'params': ['P00', 'P01']},
            {'name': 'B', 'params': ['P02', 'P03', 'P04']},
        ]))
        self.assertEqual(wb.sheetnames, ['总览', 'A', 'B'])
        summary = wb['总览']
        self.assertEqual(summary.cell(1, 3).value, '分类')
        self.assertEqual([summary.cell(r, 3).value for r in range(2, 7)], ['A', 'A', 'B', 'B', 'B'])
        self.assertEqual(summary.cell(2, 2).hyperlink.target, "#'A'!A1")
        # 无 Site → 块高 32：第二块从第 33 行开始
        self.assertEqual(summary.cell(3, 2).hyperlink.target, "#'A'!A33")
        self.assertEqual(summary.cell(4, 2).hyperlink.target, "#'B'!A1")
        self.assertEqual(wb['A'].cell(2, 1).value, 'P00')
        self.assertEqual(wb['A'].cell(34, 1).value, 'P01')
        self.assertEqual(wb['B'].cell(2, 1).value, 'P02')

    def test_page_cap_packs_full_pages_not_even_split(self):
        groups = [{'name': 'G', 'params': self.PARAMS}]
        wb = self._wb(self._build(groups, max_items=2))
        self.assertEqual(wb.sheetnames, ['总览', 'G_1', 'G_2', 'G_3'])
        summary = wb['总览']
        # 第 3 个参数 P02 落在 G_2 的第一块
        self.assertEqual(summary.cell(4, 2).hyperlink.target, "#'G_2'!A1")

    def test_multi_assign_embeds_block_twice_and_links_first(self):
        wb = self._wb(self._build([
            {'name': 'A', 'params': ['P00', 'P01']},
            {'name': 'B', 'params': ['P00', 'P02']},
        ]))
        summary = wb['总览']
        self.assertEqual(summary.cell(2, 3).value, 'A / B')
        self.assertEqual(summary.cell(2, 2).hyperlink.target, "#'A'!A1")
        self.assertEqual(wb['B'].cell(2, 1).value, 'P00')
        self.assertEqual(len(wb['A']._images), 2)
        self.assertEqual(len(wb['B']._images), 2)
```

- [x] **Step 2: 跑测试确认失败**

```bash
.venv/Scripts/python.exe manage.py test apps.export.tests_grouping.GroupedLayoutTests
```

预期：FAIL（builder 不认 `groups`）。

- [x] **Step 3: 实现装箱与总览改造**

在 `export_batch_charts_xlsx.py` 增加：

```python
from apps.export.grouping import DEFAULT_MAX_ITEMS_PER_SHEET


def _plan_pages(rows, groups, max_items):
    """按分组顺序装箱：每页装满后开新页，末页放余数。

    组内顺序 = rows 的文件列序；组内参数若不在 rows（列不存在/无数据）则跳过；
    rows 中未被任何组覆盖的参数兜底进「其他」（前端已发，装配层再兜一次）。
    """
    order = [title for title, _entry in rows]
    titles = set(order)
    pages, assigned = [], set()
    for group in groups:
        wanted = set(group['params'])
        members = [t for t in order if t in wanted]
        if not members:
            continue
        parts = [members[i:i + max_items] for i in range(0, len(members), max_items)]
        for i, part in enumerate(parts, 1):
            base = group['name'] if len(parts) == 1 else f"{group['name']}_{i}"
            pages.append((base, part))
        assigned.update(members)
    rest = [t for t in order if t not in assigned]
    if rest:
        parts = [rest[i:i + max_items] for i in range(0, len(rest), max_items)]
        for i, part in enumerate(parts, 1):
            base = OTHER_GROUP_NAME if len(parts) == 1 else f'{OTHER_GROUP_NAME}_{i}'
            pages.append((base, part))
    return pages


def _groups_by_param(titles, groups):
    out = {title: [] for title in titles}
    for group in groups:
        for title in group['params']:
            if title in out and group['name'] not in out[title]:
                out[title].append(group['name'])
    for names in out.values():
        if not names:
            names.append(OTHER_GROUP_NAME)
    return out


def _plan_targets(pages, sheet_names, rows_by_title):
    targets = {}
    for (base, titles), sheet_name in zip(pages, sheet_names):
        start = 1
        for title in titles:
            targets.setdefault(title, (sheet_name, start))
            start += _block_height(rows_by_title[title])
    return targets
```

`_write_summary_sheet` 改为接收 `group_names_by_param` 与 `targets`，表头插入「分类」并平移列号：

```python
SUMMARY_HEADERS = ["序号", "参数", "分类", "数据点数", "Mean", "STD", "Min", "Max",
                   "CPK", "CPK Level", "ALL Site Yield"]

def _write_summary_sheet(ws_summary, rows, group_names_by_param, targets):
    """总览：序号/参数/分类/统计…；参数超链接指向实际 sheet 的块起始行。"""
    for col_idx, header in enumerate(SUMMARY_HEADERS, 1):
        cell = ws_summary.cell(row=1, column=col_idx, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = HEADER_ALIGNMENT

    col_max_widths = {i: _get_text_width(SUMMARY_HEADERS[i - 1]) for i in range(1, len(SUMMARY_HEADERS) + 1)}

    for param_idx, (selected_param, entry) in enumerate(rows, 1):
        stats_data = entry['stats_data']
        row = param_idx + 1
        cell_param = ws_summary.cell(row=row, column=2, value=selected_param)
        sheet_name, anchor_row = targets[selected_param]
        cell_param.hyperlink = f"#'{sheet_name}'!A{anchor_row}"
        cell_param.font = LINK_FONT

        ws_summary.cell(row=row, column=1, value=param_idx).alignment = Alignment(horizontal="center")
        ws_summary.cell(row=row, column=3,
                        value=' / '.join(group_names_by_param.get(selected_param, []))).alignment = Alignment(horizontal="center")
        ws_summary.cell(row=row, column=4, value=stats_data['count']).alignment = Alignment(horizontal="center")
        ws_summary.cell(row=row, column=5, value=str(stats_data['mean_val'])).alignment = Alignment(horizontal="center")
        ws_summary.cell(row=row, column=6, value=str(stats_data['std_val'])).alignment = Alignment(horizontal="center")

        range_parts = str(stats_data['data_range']).split(' ~ ')
        ws_summary.cell(row=row, column=7, value=range_parts[0] if len(range_parts) > 0 else '').alignment = Alignment(horizontal="center")
        ws_summary.cell(row=row, column=8, value=range_parts[1] if len(range_parts) > 1 else '').alignment = Alignment(horizontal="center")

        cell_cpk = ws_summary.cell(row=row, column=9, value=stats_data['cpk_str'])
        _apply_cpk_style(cell_cpk, stats_data.get('cpk_color', 'gray'))
        ws_summary.cell(row=row, column=10, value=str(stats_data['cpk_str'])).alignment = Alignment(horizontal="center")

        all_site_yield = "100.00%"
        for site_info in entry['site_stats']:
            if site_info.get('Site') == 'ALL Site':
                all_site_yield = site_info.get('Yield', '100.00%')
                break
        cell_yield = ws_summary.cell(row=row, column=11, value=all_site_yield)
        cell_yield.alignment = Alignment(horizontal="center")
        for site_info in entry['site_stats']:
            if site_info.get('Site') == 'ALL Site':
                if _site_fail_count(site_info) > 0:
                    cell_yield.fill = FAIL_FILL
                    cell_yield.font = FAIL_FONT
                else:
                    cell_yield.fill = NORMAL_FILL
                break

        row_vals = [(1, param_idx), (2, selected_param), (3, ' / '.join(group_names_by_param.get(selected_param, []))),
                    (4, stats_data['count']), (5, str(stats_data['mean_val'])), (6, str(stats_data['std_val'])),
                    (7, range_parts[0] if len(range_parts) > 0 else ''), (8, range_parts[1] if len(range_parts) > 1 else ''),
                    (9, str(stats_data['cpk_str'])), (10, str(stats_data['cpk_str'])), (11, all_site_yield)]
        for col_i, val in row_vals:
            width = _get_text_width(val)
            if width > col_max_widths.get(col_i, 0):
                col_max_widths[col_i] = width

    for col in range(1, len(SUMMARY_HEADERS) + 1):
        ws_summary.column_dimensions[get_column_letter(col)].width = min(col_max_widths.get(col, 15), 40)
```

builder 主流程改为：

```python
def build_batch_charts_xlsx_with_charts(df, metadata, params, site_col=None,
                                         show_limit=True, show_3sigma=False,
                                         show_4sigma=False, show_6sigma=True,
                                         show_normal=False, show_kde=False,
                                         dpi=EXPORT_DPI_DEFAULT,
                                         cpk_thresholds=None,
                                         workers=None, progress_cb=None,
                                         groups=None,
                                         max_items_per_sheet=DEFAULT_MAX_ITEMS_PER_SHEET):
    ...
    rows = _collect_param_stats(df, metadata, params, site_col, th)
    rows_by_title = dict(rows)
    titles = [title for title, _entry in rows]

    if groups:
        page_cap = int(max_items_per_sheet or DEFAULT_MAX_ITEMS_PER_SHEET)
        pages = _plan_pages(rows, groups, page_cap)
        group_names = _groups_by_param(titles, groups)
    else:
        pages = [(title, [title]) for title in titles]
        group_names = {title: [] for title in titles}
    sheet_names = unique_sheet_names([base for base, _titles in pages])
    targets = _plan_targets(pages, sheet_names, rows_by_title)
    _write_summary_sheet(ws_summary, rows, group_names, targets)

    open_buffers = []
    png_results = _render_chart_pngs(rows, flags, workers)
    done = set()
    for (base, page_titles), sheet_name in zip(pages, sheet_names):
        ws = wb.create_sheet(title=sheet_name)
        _set_detail_column_widths(ws)
        start = 1
        has_content = False
        for title in page_titles:
            buffer = _write_block(ws, start, title, rows_by_title[title],
                                  png_results.get(title), df, metadata, site_col, flags)
            if buffer is None:
                continue
            has_content = True
            open_buffers.append(buffer)
            start += _block_height(rows_by_title[title])
            if title not in done:
                done.add(title)
                if progress_cb:
                    progress_cb(len(done))
        if not has_content:
            wb.remove(ws)
    ...
```

注意：`sheet_names` 与 `pages` 数量一致；`targets` 用 `setdefault` 保证多属只记第一次。

- [x] **Step 4: 跑测试**

```bash
.venv/Scripts/python.exe manage.py test apps.export.tests_grouping apps.export test.backend.test_export_histogram_grid
```

预期：PASS。

- [x] **Step 5: 提交**

```bash
git add apps/export/export_batch_charts_xlsx.py apps/export/tests_grouping.py
git commit -m "feat(export): 按分组装箱分页并让总览链接指向块锚点"
```

---

### Task 5: 作业提交与任务装配接线

**Files:**
- Modify: `apps/jobs/views.py:122-138`、`apps/jobs/executor.py:258-275`、`apps/jobs/runner.py:163-166`
- Modify: `frontend/src/utils/error.ts`
- Test: `apps/jobs/tests_batch_groups.py`（新文件，勿加进 `tests_jobs.py`）

**Interfaces:**
- Consumes: Task 2 `normalize_batch_grouping` / `GroupingError`；Task 4 builder 参数。
- Produces: task dict 键 `groups`（`list[dict]`）与 `max_items_per_sheet`（`int`）；view 对非法请求返回 400。

- [x] **Step 1: 写失败测试**

```python
# apps/jobs/tests_batch_groups.py
from django.test import SimpleTestCase

from apps.jobs.executor import build_batch_charts_task
from apps.export.grouping import GroupingError, normalize_batch_grouping


class BatchChartsTaskGroupingTests(SimpleTestCase):
    def _task(self, params):
        return build_batch_charts_task(
            params=params, abs_path='C:/none/x.csv', fmt='CTA8290D',
            job_id=1, owner_id=1, dpi=100, cpk_thresholds=(1.67, 1.33, 1.0),
            groups=params.get('groups'),
            max_items_per_sheet=params.get('max_items_per_sheet'))

    def test_task_carries_groups_and_cap(self):
        groups = [{'name': 'A', 'params': ['P1']}]
        task = self._task({'params': ['P1'], 'groups': groups, 'max_items_per_sheet': 50})
        self.assertEqual(task['groups'], groups)
        self.assertEqual(task['max_items_per_sheet'], 50)

    def test_task_omits_grouping_keys_when_absent(self):
        task = self._task({'params': ['P1']})
        self.assertNotIn('groups', task)
        self.assertNotIn('max_items_per_sheet', task)
```

- [x] **Step 2: 跑测试确认失败**

```bash
.venv/Scripts/python.exe manage.py test apps.jobs.tests_batch_groups
```

预期：FAIL（`build_batch_charts_task` 不接受新参数）。

- [x] **Step 3: 实现接线**

`executor.py`：

```python
from apps.export.grouping import DEFAULT_MAX_ITEMS_PER_SHEET

def build_batch_charts_task(*, params, abs_path, fmt, job_id, owner_id,
                            dpi, cpk_thresholds, chart_format='xlsx',
                            groups=None, max_items_per_sheet=None) -> dict:
    show_keys = ('show_limit', 'show_3sigma', 'show_4sigma',
                 'show_6sigma', 'show_normal', 'show_kde')
    task = _base_task(params=params, abs_path=abs_path, fmt=fmt,
                      job_id=job_id, owner_id=owner_id) | {
        'params': list(params.get('params') or []),
        'chart_format': chart_format,
        'dpi': int(dpi),
        'cpk_thresholds': tuple(cpk_thresholds),
        'data_only_bin1': bool(params.get('data_only_bin1')),
        **{k: params.get(k, True if k == 'show_limit' or k == 'show_6sigma' else False)
           for k in show_keys},
    }
    if groups:
        task['groups'] = groups
        task['max_items_per_sheet'] = int(max_items_per_sheet or DEFAULT_MAX_ITEMS_PER_SHEET)
    return task
```

`views.py::_build_task` 透传：

```python
    if kind == 'export_batch_charts':
        return executor.build_batch_charts_task(
            params={**params, 'result_name': prefs['result_name']},
            abs_path=abs_path, fmt=fmt,
            job_id=job_id, owner_id=owner_id,
            dpi=prefs['dpi'], cpk_thresholds=prefs['cpk_thresholds'],
            chart_format='pptx' if str(params.get('format', 'xlsx')) == 'pptx' else 'xlsx',
            groups=params.get('groups'),
            max_items_per_sheet=params.get('max_items_per_sheet'))
```

`views.py::_submit_export` 在解析 `params` 后加校验：

```python
        params = {k: v for k, v in request.data.items() if k != 'result_name'}
        if kind == 'export_batch_charts':
            from apps.export.grouping import GroupingError, normalize_batch_grouping
            try:
                groups, max_items = normalize_batch_grouping(
                    params.get('groups'), params.get('max_items_per_sheet'),
                    params.get('params') or [], str(params.get('format', 'xlsx')))
            except GroupingError as exc:
                return error_response(exc.code, None, 400, field=exc.field)
            if groups:
                params['groups'] = groups
                params['max_items_per_sheet'] = max_items
            else:
                params.pop('groups', None)
                params.pop('max_items_per_sheet', None)
```

`runner.py::run_export_batch_charts`（仅 xlsx 分支）：

```python
        payload = build_batch_charts_xlsx_with_charts(
            df, metadata, params, site_col=get_site_column(df), **show,
            dpi=task['dpi'], cpk_thresholds=thresholds,
            workers=1, progress_cb=_cb,
            groups=task.get('groups'),
            max_items_per_sheet=task.get('max_items_per_sheet', 50))
```

`frontend/src/utils/error.ts` 的 `ERROR_CODE_MAP` 追加：

```ts
  invalid_groups: '测试项归类无效，请检查后重试',
  invalid_page_size: '每页测试项数不合法',
  groups_not_supported: 'PPT 格式不支持测试项归类',
```

- [x] **Step 4: 跑测试**

```bash
.venv/Scripts/python.exe manage.py test apps.jobs.tests_batch_groups apps.jobs.tests_jobs
```

- [x] **Step 5: 提交**

```bash
git add apps/jobs/views.py apps/jobs/executor.py apps/jobs/runner.py frontend/src/utils/error.ts apps/jobs/tests_batch_groups.py
git commit -m "feat(jobs): 批量导出作业透传测试项分组与页上限（含错误码）"
```

---

### Task 6: 归类 UI 与导出接线

**Files:**
- Create: `frontend/src/pages/data/components/export/ExportGroupingCard.vue`
- Modify: `frontend/src/pages/data/ExportToolsTab.vue`
- Modify: `frontend/src/pages/data/components/export/ExportChartConfig.vue:13`（步骤 2 → 3）
- Modify: `frontend/src/pages/data/components/export/ExportActions.vue:5`（步骤 3 → 4）
- Test: `frontend/e2e/exports/grouped-export.spec.ts`（新）

**Interfaces:**
- Consumes: Task 1 全部导出；后端请求字段 `groups` / `max_items_per_sheet`。
- Produces: 卡片 `v-model` 为 `GroupingConfig`；导出按钮请求携带分组（仅当 `hasGroupingRules` 为真）。

- [x] **Step 1: 写 e2e 失败测试（接线证明）**

```ts
// frontend/e2e/exports/grouped-export.spec.ts
import { expect, test } from '@playwright/test'

import { gotoApp } from '../helpers/nav'

test.describe('@p2 导出 - 测试项归类', { tag: ['@p2', '@exports'] }, () => {
  test('添加分类后批量导出 Excel：提交 202 且触发下载', async ({ page }) => {
    test.slow()
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '导出工具' }).click()

    const fileSelect = page.locator('.active-file-banner:visible .el-select').first()
    await fileSelect.click()
    const dropdown = page.locator('.el-select-dropdown:visible')
    const options = dropdown.locator('.el-select-dropdown__item:not(.is-disabled)')
    await expect(options.first()).toBeVisible({ timeout: 15_000 })
    const histogram = page.waitForResponse(
      (r) => /\/analysis\/histogram\/?/.test(new URL(r.url()).pathname) && r.status() === 200,
      { timeout: 15_000 }).catch(() => null)
    await options.first().click()
    await page.keyboard.press('Escape')
    await histogram

    const panel = page.locator('.export-tools')
    const paramSelect = panel.locator('.el-select').filter({ hasText: '点击选择要导出的参数' }).first()
    await paramSelect.click()
    const popper = page.locator('.el-select-dropdown:visible')
    const paramOptions = popper.locator('.el-select-dropdown__item:not(.is-disabled)')
    await expect(paramOptions.first()).toBeVisible({ timeout: 5_000 })
    const firstName = (await paramOptions.first().textContent())?.trim() ?? ''
    await paramOptions.first().click()
    await page.keyboard.press('Escape')
    await expect(popper).toBeHidden({ timeout: 5_000 })

    await page.getByTestId('export-group-add').click()
    await page.getByTestId('export-group-name').locator('input').fill('A')
    await page.getByTestId('export-group-pattern-text').first().locator('input')
      .fill(firstName.slice(0, Math.min(3, firstName.length)))
    await expect(page.getByTestId('export-grouping-preview')).toContainText(/A：\d+ 项/)

    const submitPromise = page.waitForResponse(
      (r) => r.url().includes('/jobs/export_batch_charts/'), { timeout: 180_000 })
    const downloadPromise = page.waitForEvent('download', { timeout: 180_000 }).catch(() => null)
    await page.getByRole('button', { name: /批量导出 Excel/ }).click()
    const submit = await submitPromise
    expect(submit.status(), '提交批量导出作业应 202').toBe(202)
    const download = await downloadPromise
    if (download) expect(download.suggestedFilename().toLowerCase()).toMatch(/\.xlsx$/)
  })
})
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd frontend && E2E_PORT=<空闲> E2E_FRONTEND_PORT=<空闲> npx playwright test e2e/exports/grouped-export.spec.ts --project=P1 --workers=1
```

预期：FAIL（找不到 `export-group-add`）。

- [x] **Step 3: 写卡片组件**

```vue
<!-- frontend/src/pages/data/components/export/ExportGroupingCard.vue -->
<template>
  <div class="step-card">
    <div class="step-header">
      <span class="step-number">2</span>
      <span class="step-title">测试项归类</span>
      <span class="step-hint">可选：按名字前缀/后缀/包含分组；每类按页上限装箱</span>
    </div>
    <div class="step-body">
      <div class="grouping-globals">
        <el-select :model-value="modelValue.strategy" size="small" aria-label="归类冲突策略"
                   class="strategy-select" @update:model-value="patch({ strategy: $event })">
          <el-option value="first" label="首个命中（推荐）" />
          <el-option value="specific" label="最具体优先" />
          <el-option value="multi" label="允许一个参数多属" />
        </el-select>
        <span class="bw-label">每页最多</span>
        <el-select :model-value="modelValue.maxItemsPerSheet" size="small" aria-label="每页最多测试项数"
                   class="max-select" @update:model-value="patch({ maxItemsPerSheet: $event })">
          <el-option v-for="n in MAX_ITEMS_OPTIONS" :key="n" :value="n" :label="`${n} 项`" />
        </el-select>
      </div>

      <div v-for="(group, gi) in modelValue.groups" :key="group.id" class="group-row">
        <div class="group-head">
          <el-input :model-value="group.name" size="small" placeholder="分类名，如 LKG"
                    aria-label="分类名" data-testid="export-group-name" class="group-name"
                    @update:model-value="updateGroup(gi, { name: $event })" />
          <el-button size="small" link :disabled="gi === 0" @click="moveGroup(gi, -1)">上移</el-button>
          <el-button size="small" link :disabled="gi === modelValue.groups.length - 1"
                     @click="moveGroup(gi, 1)">下移</el-button>
          <el-button size="small" link @click="removeGroup(gi)">删除分类</el-button>
        </div>
        <div v-for="(pattern, pi) in group.patterns" :key="pi" class="pattern-row">
          <el-select :model-value="pattern.type" size="small" aria-label="条件类型" class="pattern-type"
                     @update:model-value="updatePattern(gi, pi, { type: $event })">
            <el-option value="prefix" label="前缀" />
            <el-option value="suffix" label="后缀" />
            <el-option value="contains" label="包含" />
          </el-select>
          <el-input :model-value="pattern.text" size="small" placeholder="匹配文本"
                    aria-label="匹配文本" data-testid="export-group-pattern-text" class="pattern-text"
                    @update:model-value="updatePattern(gi, pi, { text: $event })" />
          <el-button size="small" link @click="removePattern(gi, pi)">删除条件</el-button>
        </div>
        <el-button size="small" link data-testid="export-group-add-pattern" @click="addPattern(gi)">+ 条件</el-button>
      </div>

      <el-button size="small" data-testid="export-group-add" @click="addGroup">+ 添加分类</el-button>

      <div class="preview" data-testid="export-grouping-preview">
        <div v-for="group in preview.groups" :key="group.name" class="preview-line">
          {{ group.name }}：{{ group.params.length }} 项<template v-if="group.params.length">
            （{{ group.params.slice(0, 3).join(', ') }}<template v-if="group.params.length > 3">…</template>）</template>
        </div>
        <div class="preview-meta">
          预计 {{ preview.sheets }} 张 sheet · 约 {{ preview.seconds }}s · {{ preview.size }}
          <template v-if="preview.conflicts"> · 冲突 {{ preview.conflicts }} 项</template>
        </div>
      </div>

      <div class="grouping-help">
        匹配不区分大小写；同一分类内多个条件是「或」；未命中的测试项进「其他」；冲突策略决定一个测试项命中多个分类时归哪边。
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

import {
  DEFAULT_MAX_ITEMS, MAX_ITEMS_OPTIONS, countConflicts, estimateSheetCount,
  newGroupId, resolveGroups, type GroupingConfig, type GroupPattern,
} from '../../composables/exportGrouping'

const props = defineProps<{ modelValue: GroupingConfig; params: string[] }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: GroupingConfig): void }>()

function patch(part: Partial<GroupingConfig>) {
  emit('update:modelValue', { ...props.modelValue, ...part })
}
function replaceGroups(groups: GroupingConfig['groups']) {
  patch({ groups })
}
function addGroup() {
  replaceGroups([...props.modelValue.groups, { id: newGroupId(), name: '', patterns: [{ type: 'prefix', text: '' }] }])
}
function removeGroup(index: number) {
  replaceGroups(props.modelValue.groups.filter((_g, i) => i !== index))
}
function moveGroup(index: number, delta: number) {
  const groups = [...props.modelValue.groups]
  const target = index + delta
  if (target < 0 || target >= groups.length) return
  ;[groups[index], groups[target]] = [groups[target], groups[index]]
  replaceGroups(groups)
}
function updateGroup(index: number, part: Partial<GroupingConfig['groups'][number]>) {
  replaceGroups(props.modelValue.groups.map((g, i) => (i === index ? { ...g, ...part } : g)))
}
function addPattern(groupIndex: number) {
  const group = props.modelValue.groups[groupIndex]
  updateGroup(groupIndex, { patterns: [...group.patterns, { type: 'prefix', text: '' }] })
}
function removePattern(groupIndex: number, patternIndex: number) {
  const group = props.modelValue.groups[groupIndex]
  updateGroup(groupIndex, { patterns: group.patterns.filter((_p, i) => i !== patternIndex) })
}
function updatePattern(groupIndex: number, patternIndex: number, part: Partial<GroupPattern>) {
  const group = props.modelValue.groups[groupIndex]
  updateGroup(groupIndex, {
    patterns: group.patterns.map((p, i) => (i === patternIndex ? { ...p, ...part } : p)),
  })
}

const preview = computed(() => {
  const groups = resolveGroups(props.params, props.modelValue.groups, props.modelValue.strategy)
  const cap = props.modelValue.maxItemsPerSheet || DEFAULT_MAX_ITEMS
  const count = props.params.length
  return {
    groups,
    sheets: estimateSheetCount(groups, cap),
    conflicts: countConflicts(props.params, props.modelValue.groups),
    seconds: Math.max(1, Math.round((count * 232) / 1000)),
    size: `${(count * 45 / 1024).toFixed(1)} MB`,
  }
})
</script>

<style scoped>
.step-card { background: var(--bg-2); border: 1px solid var(--border); border-radius: 10px; }
.step-header { display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid var(--border); }
.step-number { width: 22px; height: 22px; border-radius: 50%; background: var(--brand); color: var(--text-inverse); display: inline-flex; align-items: center; justify-content: center; font-size: var(--p-fs-dense); font-weight: 700; }
.step-title { font-size: var(--p-fs-small); font-weight: 600; color: var(--text); }
.step-hint { margin-left: auto; font-size: var(--p-fs-micro); color: var(--text-3); }
.step-body { padding: 12px 16px; display: flex; flex-direction: column; gap: 10px; }
.grouping-globals { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.strategy-select { width: 180px; }
.max-select { width: 100px; }
.bw-label { font-size: var(--p-fs-dense); color: var(--text-2); }
.group-row { border: 1px dashed var(--border); border-radius: 8px; padding: 8px; display: flex; flex-direction: column; gap: 6px; }
.group-head, .pattern-row { display: flex; align-items: center; gap: 6px; }
.group-name { width: 180px; }
.pattern-type { width: 90px; }
.pattern-text { width: 220px; }
.preview { font-size: var(--p-fs-dense); color: var(--text-2); display: flex; flex-direction: column; gap: 2px; }
.preview-meta { color: var(--text-3); }
.grouping-help { font-size: var(--p-fs-micro); color: var(--text-3); line-height: 1.5; }
</style>
```

- [x] **Step 4: 接线 `ExportToolsTab.vue`**

在现有引用后追加：

```ts
import ExportGroupingCard from './components/export/ExportGroupingCard.vue'
import { safeGetItem, safeSetItem } from '../../utils/safeStorage'
import {
  defaultGroupingConfig, hasGroupingRules, parseGroupingConfig, resolveGroups,
  type GroupingConfig,
} from './composables/exportGrouping'

const GROUPING_KEY = (fileId: number | null) => `lqdp.export.grouping.${fileId ?? 'none'}`

const grouping = ref<GroupingConfig>(parseGroupingConfig(
  props.fileId ? safeGetItem(GROUPING_KEY(props.fileId)) : null))

watch(() => props.fileId, (fileId) => {
  grouping.value = parseGroupingConfig(fileId ? safeGetItem(GROUPING_KEY(fileId)) : null)
}, { immediate: false })

watch(grouping, (value) => {
  if (props.fileId) safeSetItem(GROUPING_KEY(props.fileId), JSON.stringify(value))
}, { deep: true })
```

模板中在 `ExportParamSelector` 之后插入：

```vue
<ExportGroupingCard v-model="grouping" :params="localParams" />
```

`onExportBatch` 的 options 先显式标成可扩展对象，再追加分组：

```ts
  const options: Record<string, any> = {
    show_limit: chartConfig.value.includes('limit'),
    show_3sigma: chartConfig.value.includes('s3'),
    show_4sigma: chartConfig.value.includes('s4'),
    show_6sigma: chartConfig.value.includes('s6'),
    show_normal: chartConfig.value.includes('normal'),
    show_kde: chartConfig.value.includes('kde'),
  }
  if (hasGroupingRules(grouping.value)) {
    options.groups = resolveGroups(localParams.value, grouping.value.groups, grouping.value.strategy)
    options.max_items_per_sheet = grouping.value.maxItemsPerSheet
  }
```

（`options` 类型为 `Record<string, any>`；`useExport` 已把 options 展开进作业 payload，无需改。）

步骤号：`ExportChartConfig.vue` 的 `<span class="step-number">2</span>` → `3`；`ExportActions.vue` 的 `3` → `4`。

- [x] **Step 5: 跑测试**

```bash
cd frontend && npx vitest run test/unit/exportGrouping.spec.ts && npm run lint:e2e
E2E_PORT=<空闲> E2E_FRONTEND_PORT=<空闲> npx playwright test e2e/exports/grouped-export.spec.ts --project=P1 --workers=1
```

预期：PASS。

- [x] **Step 6: 提交**

```bash
git add frontend/src/pages/data/components/export/ExportGroupingCard.vue \
  frontend/src/pages/data/ExportToolsTab.vue \
  frontend/src/pages/data/components/export/ExportChartConfig.vue \
  frontend/src/pages/data/components/export/ExportActions.vue \
  frontend/e2e/exports/grouped-export.spec.ts
git commit -m "feat(export): 测试项归类 UI 与导出接线（规则仅存 localStorage）"
```

---

### Task 7: 收口门禁与文档

**Files:** 无新增源码（可能补 `docs/tasks/todo.md` 台账，按项目约定）。

- [x] **Step 1: 后端定向 + 全量受影响档**

```bash
.venv/Scripts/python.exe manage.py test apps.export apps.jobs apps.weight test.backend
cd frontend && npm run test:e2e:affected
```

判绿看末行 `RESULT:`，不看 `$?`。

- [x] **Step 2: 浏览器定向档（分类导出）**

```bash
cd frontend && E2E_PORT=<空闲> E2E_FRONTEND_PORT=<空闲> npx playwright test e2e/exports --project=P1 --workers=2
```

- [x] **Step 3: 提交收口记录（若项目要求）**

在 `docs/tasks/todo.md` 追加本批台账（完成项、门禁数字、残余风险），提交：

```bash
git add docs/tasks/todo.md
git commit -m "docs(export): 归类与分页批次台账"
```

---

## Self-Review（写完计划后的自查）

- **Spec coverage**：§4 匹配/策略 → Task 1；§4.3 预览 → Task 1+6；§5 UI/持久化 → Task 6；§6 契约 → Task 2+5；
  §7 版式/锚点/分类列 → Task 3+4；§8 测试 → 各任务 + Task 7；§10 风险 → 已在 spec，无需代码。
- **Placeholder scan**：无 TBD/TODO；所有代码步骤给了可落盘内容。
- **Type consistency**：`GroupingConfig`/`GroupRule` 在 Task 1 定义，Task 6 按同名使用；
  `normalize_batch_grouping` 在 Task 2 定义、Task 5 消费；`groups`/`max_items_per_sheet` 字段名贯穿前后端。
