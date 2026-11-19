# 批4 刀五a：useSelectFilter 抽取 + 相关性 X/Y 迁 v2 + clearFilterInput 判据 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把三族 v2 下拉的九个同名符号（`kw` / `matches` / `filterMethod` / `clearFilterInput` / `onSelectKeydown` / `onVisibleChange` / `selectAll` / `clearAll` / `selectMatches`）抽成 `useSelectFilter`；把相关性页两颗未封顶 X/Y v1 下拉迁到 `el-select-v2` 虚拟化；给 `clearFilterInput` 补一条真正承重的 T3。

**Architecture:** 新 composable 放 `frontend/src/pages/data/composables/useSelectFilter.ts`（不放 `src/composables/`，否则命中 GLOBAL）。三族差异收敛成 options：`source`/`selected`/`onChange`/`limit`/`focusOnOpen`；模板与 `#empty`/footer 槽全部不动。X/Y 单选用 `el-select-v2` + `toOptions`，不接 `useSelectFilter`（没有多选并集/Enter 全选语义）。

**Tech Stack:** Vue 3 + Element Plus 2.14（`el-select-v2`）+ Vitest（node 环境）+ Playwright。

**Spec:** `docs/superpowers/specs/2026-11-13-ux-batch-dropdown-admin-dedup-intro-usage-design.md` §2.3/§2.9；批1 台账 `docs/tasks/todo.md`「记账不做」段（九符号清单）；门禁见 `docs/reference/testing-gates.md`。

## Global Constraints

- **600 行**：`CorrelationToolsTab.vue` 现 551 行，迁移后必须仍 < 600；三族迁移后行数应下降。
- **不碰全局档路径**：不改 `frontend/src/composables/`、`frontend/src/utils/`、`frontend/e2e/helpers/`、`frontend/e2e/fixtures/`；新 composable 与测试都在 `pages/data/` 下。
- **不重引 `DROPDOWN_RENDER_CAP`**（已删除）；v2 用 `el-select-v2` 虚拟化。
- **每实例 popper-class 必填**；e2e 选择器沿用 `.dp-xxx:visible .el-select-dropdown__item`。
- **双主题**：不新增颜色；X/Y 的 `style="width:100%"` 与既有 token 规则保留。
- **out of scope**：`components/common/FileSelect.vue` 虚拟化、`SftpSearchPage` run-history 下拉、`CombineBatchDialog` 批次下拉、`view-data.spec.ts:1474` 几何 flake——都不在本刀顺手改。
- **分支**：从 master（当前 `c6f8bf9`）另开 `feature/batch4d-knife5a-select-filter`；不 push；收口全量池 + 后端全套。

## File Structure

- `frontend/src/pages/data/composables/useSelectFilter.ts`（新建）：九符号唯一实现。
- `frontend/test/unit/useSelectFilter.spec.ts`（新建）：纯函数/回调/DOM 契约 T2。
- `frontend/src/pages/data/components/correlation/SerialSelector.vue`：删 75-166 九符号，改 destructure。
- `frontend/src/pages/data/components/browser/TestColumnSelector.vue`：删 72-149。
- `frontend/src/pages/data/components/export/ExportParamSelector.vue`：删 60-136；**不加** `#empty`。
- `frontend/src/pages/analysis/components/CorrelationToolsTab.vue`：X/Y 两处 `el-select` → `el-select-v2`。
- `frontend/e2e/data/file-correlation.spec.ts`：`clearFilterInput` T3。
- `docs/tasks/todo.md`：本刀台账。

---

### Task 1: `clearFilterInput` 的 T3（先钉现状，再做重构）

**Files:**
- Modify: `frontend/e2e/data/file-correlation.spec.ts`

**为什么先做**：这是 characterization test。EP v2 自己在关闭/打开时会清 `states.inputValue`，所以「input 为空」没有牙齿；真正会泄漏的是组件自己的 `kw`，症状是重开后 `#empty` 槽仍显示「无匹配序列」。这条先对**未改代码**跑绿，再用变异（注释掉关闭分支的 `clearFilterInput()`）证红。

- [ ] **Step 0: 从 master 开分支**

```bash
git switch -c feature/batch4d-knife5a-select-filter master
```

Expected: `Switched to a new branch 'feature/batch4d-knife5a-select-filter'`

- [ ] **Step 1: 在现有序列用例的 Escape 之后插入判据**

在 `序列勾选：搜索 Enter 全选匹配 / 清空 → 仅对比 Limit` 用例中，找到 `await page.keyboard.press('Escape')`（关闭关键词面板那一步）之后、下一段交互之前，插入（变量名用该文件已有的 `serialSel` / `serialPopper` / `section` / `MAX_WINDOW_ROWS` / `windowItems` / `expectWindowRows`；若名称不同按现有文件改）：

```ts
    /*
     * clearFilterInput 判据（刀五a）：关掉再打开，关键词不得残留。
     * 只判 kw 派生的 UI：EP v2 收起时自己清 inputValue ⇒「input 为空」没有牙齿。
     * 序列是 number[]，字母关键词永不命中；重开后 .empty-hint 必须消失。
     */
    const NO_MATCH_QUERY = 'zzzz'
    await serialSel.click()
    await expect(serialPopper).toBeVisible()
    await page.keyboard.type(NO_MATCH_QUERY)
    await expect(serialPopper.locator('.empty-hint')).toBeVisible()
    await section.locator('.fc-serial-hint').click()          // 点外部关闭 → visible-change(false)
    await expect(serialPopper).toBeHidden()
    await serialSel.click()
    await expect(serialPopper).toBeVisible()
    await expect(serialPopper.locator('.empty-hint')).toHaveCount(0)   // ← 承重：kw 未残留
    await expect(serialPopper.locator('.match-hint')).toHaveCount(0)
    await expect(serialSel.locator('input').first()).toHaveValue('')   // 辅助（EP 自己也会清）
    const totalSerials = Number(/共 (\d+) 颗/.exec(
      (await section.locator('.fc-serial-hint').textContent()) ?? '')?.[1])
    expect(totalSerials, '候选数须大于窗口界，否则上面那条没有牙齿').toBeGreaterThan(MAX_WINDOW_ROWS)
    await expectWindowRows(windowItems(page, SERIAL_POPPER), totalSerials, '序列下拉（关后重开，应无残留过滤）')
    await page.keyboard.press('Escape')                       // 空关键词 ⇒ EP 真的收起面板
```

注意：`SERIAL_POPPER`/`windowItems` 若文件里已有对应常量/助手，按现有名称；若没有，用该文件既有的可见选项定位方式，不要新开 helper。

- [ ] **Step 2: 跑用例**

```bash
cd frontend && E2E_PORT=21061 E2E_FRONTEND_PORT=22061 npx playwright test e2e/data/file-correlation.spec.ts --project=P1 --workers=1
```

Expected: 绿（现状的 `clearFilterInput` 已知会在关闭时清 `kw`）。

- [ ] **Step 3: 变异自证**

把 `onVisibleChange(false)` 里的 `clearFilterInput()` 临时注释掉，重跑 Step 2。Expected: 红在 `.empty-hint` 的 `toHaveCount(0)`（或紧随的 `match-hint`）。从备份/编辑还原后再跑绿。报告必须写 RED/GREEN 两段。

- [ ] **Step 4: 提交**

```bash
git add frontend/e2e/data/file-correlation.spec.ts
git commit -m "test(e2e): 钉住序列下拉关后重开无残留过滤"
```

---

### Task 2: `useSelectFilter` + SerialSelector

**Files:**
- Create: `frontend/src/pages/data/composables/useSelectFilter.ts`
- Create: `frontend/test/unit/useSelectFilter.spec.ts`
- Modify: `frontend/src/pages/data/components/correlation/SerialSelector.vue`

- [ ] **Step 1: 写 T2（先红）**

新建 `frontend/test/unit/useSelectFilter.spec.ts`：

```ts
import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useSelectFilter } from '../../src/pages/data/composables/useSelectFilter'

function mount<T extends string | number>(src: T[], sel: T[], limit?: number) {
  const source = ref(src) as { value: T[] }
  const selected = ref(sel) as { value: T[] }
  const emitted: T[][] = []
  const api = useSelectFilter<T>({
    source: () => source.value,
    selected: () => selected.value,
    onChange: (v) => emitted.push(v),
    limit,
  })
  return { api, source, selected, emitted }
}

describe('useSelectFilter', () => {
  it('kw 去空白并转小写', () => {
    const { api } = mount(['A', 'B'], [])
    api.filterMethod('  A b ')
    expect(api.kw.value).toBe('a b')
  })

  it('空关键词的 matches 是空数组，不是全量', () => {
    const { api } = mount(['A', 'B'], [])
    expect(api.matches.value).toEqual([])
  })

  it('matches 大小写不敏感，数字按子串匹配', () => {
    const { api } = mount<string>(['Alpha', 'Beta'], [])
    api.filterMethod('al')
    expect(api.matches.value).toEqual(['Alpha'])
    const nums = mount<number>([10123, 20000], [])
    nums.api.filterMethod('012')
    expect(nums.api.matches.value).toEqual([10123])
  })

  it('selectOptions 无关键词给全集，有关键词给匹配集', () => {
    const { api } = mount(['Alpha', 'Beta'], [])
    expect(api.selectOptions.value.map((o) => o.value)).toEqual(['Alpha', 'Beta'])
    api.filterMethod('be')
    expect(api.selectOptions.value.map((o) => o.value)).toEqual(['Beta'])
  })

  it('selectAll 尊重 limit', () => {
    const many = Array.from({ length: 250 }, (_, i) => i)
    const { api, emitted } = mount(many, [], 200)
    api.selectAll()
    expect(emitted[0]).toHaveLength(200)
  })

  it('clearAll 发空数组', () => {
    const { api, emitted } = mount(['A'], ['A'])
    api.clearAll()
    expect(emitted[0]).toEqual([])
  })

  it('selectMatches 并集去重、已选在前；空/无匹配不发', () => {
    const { api, emitted } = mount([5, 7, 9], [5])
    api.filterMethod('7')
    api.selectMatches()
    expect(emitted[0]).toEqual([5, 7])
    api.filterMethod('zzz')
    api.selectMatches()
    expect(emitted).toHaveLength(1)
  })

  it('Enter 只在有匹配时拦截并全选', () => {
    const { api, emitted } = mount(['Alpha'], [])
    const ev = { key: 'Enter', preventDefault: vi.fn(), stopPropagation: vi.fn() }
    api.filterMethod('al')
    api.onSelectKeydown(ev as unknown as KeyboardEvent)
    expect(ev.preventDefault).toHaveBeenCalled()
    expect(emitted[0]).toEqual(['Alpha'])
    const ev2 = { key: 'Enter', preventDefault: vi.fn(), stopPropagation: vi.fn() }
    api.filterMethod('zzz')
    api.onSelectKeydown(ev2 as unknown as KeyboardEvent)
    expect(ev2.preventDefault).not.toHaveBeenCalled()
  })

  it('关闭时清空 kw；无 selectRef 时打开不抛', () => {
    const { api } = mount(['A'], [])
    api.filterMethod('a')
    api.onVisibleChange(false)
    expect(api.kw.value).toBe('')
    expect(() => api.onVisibleChange(true)).not.toThrow()
  })

  it('clearFilterInput 同步 EP 内部 input（DOM 契约）', () => {
    const { api } = mount(['A'], [])
    const fakeInput = { value: '1', dispatchEvent: vi.fn() }
    api.selectRef.value = { $el: { querySelector: () => fakeInput } } as unknown as typeof api.selectRef.value
    api.filterMethod('a')
    api.clearFilterInput()
    expect(api.kw.value).toBe('')
    expect(fakeInput.value).toBe('')
    expect(fakeInput.dispatchEvent).toHaveBeenCalledTimes(1)
    const event = fakeInput.dispatchEvent.mock.calls[0][0] as Event
    expect(event.type).toBe('input')
    expect(event.bubbles).toBe(true)
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run test/unit/useSelectFilter.spec.ts
```

Expected: FAIL（模块不存在）。

- [ ] **Step 3: 写 composable**

新建 `frontend/src/pages/data/composables/useSelectFilter.ts`：

```ts
import { computed, nextTick, ref, type ComputedRef, type Ref } from 'vue'
import { filterByKeyword, toOptions, type SelectOption } from '../../../utils/selectOptions'

interface SelectElLike { $el?: HTMLElement }

export interface UseSelectFilterOptions<T extends string | number> {
  source: () => T[]
  selected: () => T[]
  onChange: (value: T[]) => void
  limit?: number
  focusOnOpen?: boolean
}

export interface UseSelectFilterReturn<T extends string | number> {
  selectRef: Ref<SelectElLike | undefined>
  kw: ComputedRef<string>
  matches: ComputedRef<T[]>
  selectOptions: ComputedRef<SelectOption[]>
  filterMethod: (query: string) => void
  clearFilterInput: () => void
  onVisibleChange: (visible: boolean) => void
  onSelectKeydown: (event: KeyboardEvent) => void
  selectAll: () => void
  clearAll: () => void
  selectMatches: () => void
}

export function useSelectFilter<T extends string | number>(
  opts: UseSelectFilterOptions<T>,
): UseSelectFilterReturn<T> {
  const filterText = ref('')
  const selectRef = ref<SelectElLike>()

  const kw = computed(() => filterText.value.trim().toLowerCase())

  /** 空关键词必须自己给 []：filterByKeyword 空串返回入参本身（引用契约），
   *  透传会把「没输入」变成「全匹配」⇒ footer 谎报 + Enter 变成全选全集 */
  const matches = computed<T[]>(() =>
    kw.value ? filterByKeyword(opts.source(), filterText.value) : [])

  /** v2 的 filter-method 不过滤（useSelect.mjs:114-132）⇒ 预过滤 */
  const selectOptions = computed(() =>
    toOptions(kw.value ? matches.value : opts.source()))

  const applyLimit = (list: T[]): T[] =>
    opts.limit != null && list.length > opts.limit ? list.slice(0, opts.limit) : list

  const filterInput = (): HTMLInputElement | null | undefined =>
    selectRef.value?.$el?.querySelector('input')

  const clearFilterInput = () => {
    filterText.value = ''
    const input = filterInput()
    if (input) {
      input.value = ''
      input.dispatchEvent(new Event('input', { bubbles: true }))
    }
  }

  const filterMethod = (query: string) => { filterText.value = query }

  const selectMatches = () => {
    if (matches.value.length === 0) return
    opts.onChange(applyLimit([...new Set<T>([...opts.selected(), ...matches.value])]))
    clearFilterInput()
  }

  const onSelectKeydown = (event: KeyboardEvent) => {
    if (event.key === 'Enter' && matches.value.length > 0) {
      event.preventDefault()
      event.stopPropagation()
      selectMatches()
    }
  }

  const onVisibleChange = (visible: boolean) => {
    if (!visible) return clearFilterInput()
    if (opts.focusOnOpen) nextTick(() => filterInput()?.focus())
  }

  const selectAll = () => opts.onChange(applyLimit([...opts.source()]))
  const clearAll = () => opts.onChange([])

  return { selectRef, kw, matches, selectOptions, filterMethod,
           clearFilterInput, onVisibleChange, onSelectKeydown, selectAll, clearAll, selectMatches }
}
```

- [ ] **Step 4: 跑 T2 确认通过**

```bash
cd frontend && npx vitest run test/unit/useSelectFilter.spec.ts
```

Expected: `Tests 10 passed (10)`（或实际条数）。

- [ ] **Step 5: 迁移 SerialSelector**

`SerialSelector.vue` 删除第 75-166 行附近的九符号定义；保留文件头注释与 `MAX_SELECTED`；把 `selectRef` 改为从 composable destructure：

```ts
import { useSelectFilter } from '../../composables/useSelectFilter'

/** 已选上限（el-table 无列虚拟化：200 × 4 列 ≈ 800 列已到现实极限） */
const MAX_SELECTED = 200

const { selectRef, kw, matches, selectOptions, filterMethod,
        onSelectKeydown, onVisibleChange, selectAll, clearAll } =
  useSelectFilter<number>({
    source: () => props.options,
    selected: () => props.modelValue,
    onChange: (v) => emit('update:modelValue', v),
    limit: MAX_SELECTED,
    focusOnOpen: true,
  })
```

模板不动（`ref="selectRef"`、`#empty`、footer 的按钮/hint 都沿用）。`clearFilterInput` / `selectMatches` 不 destructure（内部使用）。

- [ ] **Step 6: 构建与用例**

```bash
cd frontend && npm run build
cd frontend && npm run lint:e2e
cd frontend && E2E_PORT=21061 E2E_FRONTEND_PORT=22061 npx playwright test e2e/data/file-correlation.spec.ts --project=P1 --workers=1
```

Expected: build 无 TS 诊断；lint 0；序列用例绿（Task 1 的 T3 仍绿）。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/pages/data/composables/useSelectFilter.ts frontend/test/unit/useSelectFilter.spec.ts frontend/src/pages/data/components/correlation/SerialSelector.vue
git commit -m "refactor(data): 抽出 useSelectFilter 并迁移 SerialSelector"
```

---

### Task 3: TestColumnSelector + ExportParamSelector

**Files:**
- Modify: `frontend/src/pages/data/components/browser/TestColumnSelector.vue`
- Modify: `frontend/src/pages/data/components/export/ExportParamSelector.vue`

- [ ] **Step 1: 迁移 TestColumnSelector**

删除九符号块（约 72-149）；destructure：

```ts
const { selectRef, kw, matches, selectOptions, filterMethod,
        onSelectKeydown, onVisibleChange, selectAll, clearAll } =
  useSelectFilter<string>({
    source: () => props.cols,
    selected: () => props.modelValue,
    onChange: (v) => emit('update:modelValue', v),
  })
```

模板不动（`#empty`、`#footer` 按钮/hint 沿用）。

- [ ] **Step 2: 迁移 ExportParamSelector**

删除九符号块（约 60-136）；`source: () => props.params`；其余同上。**不加 `#empty`**（既有缺口，另单）。

- [ ] **Step 3: 验证**

```bash
cd frontend && npm run build
cd frontend && npx vitest run
cd frontend && E2E_PORT=21061 E2E_FRONTEND_PORT=22061 npx playwright test e2e/data/view-data.spec.ts e2e/data/exports.spec.ts --project=P1 --workers=1
```

Expected: build/lint 绿；相关用例绿。行数检查：两文件均 < 600。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/pages/data/components/browser/TestColumnSelector.vue frontend/src/pages/data/components/export/ExportParamSelector.vue
git commit -m "refactor(data): 测试列/导出参数下拉改用 useSelectFilter"
```

---

### Task 4: 相关性 X/Y → `el-select-v2`

**Files:**
- Modify: `frontend/src/pages/analysis/components/CorrelationToolsTab.vue`

- [ ] **Step 1: 写/确认失败判据**

先跑现有相关性用例（不改代码）：

```bash
cd frontend && E2E_PORT=21061 E2E_FRONTEND_PORT=22061 npx playwright test e2e/analysis/correlation-inline.spec.ts --project=P1 --workers=1
```

Expected: 绿（作为基线）。v1 未封顶的缺陷是「全量 option 挂载」；本步的判据是迁移后同一用例仍绿且 X/Y 可选中。

- [ ] **Step 2: 迁移模板**

`CorrelationToolsTab.vue` 的 X/Y 两处 `el-select` 改为：

```vue
      <el-select-v2
        v-model="localX"
        :options="axisOptions"
        filterable
        placeholder="选择 X 轴参数"
        popper-class="dp-corr-x-popper"
        style="width: 100%"
      />
```

Y 同理（`localY`、`dp-corr-y-popper`）。

- [ ] **Step 3: 加 options**

脚本加：

```ts
import { toOptions } from '../../../utils/selectOptions'

/** X/Y 两颗未封顶 v1 下拉 → v2（§2.9 收尾）。不传 filter-method，走 EP 内置 label 过滤。 */
const axisOptions = computed(() => toOptions(params.value))
```

`params` 是组件已有的参数列表来源；按文件实际类型取 `.value`。

- [ ] **Step 4: 验证**

```bash
cd frontend && npm run build
cd frontend && E2E_PORT=21061 E2E_FRONTEND_PORT=22061 npx playwright test e2e/analysis/correlation-inline.spec.ts e2e/analysis/correlation-file-switch-reset.spec.ts e2e/analysis/axis-label-precision.spec.ts --project=P1 --workers=1
```

Expected: 绿。若 `KELVIN_SW` 因虚拟窗口落点红，**只改该 spec**：打开下拉后向 filter input 输入关键词再点，不改共享 `pickOption`。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/analysis/components/CorrelationToolsTab.vue
git commit -m "perf(analysis): 相关性 X/Y 下拉迁 el-select-v2"
```

---

### Task 5: 台账与全量门禁

**Files:**
- Modify: `docs/tasks/todo.md`

- [ ] **Step 1: 追加本刀条目**

```markdown
# 任务：批4 刀五a（useSelectFilter + X/Y 迁 v2 + clearFilterInput，2026-11-17）

设计：`docs/superpowers/specs/2026-11-13-ux-batch-dropdown-admin-dedup-intro-usage-design.md` §2.3/§2.9
计划：`docs/superpowers/plans/2026-11-17-batch4d-knife5a-select-filter.md`

## 勾选清单

- [ ] clearFilterInput T3（关后重开无残留过滤）
- [ ] useSelectFilter 抽取 + SerialSelector
- [ ] TestColumnSelector + ExportParamSelector
- [ ] 相关性 X/Y 迁 el-select-v2
- [ ] 全量门禁
- [ ] 并入 master（需用户点头；不 push）

## 门禁记录

| 档 | 命令 | 实测判据行 |
|---|---|---|
| 序列 T3 | `npx playwright test e2e/data/file-correlation.spec.ts --project=P1 --workers=1` | |
| T2 | `npx vitest run test/unit/useSelectFilter.spec.ts` | |
| 全量 vitest | `npx vitest run` | |
| e2e 类型 | `npm run lint:e2e` | |
| 前端构建 | `npm run build` | |
| 相关性 X/Y | `npx playwright test e2e/analysis/{correlation-inline,correlation-file-switch-reset,axis-label-precision}.spec.ts --project=P1 --workers=1` | |
| 全量池 | `node scripts/e2e_pool.mjs --slots=4` | |
| 后端全套 | `manage.py test` | |
```

- [ ] **Step 2: 全量门禁**

```bash
cd frontend && npx vitest run
cd frontend && npm run lint:e2e
cd frontend && npm run build
node scripts/e2e_pool.mjs --slots=4
CODEBUDDY_SAFE_DELETE_ENABLED=0 .venv/Scripts/python.exe -X utf8 manage.py test
```

一条命令一档；池与后端可并行。填表取原文；判绿取末尾判据行。

- [ ] **Step 3: 提交与并入（需用户点头；不 push）**

```bash
git add docs/tasks/todo.md docs/superpowers/plans/2026-11-17-batch4d-knife5a-select-filter.md
git commit -m "docs(todo): 批4 刀五a 收口门禁"
git merge-base --is-ancestor master HEAD
git switch master
git merge --ff-only feature/batch4d-knife5a-select-filter
git branch -d feature/batch4d-knife5a-select-filter
git status --short
```

---

## 自审

**Spec 覆盖**：九符号抽取（Task 2/3）、X/Y 未封顶下拉（Task 4）、`clearFilterInput` 零判据（Task 1）、全量门禁（Task 5）。

**Out of scope**：`FileSelect.vue` 虚拟化、`view-data:1474` 几何 flake、`SftpSearchPage`/`CombineBatchDialog` 下拉——单独小刀。

**类型一致**：composable 的 `source/selected/onChange` 与三组件 props/emit 对齐；`limit` 只给 Serial；`focusOnOpen` 只给 Serial；X/Y 不接 composable（单选无多选语义）。`el-select-v2` 的 `popper-class` 实例级身份不变。
