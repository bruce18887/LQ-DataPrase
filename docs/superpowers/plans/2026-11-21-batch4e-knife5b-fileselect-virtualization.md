# 批4 刀五b：FileSelect 虚拟化 + 下拉收尾 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `FileSelect.vue` 从 v1 `el-select + v-for` 迁到 `el-select-v2` 虚拟化（真实候选上限 5000/9999），顺手收掉 `CombineBatchDialog` 的未封顶批次下拉、判掉 `SftpSearchPage` 运行历史（实际封顶 20）并收尾刀五a 的测试挂账。

**Architecture:** FileSelect 的过滤/排序/置顶/元信息抽成纯函数模块 `fileSelectModel.ts`（T2 覆盖），组件模板迁 v2：`:options` 喂预过滤后的对象数组，`#default` 逐行渲染富信息行与高亮片段，`item-height` 按 `showMeta` 取 48/34。删掉零消费者的 `groupBy` 分组分支；保留多选置顶、`mark` 高亮、`dp-file-option__*` 类名与 `.dp-file-select-dropdown` 实例类。

**Tech Stack:** Vue 3 + Element Plus 2.14（`el-select-v2`）+ Vitest（node 环境）+ Playwright。

**Spec:** `docs/superpowers/specs/2026-11-13-ux-batch-dropdown-admin-dedup-intro-usage-design.md` §2.3/§2.9；刀五a 台账 `docs/tasks/todo.md`「批4 刀五a」段；门禁见 `docs/reference/testing-gates.md`。

## 设计决策（本刀补充 spec）

1. **FileSelect 真实规模**：分析页走 `/files/options/`，后端默认 `limit=5000`、上限 20000（`apps/datafiles/views/file_views.py:275-285`）；数据管理页走 `/files/?page_size=9999`（`DataManagement.vue:197`）。v1 每项一个完整组件实例，必须虚拟化。
2. **分组是死代码**：`FileSelect` 的 `groupBy` 当前 **0 个消费者**（`grep -rn "group-by\|groupBy" src --include=*.vue` 只命中无关的箱线图分组），e2e 也 0 条分组断言。本刀删除 `groupBy` / `FileGroup` / `groupFiles` / `groupedItems` 与组头 CSS；保留多选已选置顶（`pinSelected`，AnalysisFilePicker 等多选场景在用）。
3. **SftpSearchPage 判 no-op**：运行历史在 store 侧已封顶 `RUN_HISTORY_KEEP = 20`（`frontend/src/stores/sftpSearch.ts:37`，2026-09-21 起），属设计稿「有意保留的 v1」有界小集，不迁 v2、不加判据。
4. **CombineBatchDialog 迁 v2**：批次目录列表在 API 侧不封顶（`BatchDirListView` 无分页），选项数 = 批次数；迁 v2 只改一行模板 + 一个 computed，虚拟化免费，避免未来批次增多后重演。
5. **高亮复用 `utils/selectOptions.ts` 的 `highlightSegments`**：该函数已按「返回文本片段、禁止 v-html」实现并有 XSS 反向探针；FileSelect 直接在 `#default` 行 slot 里逐行调用，不回到旧的全量预建 HTML。
6. **行高**：`showMeta` 48px（两行富信息），否则 34px；v2 的 `item-height` 固定，组头分支已删除，不存在「组头跟着变高」的冲突。
7. **count hint**：沿用 `ParamSelector` 的文案与样式（`共 N 项` / `匹配 N 项`），给 5000 项级别的下拉一个规模读数，也给虚拟窗口哨兵提供非 DOM 的候选数来源。

## Global Constraints

- **600 行**：`FileSelect.vue` 现 368 行，迁移后目标 < 400；`fileSelectModel.ts` 约 100 行；所有被改文件收口前跑 `npx vitest run test/unit/lineLimit.spec.ts`。
- **双主题**：不新增颜色；新增/保留样式只用 `var(--token)`。FileSelect 的 popper 仍是 `dp-file-select-dropdown` + 使用方 `popperClass`，不新增实例级类名。
- **e2e 判据类名不破**：`.dp-file-option__name`、`.dp-file-option__meta`、`mark`、`.dp-file-select-dropdown`、`.dp-file-picker-multi` 必须继续存在；`e2e/data/data.spec.ts:747` 的无裁剪断言与 `e2e/analysis/file-select.spec.ts` 的 `<mark>` 断言是本刀的回归闸。
- **本刀不动后端**：`apps/`、`test/backend/`、`config/`、`requirements/` 零改动；收口时用 `git diff --stat -- apps test config requirements` 为空来复用上一轮 `Ran 2712 / OK (skipped=16)`。
- **分支**：从 master `858c0e4` 另开 `feature/batch4e-knife5b-fileselect-v2`；不 push；FF 并入本地 master 需用户点头。
- **共享工作树**：不 `git add -A`；只 stage 本刀文件；每次提交前 `git status --short` 核对。
- **一条 bash 只跑一个 playwright project**；跑前 `netstat -ano | grep LISTENING` 确认端口空闲，跑后读汇总行（`RESULT:` 或 playwright 末尾统计行），不读 `$?`。
- **out of scope**：prune 保留期、jobs/ 占用口径、过载准入、管理员跨用户（四项待拍板项）；`view-data.spec.ts:1474` 几何 flake；`correlation-matrix-linkage` 既有红；`FileSelect` 的远程分页加载（本刀只做客户端虚拟化）。

## File Structure

- `frontend/src/components/common/fileSelectModel.ts`（新建）：`normalizeQuery` / `matchFile` / `fileRank` / `sortFiles` / `buildFileOptions` / `metaText`。
- `frontend/test/unit/fileSelectModel.spec.ts`（新建）：纯函数 T2。
- `frontend/src/components/common/FileSelect.vue`：模板/脚本/CSS 迁 v2，删分组死代码。
- `frontend/e2e/analysis/file-select.spec.ts`：新增虚拟窗口哨兵。
- `frontend/src/pages/data/components/CombineBatchDialog.vue`：批次下拉迁 v2。
- `frontend/src/pages/sftp/SftpSearchPage.vue`：运行历史下拉 no-op 注释（无行为改动）。
- `frontend/e2e/helpers/elplus.ts`：`pickOptionByKeyword` + `CORR_X_POPPER` / `CORR_Y_POPPER`；census 注释。
- `frontend/e2e/helpers/selectV2.ts`：`expectWindowRows` 先等首行可见。
- `frontend/e2e/analysis/{analysis,axis-label-precision,correlation-file-switch-reset}.spec.ts`：收敛三份 `pickAxisByKeyword`，X 也走关键词，补 X 哨兵。
- `frontend/test/unit/useSelectFilter.spec.ts`：补 `source` 响应式与 `focusOnOpen: false` 两条 T2。
- `frontend/src/utils/selectOptions.ts`：只更新消费者 census 注释，不改函数。
- `docs/tasks/todo.md`：新增「批4 刀五b」台账。

---

### Task 0: 开分支与前置核盘

**Files:**
- 无代码改动

**Interfaces:**
- Consumes: master `858c0e4`
- Produces: 分支 `feature/batch4e-knife5b-fileselect-v2`

- [ ] **Step 1: 核盘**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase"
git rev-parse --short HEAD
git status --short
```

Expected: `858c0e4`，`git status --short` 为空。若不为空：**停止**，报告脏文件，不 stash、不 checkout（共享工作树规则）。

- [ ] **Step 2: 开分支**

```bash
git switch -c feature/batch4e-knife5b-fileselect-v2 master
```

Expected: `Switched to a new branch 'feature/batch4e-knife5b-fileselect-v2'`

- [ ] **Step 3: 先把计划与未勾选台账落盘（项目 Task Management 第 1 条）**

在 `docs/tasks/todo.md` 末尾追加本刀台账骨架（此步只写未勾选清单与前置实测；门禁表在 Task 8 填）：

```markdown
# 任务：批4 刀五b（FileSelect 虚拟化 + 下拉收尾，2026-11-21）

计划：`docs/superpowers/plans/2026-11-21-batch4e-knife5b-fileselect-virtualization.md`
设计：`docs/superpowers/specs/2026-11-13-ux-batch-dropdown-admin-dedup-intro-usage-design.md` §2.3/§2.9

## 前置实测

- FileSelect 候选上限：分析页 `/files/options/` 默认 `limit=5000`（上限 20000）；数据管理页 `/files/?page_size=9999`。
- SftpSearchPage 运行历史 `RUN_HISTORY_KEEP = 20`（`stores/sftpSearch.ts:37`）⇒ 判 no-op，不迁 v2。
- FileSelect `groupBy` 零消费者、e2e 零断言 ⇒ 本刀删除分组死代码，保留 `pinSelected`。

## 勾选清单

- [ ] fileSelectModel 纯函数 + T2
- [ ] FileSelect.vue 迁 el-select-v2、删分组
- [ ] FileSelect 虚拟窗口哨兵 + v1 变异自证
- [ ] CombineBatchDialog 批次下拉迁 v2
- [ ] SftpSearchPage no-op 注释
- [ ] axis 助手收敛 + X 哨兵 + census + T3 判据文案
- [ ] useSelectFilter 两条 T2
- [ ] 收口门禁

## 门禁记录

| 档 | 命令 | 实测判据行 |
|---|---|---|
| ... | ... | ... |
```

```bash
git add docs/tasks/todo.md docs/superpowers/plans/2026-11-21-batch4e-knife5b-fileselect-virtualization.md
git commit -m "docs(plan): 批4 刀五b 计划与台账"
```

---

### Task 1: FileSelect 纯逻辑模型 + T2（TDD）

**Files:**
- Create: `frontend/src/components/common/fileSelectModel.ts`
- Test: `frontend/test/unit/fileSelectModel.spec.ts`

**Interfaces:**
- Produces:
  - `interface FileSelectOption { value: number; label: string; file: DataFile }`
  - `normalizeQuery(raw: string): string`
  - `matchFile(f: Pick<DataFile, 'filename' | 'program_name' | 'batch_name'>, query: string): boolean`
  - `fileRank(f: Pick<DataFile, 'filename'>, query: string): number`
  - `sortFiles(files: DataFile[], query: string, pinnedOrder: number[]): DataFile[]`
  - `buildFileOptions(files: DataFile[], query: string, pinnedOrder: number[]): FileSelectOption[]`
  - `metaText(f: DataFile): string`

- [ ] **Step 1: 写失败测试**

`frontend/test/unit/fileSelectModel.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'
import {
  buildFileOptions,
  fileRank,
  matchFile,
  metaText,
  normalizeQuery,
  sortFiles,
} from '../../src/components/common/fileSelectModel'
import type { DataFile } from '../../src/types'

function file(id: number, filename: string, extra: Partial<DataFile> = {}): DataFile {
  return {
    id,
    filename,
    format_type: 'FT',
    file_type: 'single',
    batch_name: '',
    row_count: 0,
    col_count: null,
    program_name: '',
    status: 'ready',
    created_at: '',
    ...extra,
  }
}

describe('fileSelectModel', () => {
  it('normalizeQuery 去空白并转小写', () => {
    expect(normalizeQuery('  AbC ')).toBe('abc')
  })

  it('matchFile 命中 filename / program_name / batch_name，大小写不敏感', () => {
    const f = file(1, 'Alpha.csv', { program_name: 'P1', batch_name: 'B2' })
    expect(matchFile(f, 'alpha')).toBe(true)
    expect(matchFile(f, 'p1')).toBe(true)
    expect(matchFile(f, 'b2')).toBe(true)
    expect(matchFile(f, 'zzz')).toBe(false)
    expect(matchFile(f, '')).toBe(true)
  })

  it('fileRank 前缀 0 / 包含 1 / 其它 2', () => {
    expect(fileRank(file(1, 'Alpha'), 'al')).toBe(0)
    expect(fileRank(file(1, 'xAlpha'), 'al')).toBe(1)
    expect(fileRank(file(1, 'Beta'), 'al')).toBe(2)
  })

  it('sortFiles 无关键词保持原序；有关键词按 rank + localeCompare', () => {
    const files = [file(1, 'b'), file(2, 'A1'), file(3, 'A2')]
    expect(sortFiles(files, '', []).map((f) => f.id)).toEqual([1, 2, 3])
    expect(sortFiles(files, 'a', []).map((f) => f.id)).toEqual([2, 3, 1])
  })

  it('sortFiles 已选按选中顺序置顶，且其余项不重复', () => {
    const files = [file(1, 'one'), file(2, 'two'), file(3, 'three')]
    expect(sortFiles(files, '', [3, 1]).map((f) => f.id)).toEqual([3, 1, 2])
  })

  it('buildFileOptions 映射 value/label 并保留 file', () => {
    const files = [file(7, 'seven')]
    expect(buildFileOptions(files, '', [])).toEqual([
      { value: 7, label: 'seven', file: files[0] },
    ])
  })

  it('metaText 组合 program · format · 行数 · 大小 · 时间，空值跳过', () => {
    const f = file(1, 'a.csv', {
      program_name: 'P',
      format_type: 'FT',
      row_count: 12,
      file_size: 2048,
      created_at: '2026-11-21T10:00:00+08:00',
    })
    expect(metaText(f)).toContain('P · FT · 12 行')
    expect(metaText(file(2, 'b.csv'))).toBe('FT · 0 行')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd frontend && npx vitest run test/unit/fileSelectModel.spec.ts
```

Expected: FAIL（`Failed to resolve import ... fileSelectModel`）。

- [ ] **Step 3: 写最小实现**

`frontend/src/components/common/fileSelectModel.ts`：

```ts
import type { DataFile } from '../../types'
import { formatSize, formatTime } from '../../utils/format'

export interface FileSelectOption {
  value: number
  label: string
  file: DataFile
}

/** 查询词归一化：去首尾空白 + 小写。matchFile / fileRank 假定入参已经归一化。 */
export function normalizeQuery(raw: string): string {
  return raw.trim().toLowerCase()
}

export function matchFile(
  f: Pick<DataFile, 'filename' | 'program_name' | 'batch_name'>,
  query: string,
): boolean {
  if (!query) return true
  return [f.filename, f.program_name, f.batch_name]
    .some((v) => (v ?? '').toLowerCase().includes(query))
}

export function fileRank(f: Pick<DataFile, 'filename'>, query: string): number {
  const name = (f.filename ?? '').toLowerCase()
  if (name.startsWith(query)) return 0
  if (name.includes(query)) return 1
  return 2
}

/**
 * 无 query 保持入参原序；有 query 按 rank + localeCompare。
 * 多选已选按 pinnedOrder（选中顺序）置顶，其余项保持排序结果且不重复。
 */
export function sortFiles(
  files: DataFile[],
  query: string,
  pinnedOrder: number[],
): DataFile[] {
  const ranked = query
    ? [...files].sort((a, b) => {
        const r = fileRank(a, query) - fileRank(b, query)
        return r !== 0 ? r : a.filename.localeCompare(b.filename)
      })
    : files
  if (!pinnedOrder.length) return ranked
  const pinnedSet = new Set(pinnedOrder)
  const pinned = pinnedOrder
    .map((id) => ranked.find((f) => f.id === id))
    .filter((f): f is DataFile => Boolean(f))
  const rest = ranked.filter((f) => !pinnedSet.has(f.id))
  return [...pinned, ...rest]
}

export function buildFileOptions(
  files: DataFile[],
  query: string,
  pinnedOrder: number[],
): FileSelectOption[] {
  return sortFiles(files, query, pinnedOrder).map((f) => ({
    value: f.id,
    label: f.filename ?? '',
    file: f,
  }))
}

/** 富信息行：program · format · N 行 · 大小 · 上传时间 */
export function metaText(f: DataFile): string {
  return [
    f.program_name,
    f.format_type,
    `${f.row_count ?? 0} 行`,
    f.file_size ? formatSize(f.file_size) : '',
    f.created_at ? formatTime(f.created_at) : '',
  ]
    .filter(Boolean)
    .join(' · ')
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd frontend && npx vitest run test/unit/fileSelectModel.spec.ts
```

Expected: `Tests 7 passed (7)`。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/common/fileSelectModel.ts frontend/test/unit/fileSelectModel.spec.ts
git commit -m "refactor(common): 抽出 FileSelect 过滤排序模型"
```

---

### Task 2: FileSelect.vue 迁 `el-select-v2`，删分组死代码

**Files:**
- Modify: `frontend/src/components/common/FileSelect.vue`

**Interfaces:**
- Consumes: `buildFileOptions` / `matchFile` / `metaText` / `normalizeQuery`（Task 1）；`highlightSegments`（`frontend/src/utils/selectOptions.ts`）
- Produces: 组件对外 props/emits 除删除 `groupBy` 外不变；popper 仍带 `dp-file-select-dropdown`

- [ ] **Step 1: 替换模板为 v2**

把 `<template>` 整段替换为：

```vue
<template>
  <el-select-v2
    v-bind="attrs"
    :model-value="modelValue"
    :options="options"
    :multiple="multiple"
    :clearable="clearable"
    :collapse-tags="collapseTags"
    :collapse-tags-tooltip="collapseTagsTooltip"
    :size="size || undefined"
    :placeholder="placeholder"
    :disabled="disabled"
    :loading="loading"
    :id="id || undefined"
    :popper-class="dropdownClass"
    :height="360"
    :item-height="itemHeight"
    filterable
    :filter-method="onFilter"
    @update:model-value="onUpdate"
    @change="onChange"
    @visible-change="onVisibleChange"
    @clear="onClear"
  >
    <template #default="{ item }">
      <div class="dp-file-option">
        <span class="dp-file-option__name">
          <template v-for="(seg, i) in segmentsFor(item.file.filename ?? '')" :key="i">
            <mark v-if="seg.mark">{{ seg.text }}</mark>
            <template v-else>{{ seg.text }}</template>
          </template>
        </span>
        <span v-if="showMeta" class="dp-file-option__meta">{{ metaText(item.file) }}</span>
      </div>
    </template>
    <template #empty>
      <div class="dp-empty-hint">无匹配文件</div>
    </template>
    <template #footer>
      <div class="dp-file-count-hint">{{ q ? '匹配' : '共' }} {{ options.length }} 项</div>
    </template>
  </el-select-v2>
</template>
```

- [ ] **Step 2: 替换脚本**

`<script setup>` 整段替换为（Props 删除 `groupBy`，保留 `pinSelected`；删掉全部分组/高亮 HTML 函数）：

```vue
<script setup lang="ts">
import { computed, ref, useAttrs } from 'vue'
import type { DataFile } from '../../types'
import {
  buildFileOptions,
  matchFile,
  metaText,
  normalizeQuery,
} from './fileSelectModel'
import { highlightSegments } from '../../utils/selectOptions'

type FileSelectSize = 'large' | 'default' | 'small' | ''

interface Props {
  /** 文件列表（由父级拉取后传入，组件不做远程加载） */
  files: DataFile[]
  /** v-model：单选 number|null；多选 number[] */
  modelValue: number | number[] | null
  /** 多选模式 */
  multiple?: boolean
  placeholder?: string
  clearable?: boolean
  collapseTags?: boolean
  collapseTagsTooltip?: boolean
  size?: FileSelectSize
  disabled?: boolean
  /** 透传给 el-select 的 loading（父级文件列表加载态） */
  loading?: boolean
  /** 绑定内部原生 input（label[for] 指向依赖） */
  id?: string
  /** 追加到下拉 popper 根节点的类（内部自带 dp-file-select-dropdown） */
  popperClass?: string
  /** 富信息行：文件名 + program · format · 行数 · 大小 · 上传时间 */
  showMeta?: boolean
  /** 多选模式已选文件置顶（单选恒保持 files 原序） */
  pinSelected?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  multiple: false,
  placeholder: '选择数据文件',
  clearable: false,
  collapseTags: false,
  collapseTagsTooltip: false,
  size: '',
  disabled: false,
  loading: false,
  id: undefined,
  popperClass: '',
  showMeta: false,
  pinSelected: true,
})

interface Emits {
  (e: 'update:modelValue', value: number | number[] | null): void
  (e: 'change', value: number | number[] | null): void
  (e: 'visible-change', visible: boolean): void
  (e: 'clear'): void
}
const emit = defineEmits<Emits>()

const attrs = useAttrs()
defineOptions({ inheritAttrs: false })

const filterText = ref('')
const q = computed(() => normalizeQuery(filterText.value))

/** 已选文件 id（保持选中顺序，多选置顶按此序） */
const pinnedOrder = computed<number[]>(() =>
  props.multiple && props.pinSelected && Array.isArray(props.modelValue)
    ? [...props.modelValue]
    : [],
)

const options = computed(() =>
  buildFileOptions(
    props.files.filter((f) => matchFile(f, q.value)),
    q.value,
    pinnedOrder.value,
  ),
)

/** v2 的虚拟滚动要求固定行高：富信息行两行约 40px，取 48；紧凑行维持 34。 */
const itemHeight = computed(() => (props.showMeta ? 48 : 34))

const dropdownClass = computed(() =>
  ['dp-file-select-dropdown', props.popperClass].filter(Boolean).join(' '),
)

function segmentsFor(text: string) {
  return highlightSegments(text, q.value)
}

// ---------- 事件流转 ----------
function onFilter(query: string) {
  filterText.value = query
}
function onVisibleChange(visible: boolean) {
  if (!visible) filterText.value = ''
  emit('visible-change', visible)
}
function onUpdate(val: number | number[] | null) {
  emit('update:modelValue', val)
}
function onChange(val: number | number[] | null) {
  emit('change', val)
}
function onClear() {
  emit('clear')
}
</script>
```

- [ ] **Step 3: 调整样式**

保留 `.dp-file-option` / `.dp-file-option__name` / `:deep(mark)` / `.dp-file-option__meta` 的 token 与省略号规则，把 `.dp-file-option` 改成纵向居中并撑满 v2 给定行高：

```css
.dp-file-option {
  display: flex;
  flex-direction: column;
  justify-content: center;
  width: 100%;
  height: 100%;
  line-height: normal;
}
```

未 scoped 的 popper 样式改为（删除 `.el-select-group__title` / `.dp-file-group--pinned` / `.el-select-dropdown__list` 三条旧规则）：

```css
.dp-file-select-dropdown .el-select-dropdown__item {
  line-height: normal;
  padding: 0 20px;
}

.dp-file-select-dropdown .dp-file-count-hint {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
  text-align: center;
}
```

- [ ] **Step 4: 跑构建与行数闸**

```bash
cd frontend && npm run build
cd frontend && npx vitest run test/unit/lineLimit.spec.ts
```

Expected: build 无 TS 诊断；lineLimit `Tests ... passed`；`FileSelect.vue` < 400 行。

- [ ] **Step 5: 跑 FileSelect 与富信息行回归档**

```bash
cd frontend && E2E_PORT=21061 E2E_FRONTEND_PORT=22061 npx playwright test e2e/analysis/file-select.spec.ts --project=P1 --workers=1
```

Expected: 按文件末尾实际汇总行取；本文件 7 条用例，含 `[setup]` 认证时汇总为 9 条。

```bash
cd frontend && E2E_PORT=21061 E2E_FRONTEND_PORT=22061 npx playwright test e2e/data/data.spec.ts --project=P2 --workers=1 -g "富信息"
```

Expected: 绿（`data.spec.ts:747` 的 meta 无裁剪断言）。若该 `-g` 没有命中，改跑整文件并在台账记实际用例标题；不许删断言。

- [ ] **Step 6: 人工目测双主题**

启动 `npm run dev`，在分析页分别切 light/night：打开文件下拉，确认富信息两行不裁剪、`<mark>` 高亮可见、多选已选置顶顺序正确、空态文案「无匹配文件」可见、footer 计数正确。发现问题就地修 CSS，重跑 Step 5。

- [ ] **Step 7: 提交**

```bash
git add frontend/src/components/common/FileSelect.vue
git commit -m "perf(common): FileSelect 下拉迁 el-select-v2 虚拟化"
```

---

### Task 3: FileSelect 虚拟窗口哨兵（T3）

**Files:**
- Modify: `frontend/e2e/analysis/file-select.spec.ts`

**Interfaces:**
- Consumes: `MAX_WINDOW_ROWS`（`e2e/helpers/selectV2.ts`）
- Produces: 一条「DOM 行数远小于候选数」的反截断判据；v1 回退必红

- [ ] **Step 1: 加哨兵用例**

在文件顶部导入：

```ts
import { MAX_WINDOW_ROWS } from '../helpers/selectV2'
```

在 `test.describe` 内新增：

```ts
  test('虚拟窗口：DOM 只挂窗口内十来行，不是全部候选', async ({ page }) => {
    const dropdown = await openFileDropdown(page)
    const countHint = dropdown.locator('.dp-file-count-hint')
    await expect(countHint).toHaveText(/共 \d+ 项/)
    const total = Number(/共 (\d+) 项/.exec((await countHint.textContent()) ?? '')?.[1] ?? 0)
    expect(total, '夹具文件数须大于窗口界，否则本条没有牙齿').toBeGreaterThan(MAX_WINDOW_ROWS)
    const items = dropdown.locator('.el-select-dropdown__item')
    await expect(items.first()).toBeVisible()
    const rows = await items.count()
    expect(
      rows,
      `文件下拉应虚拟化：DOM ${rows} 行 / 候选 ${total} 项，界 ${MAX_WINDOW_ROWS}`,
    ).toBeLessThan(MAX_WINDOW_ROWS)
    test.info().annotations.push({
      type: '虚拟窗口实测',
      description: `文件下拉：DOM ${rows} 行 / 候选 ${total} 项 / 界 ${MAX_WINDOW_ROWS}`,
    })
  })
```

- [ ] **Step 2: 跑测试确认绿**

```bash
cd frontend && E2E_PORT=21061 E2E_FRONTEND_PORT=22061 npx playwright test e2e/analysis/file-select.spec.ts --project=P1 --workers=1
```

Expected: 新用例绿，annotation 记录实测 DOM 行数与候选数。

- [ ] **Step 3: 变异自证（v1 回退必红）**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase"
git show HEAD^:frontend/src/components/common/FileSelect.vue > tasks/_fileselect_v1.vue
cp tasks/_fileselect_v1.vue frontend/src/components/common/FileSelect.vue
cd frontend && E2E_PORT=21061 E2E_FRONTEND_PORT=22061 npx playwright test e2e/analysis/file-select.spec.ts --project=P1 --workers=1 -g "虚拟窗口"
```

Expected: FAIL，消息里 `实测 87 行`（或该夹具当时候选数）且 `界 20`。随后恢复：

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase"
git checkout -- frontend/src/components/common/FileSelect.vue
rm -f tasks/_fileselect_v1.vue
```

再跑一遍 Step 2 确认绿。注意：`tasks/_fileselect_v1.vue` 是临时文件，不得提交。

- [ ] **Step 4: 提交**

```bash
git add frontend/e2e/analysis/file-select.spec.ts
git commit -m "test(e2e): 钉住 FileSelect 走虚拟窗口"
```

---

### Task 4: CombineBatchDialog 批次下拉迁 v2

**Files:**
- Modify: `frontend/src/pages/data/components/CombineBatchDialog.vue`

**Interfaces:**
- Consumes: `props.batchOptions: string[]`
- Produces: 模板仍保留 `data-testid="combine-existing-select"`

- [ ] **Step 1: 模板替换**

把 `v-else` 的 `<el-select>...</el-select>` 整段替换为：

```vue
    <el-select-v2
      v-else
      v-model="existingName"
      :options="batchSelectOptions"
      filterable
      placeholder="选择目标批次"
      size="large"
      :data-testid="'combine-existing-select'"
      style="margin-top: 12px; width: 100%"
    />
```

- [ ] **Step 2: 脚本加 computed**

在 `const existingName = ref('')` 之后加：

```ts
const batchSelectOptions = computed(() =>
  props.batchOptions.map((name) => ({ label: name, value: name })),
)
```

`computed` 已在文件里导入，不新增 import。

- [ ] **Step 3: 跑组合批次回归档**

```bash
cd frontend && E2E_PORT=21061 E2E_FRONTEND_PORT=22061 npx playwright test e2e/data/combine.spec.ts --project=P2 --workers=1
```

Expected: 整文件绿；`[data-testid="combine-existing-select"]` 的追加模式用例正常选中批次。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/pages/data/components/CombineBatchDialog.vue
git commit -m "perf(data): 组合批次下拉迁 el-select-v2"
```

---

### Task 5: SftpSearchPage 判 no-op + 注释

**Files:**
- Modify: `frontend/src/pages/sftp/SftpSearchPage.vue`

**Interfaces:**
- Consumes: `frontend/src/stores/sftpSearch.ts` 的 `RUN_HISTORY_KEEP = 20`
- Produces: 无行为改动；台账记明「不迁 v2」依据

- [ ] **Step 1: 加一行说明注释**

在运行历史 `<el-select>` 上方加：

```vue
      <!-- 运行历史上限 RUN_HISTORY_KEEP=20（stores/sftpSearch.ts）；有界小集，按设计稿「有意保留的 v1」不迁 v2。 -->
```

- [ ] **Step 2: 不跑用例，只做静态核对**

```bash
cd frontend && grep -n "RUN_HISTORY_KEEP" src/stores/sftpSearch.ts && grep -n "RUN_HISTORY_KEEP=20" src/pages/sftp/SftpSearchPage.vue
```

Expected: 两处都命中，且 store 值是 `20`。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/pages/sftp/SftpSearchPage.vue
git commit -m "docs(sftp): 说明运行历史下拉不迁 v2 的依据"
```

---

### Task 6: 刀五a 挂账收尾（axis 助手 + 哨兵 + census）

**Files:**
- Modify: `frontend/e2e/helpers/elplus.ts`
- Modify: `frontend/e2e/helpers/selectV2.ts`
- Modify: `frontend/e2e/analysis/analysis.spec.ts`
- Modify: `frontend/e2e/analysis/axis-label-precision.spec.ts`
- Modify: `frontend/e2e/analysis/correlation-file-switch-reset.spec.ts`
- Modify: `frontend/src/utils/selectOptions.ts`（仅注释）

**Interfaces:**
- Produces:
  - `CORR_X_POPPER = 'dp-corr-x-popper'`
  - `CORR_Y_POPPER = 'dp-corr-y-popper'`
  - `pickOptionByKeyword(page, placeholder, keyword, scope?, popperClass?): Promise<void>`
  - `expectWindowRows()` 先 `await expect(items.first()).toBeVisible()` 再计数

- [ ] **Step 1: `elplus.ts` 加常量与助手**

在 `PIN_COL_POPPER` 之后加：

```ts
/** 相关性 X/Y 下拉面板的实例级 class（`CorrelationToolsTab.vue` 的 `popper-class` 字面值）。 */
export const CORR_X_POPPER = 'dp-corr-x-popper'
export const CORR_Y_POPPER = 'dp-corr-y-popper'
```

在 `pickOption` 之后加：

```ts
/** 打开下拉 → 在过滤 input 输入关键词 → 点命中项；popperClass 给实例级面板时按实例取选项。 */
export async function pickOptionByKeyword(
  page: Page,
  selectPlaceholder: string,
  keyword: string,
  scope: Page | Locator = page,
  popperClass?: string,
) {
  const select = elSelectByPlaceholder(scope, selectPlaceholder).first()
  await select.click()
  await select.locator('input').first().fill(keyword)
  const options = popperClass
    ? popperOf(page, popperClass).locator('.el-select-dropdown__item')
    : visibleSelectOptions(page)
  await options.filter({ hasText: keyword }).first().click()
}
```

- [ ] **Step 2: 三个 spec 收敛**

`e2e/analysis/analysis.spec.ts`、`e2e/analysis/axis-label-precision.spec.ts`、`e2e/analysis/correlation-file-switch-reset.spec.ts`：

1. 删除各自本地的 `pickAxisByKeyword` 函数。
2. 从 `../helpers/elplus` 导入 `pickOptionByKeyword`、`CORR_X_POPPER` 与 `CORR_Y_POPPER`（**X/Y 都走关键词**，不再保留裸 `pickOption` 的 X 分支——这是 `todo.md:1499` 挂账的收口）。
3. `correlation-file-switch-reset.spec.ts` 删除本地 `const CORR_Y_POPPER = ...`。
4. 把 Y 轴调用改成：

```ts
await pickOptionByKeyword(page, '选择 Y 轴参数', 'KELVIN_SW', layout, CORR_Y_POPPER)
```

5. 把三个文件里的 X 轴裸选改成：

```ts
await pickOptionByKeyword(page, '选择 X 轴参数', 'KELVIN_VIN', layout, CORR_X_POPPER)
```

6. 收敛后清掉因此不再使用的 import（`pickOption` / `visibleSelectOptions` / `elSelectByPlaceholder` 若已无调用），以 `npm run lint:e2e` 无报错为准。

- [ ] **Step 3: `selectV2.ts` 补首行可见等待**

```ts
export async function expectWindowRows(items: Locator, candidates: number, label: string): Promise<number> {
  await expect(items.first()).toBeVisible()
  const rows = await items.count()
  expect(
    rows,
    `DOM 里只该有虚拟窗口那几行（${label}：实测 ${rows} 行 / 当下候选 ${candidates} 项，界 ${MAX_WINDOW_ROWS}）`,
  ).toBeLessThan(MAX_WINDOW_ROWS)
  return rows
}
```

- [ ] **Step 4: X 哨兵补齐**

在 `correlation-file-switch-reset.spec.ts` 的 Y 哨兵之前，加 X 的同类哨兵（复用 `paramTotal` / `MAX_WINDOW_ROWS` / `expectWindowRows` / `windowItems`）：

```ts
    await elSelectByPlaceholder(layout, '选择 X 轴参数').first().click()
    const xPopper = popperOf(page, CORR_X_POPPER)
    await expect(xPopper).toBeVisible()
    const xRows = await expectWindowRows(
      windowItems(page, CORR_X_POPPER),
      paramTotal,
      '相关性 X 下拉（未输入关键词时的虚拟窗口）',
    )
    expect(xRows, '虚拟窗口里至少得有可见行，否则计数没意义').toBeGreaterThan(0)
    test.info().annotations.push({
      type: '虚拟窗口实测',
      description: `相关性 X 下拉未输入关键词：DOM ${xRows} 行 / 候选 ${paramTotal} 项 / 界 ${MAX_WINDOW_ROWS}`,
    })
    await page.keyboard.press('Escape')
    await expect(xPopper).toBeHidden()
```

- [ ] **Step 5: 更新 census 注释**

`elplus.ts` 的 `visibleSelectOptions` 注释改成当前实数：

```text
消费者口径（2026-11-21 `grep -rn visibleSelectOptions e2e src test` 现数）：
直接调用是 `e2e/data/file-correlation.spec.ts` 6 处 + 本文件的 `pickOptionByKeyword` 1 处；
`e2e/analysis/{analysis,axis-label-precision,correlation-file-switch-reset}.spec.ts`
已改经 `pickOptionByKeyword` 间接使用，不再各自直调。
```

`selectOptions.ts` 顶部注释改成当前实数：

```text
消费者（2026-11-21 现数，`grep -rn "utils/selectOptions" frontend/src`）：
`toOptions` = CorrelationToolsTab（X/Y）+ DataBrowserToolbar（固定列）+ useSelectFilter 共 3 处；
`filterByKeyword` = useSelectFilter 1 处；`sortPrefixFirst` / `buildSelectView` = ParamSelector 1 处；
`highlightSegments` = ParamSelector + FileSelect（刀五b）共 2 处。
```

- [ ] **Step 6: file-correlation 收尾（T3 判据文案 + 残留未过滤查找）**

1. `e2e/data/file-correlation.spec.ts:390` 的 `expectWindowRows` label 写的是「关后重开，应无残留过滤」，但真正承重的是**收起那一刻**的隐藏面板（重开时 v2 自己会洗 query，见 `todo.md:1502`）。把 label 改成「序列下拉（收起后隐藏面板无残留过滤）」，并把同段注释里「重开后面板同样是全量」标注为「用户可见收尾，不承重」；只改文案与注释，不动断言。
2. 同文件 `:462-472`（「跨程序同名异拼法」）还有一处 FileSelect 未过滤查找（`elSelectByPlaceholder` + `visibleSelectOptions().filter()`），v2 下只是碰巧命中首屏窗口。按 `pickFilePair` 的形状改成先填过滤词再点：

```ts
    const file1 = elSelectByPlaceholder(section, '文件1 (ATE)')
    await file1.click()
    await expect
      .poll(() => visibleSelectOptions(page).count(), { timeout: 15_000 })
      .toBeGreaterThan(0)
    await file1.locator('input').first().fill(SEEDED_FILES.CTA8290D_FT)
    await visibleSelectOptions(page).filter({ hasText: SEEDED_FILES.CTA8290D_FT }).first().click()
    await page.waitForTimeout(600)
    const file2 = elSelectByPlaceholder(section, '文件2 (Bench)')
    await file2.click()
    await file2.locator('input').first().fill(SEEDED_FILES.CTA8280F_FT)
    await visibleSelectOptions(page).filter({ hasText: SEEDED_FILES.CTA8280F_FT }).first().click()
    await page.waitForTimeout(600)
```

- [ ] **Step 7: 跑三个 spec（一次一个 project）**

```bash
cd frontend && E2E_PORT=21061 E2E_FRONTEND_PORT=22061 npx playwright test e2e/analysis/correlation-file-switch-reset.spec.ts --project=P1 --workers=1
```

```bash
cd frontend && E2E_PORT=21061 E2E_FRONTEND_PORT=22061 npx playwright test e2e/analysis/analysis.spec.ts --project=P1 --workers=1
```

```bash
cd frontend && E2E_PORT=21061 E2E_FRONTEND_PORT=22061 npx playwright test e2e/analysis/axis-label-precision.spec.ts --project=P1 --workers=1
```

Expected: 三个文件各自末尾汇总行全绿；`correlation-file-switch-reset` 的 annotation 同时含 X 与 Y 的实测行。

- [ ] **Step 8: 提交**

```bash
git add frontend/e2e/helpers/elplus.ts frontend/e2e/helpers/selectV2.ts \
  frontend/e2e/analysis/analysis.spec.ts frontend/e2e/analysis/axis-label-precision.spec.ts \
  frontend/e2e/analysis/correlation-file-switch-reset.spec.ts \
  frontend/e2e/data/file-correlation.spec.ts frontend/src/utils/selectOptions.ts
git commit -m "test(e2e): 收敛轴选择助手并补 X 哨兵"
```

---

### Task 7: `useSelectFilter` 补两条 T2

**Files:**
- Modify: `frontend/test/unit/useSelectFilter.spec.ts`

**Interfaces:**
- Consumes: `useSelectFilter`（`frontend/src/pages/data/composables/useSelectFilter.ts`）
- Produces: `source` 响应式变化与 `focusOnOpen: false` 的负例判据

- [ ] **Step 1: 加测试**

```ts
  it('source 是响应式的：源列表异步换掉后 selectOptions 跟着走', () => {
    const { api, source } = mount(['A', 'B'], [])
    expect(api.selectOptions.value.map((o) => o.value)).toEqual(['A', 'B'])
    source.value = ['C']
    expect(api.selectOptions.value.map((o) => o.value)).toEqual(['C'])
  })

  it('focusOnOpen: false 时打开不回填焦点', async () => {
    const { api } = mount(['A'], [], undefined, false)
    const fakeInput = { value: '', focus: vi.fn() }
    api.selectRef.value = { $el: { querySelector: () => fakeInput } } as unknown as typeof api.selectRef.value
    api.onVisibleChange(true)
    await nextTick()
    expect(fakeInput.focus).not.toHaveBeenCalled()
  })
```

- [ ] **Step 2: 跑测试**

```bash
cd frontend && npx vitest run test/unit/useSelectFilter.spec.ts
```

Expected: `Tests 14 passed (14)`（原 12 + 新 2）。

- [ ] **Step 3: 提交**

```bash
git add frontend/test/unit/useSelectFilter.spec.ts
git commit -m "test(unit): 补 useSelectFilter 响应式与负例判据"
```

---

### Task 8: 台账 + 收口门禁

**Files:**
- Modify: `docs/tasks/todo.md`

**Interfaces:**
- Consumes: 前七个任务的提交与门禁输出
- Produces: 「批4 刀五b」台账段，含勾选清单、门禁表、挂账

- [ ] **Step 1: 填台账门禁表与勾选**

Task 0 已把「批4 刀五b」骨架写进 `docs/tasks/todo.md`。本步只做两件事：

1. 按实测把每个命令的**末尾判据行原文**填进 `## 门禁记录`（不许抄快照、不许用 `tail` 截断出假绿）。
2. 按实际结果勾掉 `## 勾选清单` 的条目，并把「已知边界 / 挂账」补上：X/Y 哨兵覆盖、SftpSearchPage no-op、`view-data.spec.ts:1474`、`correlation-matrix-linkage` 既有红，逐条给归属。

- [ ] **Step 2: 跑完整门禁**

```bash
cd frontend && npm run test:unit
cd frontend && npm run build
cd frontend && npm run lint:e2e
cd frontend && npm run test:e2e:affected
```

Expected:
- vitest：全部 green，且包含 `fileSelectModel.spec.ts` 7 例、`useSelectFilter.spec.ts` 14 例、`lineLimit.spec.ts`。
- build：`build complete`，无 TS 诊断。
- lint:e2e：`error TS` 0 处。
- affected：末行 `RESULT: PASS`；若命中 GLOBAL/全量档，按打印的文件数确认。

- [ ] **Step 3: 收口全量池**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase"
node scripts/e2e_pool.mjs --slots=4
```

Expected: 池末行 `unexpected 0`、`结论 MEASURED`、exit 0；flaky 逐条点名并附 retry 结果。若出现红，按 `docs/reference/testing-gates.md` 先区分存量/负载 flake/本刀回归，不许直接改判据。

- [ ] **Step 4: 后端沿用证明**

```bash
cd "C:/Users/Administrator/Desktop/DataPrase/LQ-DataPrase"
git diff --stat 858c0e4..HEAD -- apps test config requirements
```

Expected: 空输出。然后沿用上一轮 `Ran 2712 / OK (skipped=16)`，并在台账写明「后端树零改动，沿用」。

- [ ] **Step 5: 填台账门禁表并提交**

把每个命令的**末尾判据行原文**填进 `## 门禁记录`，勾选清单按实际打勾，挂账写清：

```bash
git add docs/tasks/todo.md
git commit -m "docs(todo): 批4 刀五b 收口门禁"
```

- [ ] **Step 6: 停在这里，等用户点头再 FF 并入**

不 push、不在本任务里合并。并入时按既有流程：

```bash
git switch master
git merge --ff-only feature/batch4e-knife5b-fileselect-v2
git branch -d feature/batch4e-knife5b-fileselect-v2
git status --short
```

---

## Self-Review

1. **Spec coverage**：FileSelect 虚拟化（Task 1/2/3）、SftpSearchPage no-op（Task 5）、CombineBatchDialog（Task 4）、`pickAxisByKeyword` 收敛（Task 6）、census（Task 6）、T2 缺口（Task 7）、T3 判据文案（Task 6）、哨兵硬化（Task 6）、台账/门禁（Task 8）——逐项有任务。
2. **Placeholder scan**：无 TBD/TODO；所有代码步骤给了实际代码；命令给了预期输出。
3. **Type consistency**：`FileSelectOption` 的 `value: number` / `label: string` / `file: DataFile` 在 Task 1/2 一致；`pickOptionByKeyword` 的参数顺序在 Task 6 的常量/助手/三个 spec 中一致；`expectWindowRows` 签名未变。
4. **未覆盖项（显式 out of scope）**：prune 保留期、jobs/ 占用口径、过载准入、管理员跨用户；`view-data.spec.ts:1474` 几何 flake；`correlation-matrix-linkage` 既有红；FileSelect 远程分页。
