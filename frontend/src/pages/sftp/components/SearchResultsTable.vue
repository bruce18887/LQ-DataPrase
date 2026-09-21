<template>
  <div class="srt" data-testid="sftp-search-results">
    <!-- 信息带 + 动作条：分组开关、勾选汇总、导出/下载。结果计数常驻（虚拟滚动下
         看不见 ≠ 没有，用户必须知道表里到底有多少行）。 -->
    <div class="srt-bar">
      <span class="srt-title">{{ modeLabel }}</span>
      <span class="srt-count" data-testid="sftp-search-results-count">
        候选 {{ candidates.length }} · 命中 {{ matches.length }} · 表格 {{ shownCount }} 行
      </span>
      <span v-if="showingCandidates && mode !== 'name'" class="srt-hint">
        还没有命中，现在列出的是待扫描的候选文件
      </span>
      <span v-if="engine" class="srt-engine">
        {{ engine === 'grep' ? '服务端 grep' : '本地扫描' }}
      </span>

      <div class="srt-actions">
        <el-button size="small" text bg data-testid="sftp-results-group-toggle" @click="emit('toggle-group')">
          {{ grouped ? '切成扁平' : '按目录分组' }}
        </el-button>
        <template v-if="grouped">
          <el-button size="small" text bg :disabled="!groupDirs.length" @click="expandAll">全部展开</el-button>
          <el-button size="small" text bg :disabled="!groupDirs.length" @click="collapseAll">全部折叠</el-button>
        </template>
        <el-button size="small" text bg :disabled="!rows.length" @click="toggleSelectAll">
          {{ selectedPaths.length ? `取消勾选 (${selectedPaths.length})` : '全选' }}
        </el-button>
        <el-button size="small" text bg data-testid="sftp-results-export" :disabled="!rows.length" @click="emit('export')">
          导出 CSV
        </el-button>
        <!-- 下载是**传输**，与导出不同：它要抢后端那条共享 paramiko 连接，所以互斥判据
             由页面把 `transferActive` 传下来（计划 Task 17 Step 5）。禁用态必须配 tooltip
             说明「为什么禁着」，否则用户只会觉得按钮坏了；触发元素包一层 span —— EP 的
             tooltip 挂在 `<button disabled>` 上收不到 mouseenter（浏览器不给禁用控件派发
             鼠标事件），不包就永远不显示。 -->
        <el-tooltip :content="actionsDisabledReason" :disabled="!actionsDisabled" placement="top">
          <span class="srt-tip-anchor">
            <el-button size="small" text bg data-testid="sftp-results-download"
                       :disabled="!selectedPaths.length || actionsDisabled"
                       @click="emit('download', selectedPaths)">
              下载
            </el-button>
          </span>
        </el-tooltip>
        <el-tooltip :content="actionsDisabledReason" :disabled="!actionsDisabled" placement="top">
          <span class="srt-tip-anchor">
            <el-button size="small" text bg type="primary" data-testid="sftp-results-download-parse"
                       :disabled="!selectedPaths.length || actionsDisabled"
                       @click="emit('download-parse', selectedPaths)">
              下载并解析
            </el-button>
          </span>
        </el-tooltip>
      </div>
    </div>

    <!-- 5000 行靠 AG Grid 的行虚拟化吃下（row-buffer 10）：这里既不分页也不截断，
         折叠只是把该目录的行暂时移出 grid 的数据源，不是少给用户数据。 -->
    <ag-grid-vue
      :class="['ag-theme-quartz', isDark ? 'ag-theme-quartz-dark' : '', 'srt-grid']"
      :theme="'legacy'"
      style="height: 520px; width: 100%"
      :column-defs="columnDefs"
      :default-col-def="defaultColDef"
      :row-data="gridRows"
      :row-class-rules="rowClassRules"
      :row-height="30"
      :header-height="34"
      :row-buffer="10"
      :animate-rows="false"
      :suppress-field-dot-notation="true"
      :enable-cell-text-selection="true"
      overlay-no-rows-template="还没有结果"
      @row-clicked="onRowClicked"
    />
  </div>
</template>

<script lang="ts">
/**
 * 普通 `<script>` 只放本组件内部的纯件与类型（`<script setup>` 不能 export，两块 script
 * 合并成同一模块作用域 —— UphCard.vue 同款结构）。
 *
 * 曾在这里「顺手导出」的 `AUTO_GROUP_THRESHOLD` 与 `resultRows()` 已按计划 Task 17 Step 1
 * 安家到 `stores/sftpSearch.ts`（与 `RUN_HISTORY_KEEP` / `CANCEL_COOLDOWN_MS` 同一落点）：
 * 阈值与行集口径由页面和本组件**各 import 同一份**，才不会「导出的行 ≠ 看到的行」。
 */
// 类型全部走普通 <script> 的导入：两块 script 合并成同一模块作用域
import type { CandidateItem, MatchItem, SearchEngine, SearchMode } from '../../../api/sftpSearch'
import { resultRows, type SearchResultRow } from '../../../stores/sftpSearch'

/** 组行（只在 grouped 时插进数据源；叶子行沿用 store 里的原对象，保持身份不重渲染） */
export interface SearchGroupRow {
  __group: true
  __dir: string
  __count: number
  __label: string
}

/** 交给 grid 的数据源：叶子行（store 里的原对象）与合成组行混排 */
export type SearchGridRow = SearchResultRow | SearchGroupRow

/** 目录部分：同时兜住反斜杠，免得 Windows 风格路径整串被当成 basename */
export function dirnameOf(path: string): string {
  const i = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'))
  return i <= 0 ? '/' : path.slice(0, i)
}

/**
 * 命中片段拆成 [before, hit, after] 三段**文本**，由 `h('span', …)` 渲染。
 *
 * XSS 红线（spec §3.13）：`term` 是用户输入，整条链路不得出现 `v-html` /
 * innerHTML —— 全文件（含 AG Grid 35 community 的 dist）零 innerHTML 调用点，
 * 单元格文本一律走 Vue 的文本插值。`<img src=x onerror=alert(1)>` 当 term
 * 搜出来的片段就是这样一行字面文本。
 */
export function highlight(text: string, term: string, ci: boolean): Array<{ t: string; hit: boolean }> {
  if (!term) return [{ t: text, hit: false }]
  const hay = ci ? text.toLowerCase() : text
  const needle = ci ? term.toLowerCase() : term
  const i = hay.indexOf(needle)
  if (i < 0) return [{ t: text, hit: false }]
  return [{ t: text.slice(0, i), hit: false },
          { t: text.slice(i, i + term.length), hit: true },
          { t: text.slice(i + term.length), hit: false }]
}

/** 路径中段省略（前 18 … 后 24）；全路径在 tooltip 里 */
const PATH_HEAD = 18
const PATH_TAIL = 24
function middleOut(s: string): string {
  return s.length <= PATH_HEAD + PATH_TAIL + 1
    ? s
    : `${s.slice(0, PATH_HEAD)} … ${s.slice(-PATH_TAIL)}`
}

/** 值 chips 最多渲染几颗，其余折成 +N（单元格只有一行高，铺开会互相裁切） */
const VALUE_CHIPS = 5

function fmtSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

function fmtTime(epochSec: number | null | undefined): string {
  if (!epochSec) return ''
  const d = new Date(epochSec * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function isGroupRow(row: unknown): row is SearchGroupRow {
  return !!(row as SearchGroupRow | undefined)?.__group
}
</script>

<script setup lang="ts">
import { computed, defineComponent, h, markRaw, ref, watch } from 'vue'
import { AgGridVue } from 'ag-grid-vue3'
import { ModuleRegistry, AllCommunityModule, type ColDef } from 'ag-grid-community'
import { useThemeStore } from '../../../stores/theme'

// 注册 ag-grid 模块（幂等；与 DataBrowserAgGrid.vue / FileCorrelationTable.vue 同一写法，
// 不新增模块清单）
ModuleRegistry.registerModules([AllCommunityModule])

const props = withDefaults(defineProps<{
  candidates: CandidateItem[]
  matches: MatchItem[]
  mode: SearchMode
  engine: SearchEngine | null
  /** 高亮用的检索词（原样来自 run.spec.term，只作文本比对，永不进 HTML） */
  term: string
  grouped: boolean
  /** 表单的 case_sensitive：不区分大小写时高亮才与命中位置一致 */
  caseSensitive?: boolean
  /**
   * 下载入口的互斥禁用：页面把「搜索进行中 / 取消冷却 / 已有下载在跑」合并成的
   * `transferActive` 传下来（计划 Task 17 Step 5：搜索页自身的下载按钮读同一个判据）。
   */
  actionsDisabled?: boolean
  /** 为什么禁着（tooltip 文案）：只有 `actionsDisabled` 为真时才用得上 */
  actionsDisabledReason?: string
}>(), {
  caseSensitive: false,
  actionsDisabled: false,
  actionsDisabledReason: '上一次传输还在收尾，稍候即可',
})

const emit = defineEmits<{
  'selection-change': [paths: string[]]
  download: [paths: string[]]
  'download-parse': [paths: string[]]
  export: []
  'toggle-group': []
}>()

const isDark = computed(() => useThemeStore().currentTheme === 'night')

const modeLabel = computed(() =>
  props.mode === 'name' ? '文件名命中' : props.mode === 'content' ? '内容命中' : '列值命中')

const rows = computed(() => resultRows(props.candidates, props.matches, props.mode))
const showingCandidates = computed(() => props.mode === 'name' || props.matches.length === 0)
const rowKind = computed(() => (showingCandidates.value ? '候选' : '命中'))

// ---------------------------------------------------------------- 勾选（自持状态）
// 不用 AG Grid 的行选择：它的选中态挂在 node 上，而分组会重建数据源；勾选按 path 记账
// 才跨分组/折叠稳定，且 emit 给页面的就是路径数组本身。
const selected = ref<Set<string>>(new Set())
const collapsed = ref<Set<string>>(new Set())
/** 模板与 emit 都读这个（模板里 ref 已解包，不能再写 `selected.value`） */
const selectedPaths = computed(() => [...selected.value])

function togglePath(path: string): void {
  const next = new Set(selected.value)
  if (next.has(path)) next.delete(path)
  else next.add(path)
  selected.value = next
}

watch(selected, () => emit('selection-change', selectedPaths.value))

function toggleSelectAll(): void {
  selected.value = selected.value.size ? new Set() : new Set(rows.value.map(r => r.path))
}

// 换 run（页面从历史里挑一条）时行集整个换掉：旧勾选属于另一次搜索，必须清掉（lessons R5）。
// 数组-of-getter 的写法只在两个数组**换身份**时触发 —— 流式 push 只改内容，不该清勾选。
watch([() => props.candidates, () => props.matches], () => {
  selected.value = new Set()
  collapsed.value = new Set()
})

watch(() => props.grouped, () => { collapsed.value = new Set() })

// ---------------------------------------------------------------- 分组
const groups = computed(() => {
  const map = new Map<string, SearchResultRow[]>()
  for (const item of rows.value) {
    const dir = dirnameOf(item.path)
    const bucket = map.get(dir)
    if (bucket) bucket.push(item)
    else map.set(dir, [item])
  }
  return map
})

const groupDirs = computed(() => [...groups.value.keys()])

/** 组行 + 展开目录的叶子行（折叠 = 暂时不进数据源；组头计数仍看得见） */
const gridRows = computed<SearchGridRow[]>(() => {
  if (!props.grouped) return rows.value
  const out: SearchGridRow[] = []
  for (const [dir, items] of groups.value) {
    out.push({
      __group: true,
      __dir: dir,
      __count: items.length,
      __label: `${dir} · ${items.length} 个${rowKind.value}`,
    })
    if (!collapsed.value.has(dir)) out.push(...items)
  }
  return out
})

/** 表格里实际在场的叶子行数（折叠掉的目录不在此列，但计数照常报） */
const shownCount = computed(() => rows.value.length
  - [...collapsed.value].reduce((n, dir) => n + (groups.value.get(dir)?.length ?? 0), 0))

function toggleDir(dir: string): void {
  const next = new Set(collapsed.value)
  if (next.has(dir)) next.delete(dir)
  else next.add(dir)
  collapsed.value = next
}

function expandAll(): void { collapsed.value = new Set() }
function collapseAll(): void { collapsed.value = new Set(groupDirs.value) }

// ---------------------------------------------------------------- 单元格组件
// AG Grid 的 Vue cellRenderer 拿到的是 `params` prop（见 ag-grid-vue3 VueComponentFactory）。
// 一律用 h() 的**文本子节点**，等价于模板里的 `<span v-for>`；不走 HTML 字符串。
const CheckCell = markRaw(defineComponent({
  props: { params: { type: Object, required: true } },
  setup(cellProps) {
    return () => {
      const data = cellProps.params.data
      if (isGroupRow(data)) {
        return h('span', { class: 'srt-twisty' }, collapsed.value.has(data.__dir) ? '▶' : '▼')
      }
      const path: string = data?.path ?? ''
      return h('input', {
        type: 'checkbox',
        class: 'srt-check',
        checked: selected.value.has(path),
        'aria-label': `选择 ${path}`,
        onClick: (e: MouseEvent) => { e.stopPropagation(); togglePath(path) },
      })
    }
  },
}))

const SnippetCell = markRaw(defineComponent({
  props: { params: { type: Object, required: true } },
  setup(cellProps) {
    return () => {
      const row = cellProps.params.data as MatchItem
      if (isGroupRow(row)) return h('span')
      const parts = highlight(row.snippet ?? '', props.term, !props.caseSensitive)
        .map(pt => h('span', { class: pt.hit ? 'srt-hit' : undefined }, pt.t))
      const extra = (row.hits?.length ?? 0) > 1
        ? [h('span', { class: 'srt-more' }, ` +${row.hits!.length - 1} 处`)]
        : []
      return h('span', { class: 'srt-snippet' }, [...parts, ...extra])
    }
  },
}))

const ValuesCell = markRaw(defineComponent({
  props: { params: { type: Object, required: true } },
  setup(cellProps) {
    return () => {
      const row = cellProps.params.data as MatchItem
      if (isGroupRow(row)) return h('span')
      const vals = row.values ?? []
      const chips = vals.slice(0, VALUE_CHIPS).map((v: string) => h('span', { class: 'srt-chip' }, v))
      if (vals.length > VALUE_CHIPS) {
        chips.push(h('span', { class: 'srt-more' }, `+${vals.length - VALUE_CHIPS}`))
      }
      return h('span', { class: 'srt-values' }, chips)
    }
  },
}))

// ---------------------------------------------------------------- 列（随 mode 变）
const columnDefs = computed<ColDef[]>(() => {
  // 数据列与 utils/sftpSearchExport.ts 的 COLUMNS 同集合同顺序：所见即所导。
  const cols: ColDef[] = [
    { colId: 'sel', headerName: '', width: 40, pinned: 'left', cellRenderer: CheckCell,
      sortable: false, resizable: false },
    { colId: 'name', field: 'name', headerName: '名称', width: 240, pinned: 'left',
      valueGetter: (p: any) => (isGroupRow(p.data) ? p.data.__label : p.data?.name ?? ''),
      tooltipValueGetter: (p: any) => (isGroupRow(p.data) ? p.data.__dir : p.data?.path ?? '') },
  ]
  if (props.mode !== 'column') {
    cols.push({ colId: 'size', field: 'size', headerName: '大小', width: 96,
      valueFormatter: (p: any) => fmtSize(p.value) })
    cols.push({ colId: 'mtime', field: 'mtime', headerName: '修改时间', width: 140,
      valueFormatter: (p: any) => fmtTime(p.value) })
  }
  if (props.mode === 'content') {
    cols.push({ colId: 'line', field: 'line', headerName: '命中行', width: 80 })
    cols.push({ colId: 'snippet', field: 'snippet', headerName: '命中片段', minWidth: 320,
      cellRenderer: SnippetCell, wrapHeaderText: false,
      tooltipValueGetter: (p: any) => snippetTooltip(p.data) })
  }
  if (props.mode === 'column') {
    cols.push({ colId: 'column_name', field: 'column_name', headerName: '列名', width: 160 })
    cols.push({ colId: 'values', field: 'values', headerName: '值', minWidth: 260,
      cellRenderer: ValuesCell })
  }
  if (props.mode !== 'name') {
    cols.push({ colId: 'test_file', field: 'test_file', headerName: 'TestFile', width: 200 })
    cols.push({ colId: 'start_time', field: 'start_time', headerName: 'StartTime', width: 140 })
  }
  cols.push({ colId: 'path', field: 'path', headerName: '路径', minWidth: 300, flex: 1,
    valueFormatter: (p: any) => middleOut(String(p.value ?? '')),
    tooltipValueGetter: (p: any) => String(p.value ?? '') })

  // 组行用一格铺满整行：AG Grid 35 的 rowGrouping 属 Enterprise（社区版没注册
  // RowGrouping/GroupCellRenderer 模块，AllCommunityModule 的依赖清单里就没有），所以分组
  // 用「合成组行 + colSpan」自己搭 —— 只借社区能力，不加依赖、不新建第二张表。
  const nameCol = cols.find(c => c.colId === 'name')
  if (nameCol) {
    nameCol.colSpan = (p: any) => (isGroupRow(p.data) ? cols.length - 1 : 1)
  }
  return cols
})

/** 多次命中的文件：tooltip 里把所有命中一次列全（单元格只放第一条） */
function snippetTooltip(row: unknown): string {
  if (!row || isGroupRow(row)) return ''
  const m = row as MatchItem
  if (!m.hits?.length) return m.snippet ?? ''
  return m.hits.map(x => `${x.line}: ${x.snippet}`).join('\n')
}

// 分组时排序会让组序被打散（合成组行也是普通行），所以排序只在扁平档开放。
const defaultColDef = computed<ColDef>(() => ({
  sortable: !props.grouped,
  filter: false,
  resizable: true,
}))

const rowClassRules = {
  'srt-group-row': (p: any) => isGroupRow(p.data),
}

function onRowClicked(e: any): void {
  const data = e.data
  if (isGroupRow(data)) toggleDir(data.__dir)
}
</script>

<style scoped>
.srt { min-width: 0; }

.srt-bar {
  display: flex; align-items: center; gap: var(--p-space-3); flex-wrap: wrap;
  padding: var(--p-space-2) var(--p-space-3);
  background: var(--bg-2); border: 1px solid var(--border); border-bottom: none;
  border-radius: var(--p-radius-md) var(--p-radius-md) 0 0;
}
.srt-title { font-size: var(--p-fs-small); font-weight: var(--p-fw-bold); color: var(--text); }
.srt-count { font-size: var(--p-fs-dense); color: var(--text-2); }
.srt-hint { font-size: var(--p-fs-dense); color: var(--warn); }
.srt-engine { font-size: var(--p-fs-micro); color: var(--text-3); }
.srt-actions { display: flex; align-items: center; gap: var(--p-space-1); margin-left: auto; flex-wrap: wrap; }
.srt-actions :deep(.el-button) { font-size: var(--p-fs-dense); }
.srt-tip-anchor { display: inline-flex; }

/* AG Grid 主题接线：与 DataBrowserAgGrid.vue 同款 —— 只把项目语义 token 喂给 --ag-* 变量，
   两套主题靠 token 自己翻转（quartz 内置栈无 CJK 档，字族必须接 --font-sans）。 */
.srt-grid {
  --ag-background-color: var(--bg);
  --ag-foreground-color: var(--text);
  --ag-data-color: var(--text);
  --ag-header-background-color: var(--bg-2);
  --ag-header-foreground-color: var(--text);
  --ag-border-color: var(--border-2);
  --ag-row-border-color: var(--border-2);
  --ag-secondary-border-color: var(--border);
  --ag-odd-row-background-color: var(--bg);
  --ag-row-hover-color: var(--bg-3);
  --ag-selected-row-background-color: color-mix(in srgb, var(--brand) 10%, transparent);
  --ag-font-size: var(--p-fs-dense);
  --ag-font-family: var(--font-sans);
  --ag-cell-horizontal-padding: var(--p-space-2);
  --ag-input-focus-border-color: var(--brand);
  border: 1px solid var(--border);
  border-radius: 0 0 var(--p-radius-md) var(--p-radius-md);
  overflow: hidden;
}
.srt-grid :deep(.ag-cell-value) {
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0;
}
.srt-grid :deep(.ag-header-cell-label) { font-size: var(--p-fs-dense); font-weight: var(--p-fw-semibold); }
.srt-grid :deep(.ag-pinned-left-cols-container) { border-right: 1px solid var(--border-2); }

/* 组行 */
.srt-grid :deep(.srt-group-row) { background: var(--bg-3); }
.srt-grid :deep(.srt-group-row .ag-cell) { color: var(--text); font-weight: var(--p-fw-semibold); }

.srt-grid :deep(.srt-check) { accent-color: var(--brand); width: 14px; height: 14px; margin: 0 auto; cursor: pointer; }
.srt-grid :deep(.srt-twisty) { color: var(--text-2); font-size: var(--p-fs-micro); }

.srt-grid :deep(.srt-snippet) { font-family: var(--font-mono); color: var(--text-2); }
.srt-grid :deep(.srt-hit) {
  background: color-mix(in srgb, var(--brand) 30%, transparent);
  color: var(--text); font-weight: var(--p-fw-bold); border-radius: var(--p-radius-xs);
}
.srt-grid :deep(.srt-more) { color: var(--text-3); margin-left: var(--p-space-1); }
.srt-grid :deep(.srt-values) { display: flex; align-items: center; gap: var(--p-space-1); overflow: hidden; }
.srt-grid :deep(.srt-chip) {
  font-size: var(--p-fs-micro); color: var(--text-2); background: var(--bg-3);
  border: 1px solid var(--border-2); border-radius: var(--p-radius-full);
  padding: 0 var(--p-space-2); max-width: 140px; overflow: hidden; text-overflow: ellipsis;
}
</style>
