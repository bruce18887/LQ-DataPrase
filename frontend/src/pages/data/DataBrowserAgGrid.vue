<template>
  <div>
    <!-- 控制栏（DataBrowserToolbar：筛选控件 + 全文搜索 + 操作按钮） -->
    <DataBrowserToolbar
      :search-col="searchCol"
      :search-test-col="searchTestCol"
      :passfail="passfail"
      :site-filter="siteFilter"
      :site-options="siteOptions"
      :site-col-disabled="siteColDisabled"
      :autosize-mode="autosizeMode"
      :pinned-col="pinnedCol"
      :hidden-cols="hiddenCols"
      :all-cols="allCols"
      :loading="loading"
      :exporting-excel="exportingExcel"
      :exporting-csv="exportingCsv"
      @update:search-col="searchCol = $event"
      @update:search-test-col="searchTestCol = $event"
      @update:passfail="passfail = $event"
      @update:site-filter="siteFilter = $event"
      @update:autosize-mode="autosizeMode = $event"
      @update:pinned-col="pinnedCol = $event"
      @update:hidden-cols="hiddenCols = $event"
      @load="loadData"
      @export-excel="exportExcel"
      @export-csv="exportCsv"
    />

    <!-- 质量概览条（复用 /summary/ 接口，失败静默隐藏） -->
    <DataQualityBar :file-id="fileId" />

    <!-- 数据表格 -->
    <div v-loading="loading">
      <p v-if="dataLoaded" style="margin-bottom: 8px; font-size: 14px">
        共 <b>{{ rowCount }}</b> 条数据
        <span v-if="failRowCount > 0" style="color: var(--color-error); margin-left: 12px; font-weight: bold">
          （Fail: {{ failRowCount }} 行<template v-if="siteFilter">，Site {{ siteFilter }} 过滤后</template>）
        </span>
      </p>
      <div class="ag-grid-wrapper" :style="gridWrapperStyle" @contextmenu="onGridContextMenu">
        <el-empty v-if="!fileId" description="请先在上方选择文件" :image-size="80">
          <el-button type="primary" @click="emit('goto-files')">去文件列表选择</el-button>
        </el-empty>
        <ag-grid-vue
          v-else-if="dataLoaded && rowCount > 0"
          :class="['ag-theme-quartz', isDark ? 'ag-theme-quartz-dark' : '', 'ag-custom-theme']"
          :style="{ height: `${tableHeight}px`, width: '100%', contain: 'layout style' }"
          :columnDefs="columnDefs"
          :rowData="filteredRowData"
          :defaultColDef="defaultColDef"
          :autoSizeStrategy="autoSizeStrategy"
          :rowHeight="30"
          :headerHeight="35"
          :rowBuffer="10"
          :enableCellTextSelection="true"
          :ensureDomOrder="true"
          :suppressFieldDotNotation="true"
          :animateRows="true"
          :rowClassRules="rowClassRules"
          @grid-ready="onGridReady"
        />
        <el-empty v-else-if="dataLoaded" description="没有匹配的数据" :image-size="80" />
      </div>
    </div>

    <!-- 列直方图对话框（右键列名打开，复用分析页 HistogramChart + StatsSummary） -->
    <HistogramColumnDialog
      :visible="histDialogVisible"
      :file-id="props.fileId"
      :param="analyzeParam"
      :unit="colMeta[analyzeParam]?.unit ?? ''"
      @close="histDialogVisible = false"
    />

    <!-- 固定 Bin 列 fail 单元格右键菜单（定位到该行 Fail 单元格） -->
    <BinCellContextMenu
      :visible="binMenuVisible"
      :x="binMenuX"
      :y="binMenuY"
      :row-index="binMenuRowIndex"
      :bin-value="binMenuBinValue"
      :fail-cols="binMenuFailCols"
      @close="closeBinMenu"
      @goto-fail="goToFailCell"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { AgGridVue } from 'ag-grid-vue3'
import { ElMessage } from 'element-plus'
import api from '../../api'
import { datafilesApi } from '../../api/datafiles'
import { useThemeStore } from '../../stores/theme'
import { useFilesStore } from '../../stores/files'
import DataBrowserToolbar from './components/browser/DataBrowserToolbar.vue'
import HistogramColumnDialog from './components/browser/HistogramColumnDialog.vue'
import DataQualityBar from './components/browser/DataQualityBar.vue'
import BinCellContextMenu from './components/browser/BinCellContextMenu.vue'
import { useBinCellMenu } from './composables/useBinCellMenu'
import { downloadBlob, sanitizeFilename, extractFilenameFromContentDisposition } from '../../utils/download'
import { getExportTimeoutMs } from '../../utils/exportTimeout'

// Register ag-grid modules (required since v33+)
import { ModuleRegistry, AllCommunityModule } from 'ag-grid-community'
ModuleRegistry.registerModules([AllCommunityModule])

const props = defineProps<{ fileId: number | null; fileName?: string }>()
const emit = defineEmits<{ 'file-missing': []; 'goto-files': [] }>()
const themeStore = useThemeStore()
const filesStore = useFilesStore()
const isDark = computed(() => themeStore.currentTheme === 'night')

const searchCol = ref('')
const searchTestCol = ref('')
const passfail = ref('')
const siteFilter = ref('')
const autosizeMode = ref('none')
const pinnedCol = ref('')
const hiddenCols = ref<string[]>([])
const loading = ref(false)
const exportingExcel = ref(false)
const exportingCsv = ref(false)
const dataLoaded = ref(false)

// 表格高度随视口自适应（页头 + tab + 横幅 + 控制栏约 320px 固定占位）
const TABLE_TOP_OFFSET = 320
const tableHeight = ref(Math.max(320, window.innerHeight - TABLE_TOP_OFFSET))
function onResize() {
  tableHeight.value = Math.max(320, window.innerHeight - TABLE_TOP_OFFSET)
}
onMounted(() => window.addEventListener('resize', onResize))
onUnmounted(() => window.removeEventListener('resize', onResize))

const gridWrapperStyle = computed(() => ({
  containIntrinsicSize: `auto ${tableHeight.value}px`,
}))

const allCols = ref<string[]>([])
const rowData = ref<Record<string, any>[]>([])
const colMeta = ref<Record<string, { unit: string; min: string; max: string }>>({})

// 请求竞态防护：快速切换筛选时丢弃过期响应
let loadSeq = 0

// ── 列直方图（右键列名打开） ──
const histDialogVisible = ref(false)
const analyzeParam = ref('')

/**
 * 右键列头 → 打开该列分布直方图。
 * ag-grid 表头单元格渲染 col-id 属性，事件委托无需自定义 headerComponent；
 * 右键固定 Bin 列 fail 单元格 → 弹定位菜单（handleBodyContextMenu 内部 preventDefault）；
 * 其余 body 单元格右键放行（保留浏览器复制菜单）。
 */
function onGridContextMenu(e: MouseEvent) {
  closeBinMenu() // 任何右键先关旧菜单
  const header = (e.target as HTMLElement).closest('.ag-header-cell')
  if (header) {
    e.preventDefault()
    const col = header.getAttribute('col-id')
    if (!col || !allCols.value.includes(col)) return
    // 非数值列（Serial 等）不弹
    const v = rowData.value[0]?.[col]
    if (v === null || v === undefined || v === '' || Number.isNaN(Number(v))) return
    analyzeParam.value = col
    histDialogVisible.value = true
    return
  }
  handleBodyContextMenu(e)
}

// System columns that should appear first
const SYSTEM_COLS = ['SOFT_BIN', 'SW_Bin', 'HARD_BIN', 'Site', 'SITE', 'site', 'X', 'Y', 'x', 'y', 'Serial', 'SERIAL', 'serial', 'Wafer', 'WAFER', 'wafer', 'Device', 'DEVICE', 'device']

function isSystemCol(name: string): boolean {
  const baseName = name.split(' ')[0].split('(')[0].trim()
  return SYSTEM_COLS.includes(baseName) || SYSTEM_COLS.some(sc => name.toLowerCase().includes(sc.toLowerCase()))
}

// Filtered columns
const displayCols = computed(() => {
  let cols = [...allCols.value]

  if (searchCol.value) {
    const q = searchCol.value.toLowerCase()
    cols = cols.filter(c => c.toLowerCase().includes(q))
  }

  // 用户主动隐藏的列
  if (hiddenCols.value.length) {
    cols = cols.filter((c) => !hiddenCols.value.includes(c))
  }

  // Sort: system first
  const sysCols: string[] = []
  const testCols: string[] = []
  for (const c of cols) {
    if (isSystemCol(c)) {
      sysCols.push(c)
    } else {
      testCols.push(c)
    }
  }
  cols = [...sysCols, ...testCols]

  // Move selected test col to front (after system cols)
  if (searchTestCol.value && searchTestCol.value !== '' && cols.includes(searchTestCol.value)) {
    const idx = cols.indexOf(searchTestCol.value)
    if (idx >= 0) {
      cols.splice(idx, 1)
      cols.splice(sysCols.length, 0, searchTestCol.value)
    }
  }

  return cols
})

// ── 固定 Bin 列 fail 单元格右键菜单（判定链 + 定位逻辑见 composable） ──
const {
  visible: binMenuVisible,
  x: binMenuX,
  y: binMenuY,
  rowIndex: binMenuRowIndex,
  binValue: binMenuBinValue,
  failCols: binMenuFailCols,
  onGridReady,
  close: closeBinMenu,
  handleBodyContextMenu,
  goToFailCell,
} = useBinCellMenu({ pinnedCol, displayCols })

// ── Site 本地过滤 ──
const siteCol = computed(() => {
  if (!allCols.value.length) return ''
  return allCols.value.find((c) => /site/i.test(c) && isSystemCol(c)) ?? ''
})
const siteColDisabled = computed(() => !siteCol.value)
const siteOptions = computed(() => {
  if (!siteCol.value) return []
  const seen = new Set<string>()
  for (const r of rowData.value) {
    const v = r[siteCol.value]
    if (v !== null && v !== undefined && v !== '') seen.add(String(v))
  }
  return [...seen].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
})

/** 表格实际显示的行（Site 本地过滤，与导出 site_filter 语义一致） */
const filteredRowData = computed(() => {
  if (!siteFilter.value || !siteCol.value) return rowData.value
  return rowData.value.filter((r) => String(r[siteCol.value]) === siteFilter.value)
})

const rowCount = computed(() => filteredRowData.value.length)

/** Fail 行数：基于过滤后行本地计算（后端 fail_row_count 是文件级全量，与筛选语义不一致） */
const failRowCount = computed(() =>
  filteredRowData.value.filter((r) => (JSON.parse(r.__fail_cells__ ?? '[]') as string[]).length > 0).length
)

const columnDefs = computed<any[]>(() => {
  const defs: any[] = []
  for (const col of displayCols.value) {
    const meta = colMeta.value[col]
    let header = col
    if (meta) {
      const parts = [col]
      if (meta.unit && meta.unit !== '-' && meta.unit !== 'None') {
        parts.push(` (${meta.unit})`)
      }
      if (meta.min !== '' || meta.max !== '') {
        parts.push(` [${meta.min || '-'}, ${meta.max || '-'}]`)
      }
      header = parts.join('')
    }

    const colDef: any = {
      field: col,
      headerName: header,
    }

    if (pinnedCol.value && col === pinnedCol.value) {
      colDef.pinned = 'left'
    }

    defs.push(colDef)
  }

  defs.push({
    field: '__fail_cells__',
    headerName: '',
    hide: true,
  })

  return defs
})

const defaultColDef = {
  editable: false,
  sortable: true,
  resizable: true,
  filter: true,
  wrapHeaderText: true,
  autoHeaderHeight: true,
  cellStyle: (params: any) => {
    if (params.data && params.data.__fail_cells__) {
      const failCols: string[] = JSON.parse(params.data.__fail_cells__)
      if (failCols.includes(params.colDef.field)) {
        if (isDark.value) {
          return { backgroundColor: '#b91c1c', color: '#fecaca', fontWeight: 'bold' }
        }
        return { backgroundColor: '#dc2626', color: '#ffffff', fontWeight: 'bold' }
      }
    }
    return null
  },
}

const autoSizeStrategy = computed(() => {
  if (autosizeMode.value === 'fitCellContents') {
    return { type: 'fitCellContents', skipHeader: false } as any
  }
  if (autosizeMode.value === 'fitGridWidth') {
    return { type: 'fitGridWidth' } as any
  }
  return undefined
})

const rowClassRules = {
  'row-even': (params: any) => params.node.rowIndex % 2 === 0,
  'row-odd': (params: any) => params.node.rowIndex % 2 !== 0,
}

watch(
  () => props.fileId,
  () => {
    // 切换文件后 Site/隐藏列选项属于旧文件，重置避免误导
    siteFilter.value = ''
    hiddenCols.value = []
    if (props.fileId) loadData()
    else clearGrid()
  }
)

// Pass/Fail 切换即重新加载（含未加载数据时预先选择，选文件后按当前筛选生效）
watch(passfail, () => {
  if (props.fileId) loadData()
})

// 文件变更（删除等）后重新校验当前文件；若已被删除，后端 404 → 清空表格。
watch(() => filesStore.filesVersion, () => {
  if (props.fileId) loadData()
})

// Site 本地筛选触发行重排 → 右键菜单索引失效，关闭
watch(filteredRowData, () => closeBinMenu())

function clearGrid() {
  closeBinMenu()
  rowData.value = []
  allCols.value = []
  colMeta.value = {}
  dataLoaded.value = false
}

async function loadData() {
  if (!props.fileId) {
    clearGrid()
    return
  }
  closeBinMenu()
  const seq = ++loadSeq
  loading.value = true
  try {
    const resp = await datafilesApi.browse({
      datafile_id: props.fileId,
      page_size: 99999,
      pass_filter: passfail.value,
    })
    if (seq !== loadSeq) return // 已有更新的请求，丢弃本次响应
    const data = resp.data

    allCols.value = data.headers ?? []

    const rawColMeta = (data.col_meta ?? {}) as Record<string, { unit: string; min: string; max: string }>
    colMeta.value = rawColMeta

    const binCol = data.bin_column as string
    if (!pinnedCol.value) {
      // 首次加载：自动固定 Bin 列
      if (binCol && allCols.value.includes(binCol)) {
        pinnedCol.value = binCol
      }
    } else if (!allCols.value.includes(pinnedCol.value)) {
      // 切换文件后旧固定列失效：回退到 Bin 列
      pinnedCol.value = binCol && allCols.value.includes(binCol) ? binCol : ''
    }

    rowData.value = (data.rows as Record<string, any>[]) ?? []

    dataLoaded.value = true
  } catch (e: any) {
    if (e?.response?.status === 404) {
      // 文件已被删除：清空残留表格并通知父级重置 activeFileId。
      // （错误 toast 由 axios 拦截器统一弹出）
      clearGrid()
      emit('file-missing')
    }
  } finally {
    loading.value = false
  }
}

async function exportExcel() {
  exportingExcel.value = true
  try {
    const resp = await api.post(
      '/export/to_excel/',
      { file_id: props.fileId, passfail: passfail.value, site_filter: siteFilter.value },
      // 大文件（万行×百列）excelize 导出可达数十秒，必须放宽超时（全局 30s 会 abort → Broken pipe）；
      // 超时秒数由系统设置「导出超时」控制（默认 600s）
      { responseType: 'blob', timeout: await getExportTimeoutMs() }
    )
    downloadBlob(resp.data as Blob, resolveExportName(resp.headers as Record<string, string>, 'export.xlsx', '_analysis.xlsx'))
    ElMessage.success('下载完成')
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  } finally {
    exportingExcel.value = false
  }
}

async function exportCsv() {
  exportingCsv.value = true
  try {
    const resp = await api.post(
      '/export/to_csv/',
      { file_id: props.fileId, passfail: passfail.value, site_filter: siteFilter.value },
      { responseType: 'blob', timeout: await getExportTimeoutMs() }
    )
    downloadBlob(resp.data as Blob, resolveExportName(resp.headers as Record<string, string>, 'export.csv', '_data.csv'))
    ElMessage.success('下载完成')
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  } finally {
    exportingCsv.value = false
  }
}

/** 导出文件名：优先解析后端 Content-Disposition，其次用文件名兜底，最后默认名 */
function resolveExportName(headers: Record<string, string>, fallback: string, suffix: string): string {
  const parsed = extractFilenameFromContentDisposition(headers['content-disposition'])
  if (parsed) return parsed
  if (props.fileName) {
    const base = props.fileName.replace(/\.csv$/i, '')
    return sanitizeFilename(`${base}${suffix}`)
  }
  return fallback
}
</script>

<style scoped>
/* ----- Grid wrapper: CSS containment prevents repaint propagation on theme switch ----- */
.ag-grid-wrapper {
  contain: layout style paint;
  content-visibility: auto;
  contain-intrinsic-size: auto 700px;
}

/* ================================================================
   AG Grid light-theme baseline (scoped — only applies inside this component)
   ================================================================ */
:deep(.ag-custom-theme.ag-theme-quartz) {
  --ag-background-color: var(--bg-primary);
  --ag-foreground-color: var(--text-primary);
  --ag-data-color: var(--text-primary);
  --ag-header-background-color: var(--bg-secondary);
  --ag-header-foreground-color: var(--text-primary);
  --ag-odd-row-background-color: var(--bg-secondary);
  --ag-row-hover-color: var(--bg-tertiary);
  --ag-selected-row-background-color: rgba(37, 99, 235, 0.08);
  --ag-row-border-color: var(--border-default);
  --ag-border-color: var(--border-default);
  --ag-secondary-border-color: var(--border-muted);
  --ag-cell-horizontal-padding: 8px;
  --ag-font-size: 12px;
  --ag-header-column-separator-display: block;
  --ag-header-column-separator-color: var(--border-default);
  --ag-input-focus-border-color: var(--brand-primary);
  --ag-range-selection-border-color: var(--brand-primary);
  /* flashCells 定位反馈色（light：品牌蓝） */
  --ag-value-change-value-highlight-background-color: rgba(37, 99, 235, 0.35);
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-row.row-odd) {
  background-color: var(--bg-secondary) !important;
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-row.row-even) {
  background-color: var(--bg-primary) !important;
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-cell) {
  border-right: 1px solid var(--border-default);
  border-bottom: 1px solid var(--border-default);
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-header) {
  background-color: var(--bg-secondary) !important;
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-header-cell) {
  border-right: 1px solid var(--border-default);
  background-color: var(--bg-secondary) !important;
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-header-cell-label) {
  font-size: 12px;
  color: var(--text-primary);
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-pinned-left-cols-container) {
  border-right: 2px solid var(--border-emphasis);
  box-shadow: 2px 0 4px rgba(0, 0, 0, 0.05);
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-pinned-left-header) {
  border-right: 2px solid var(--border-emphasis);
  background-color: var(--bg-secondary) !important;
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-cell-first-left-pinned) {
  border-right: 1px solid var(--border-default);
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-header-cell-resize::after) {
  background-color: var(--border-default);
}

/* sorting icons */
:deep(.ag-custom-theme.ag-theme-quartz .ag-header-cell-sorted-asc .ag-header-cell-label,
      .ag-custom-theme.ag-theme-quartz .ag-header-cell-sorted-desc .ag-header-cell-label) {
  color: var(--text-primary);
}
</style>

<!-- ================================================================
     AG Grid Dark Theme — relies on ag-theme-quartz-dark built-in
     palette with minimal custom overrides for brand alignment.
     Using ag-theme-quartz-dark class toggle (not CSS var storm)
     avoids expensive :root.theme-night re-evaluation on every cell.
     ================================================================ -->
<style>
/* Pin column shadow: stronger in dark */
:root.theme-night .ag-custom-theme.ag-theme-quartz .ag-pinned-left-cols-container {
  box-shadow: 2px 0 8px rgba(0, 0, 0, 0.4) !important;
}

/* Brand-accent selection row */
:root.theme-night .ag-custom-theme.ag-theme-quartz .ag-row-selected {
  background-color: rgba(79, 172, 254, 0.18) !important;
}

/* flashCells 定位反馈色（dark：琥珀黄，与暗色系对比明显） */
:root.theme-night .ag-custom-theme.ag-theme-quartz {
  --ag-value-change-value-highlight-background-color: rgba(253, 216, 53, 0.4);
}
</style>
