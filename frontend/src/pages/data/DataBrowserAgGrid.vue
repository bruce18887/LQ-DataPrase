<template>
  <div>
    <!-- 控制栏（DataBrowserToolbar：筛选控件 + 操作按钮） -->
    <DataBrowserToolbar
      :test-cols="testCols"
      :selected-test-cols="selectedTestCols"
      :passfail="passfail"
      :site-filter="siteFilter"
      :site-options="siteOptions"
      :site-col-disabled="siteColDisabled"
      :autosize-mode="autosizeMode"
      :pinned-col="pinnedCol"
      :all-cols="allCols"
      :loading="loading"
      :exporting-excel="exportingExcel"
      :exporting-csv="exportingCsv"
      @update:selected-test-cols="selectedTestCols = $event"
      @update:passfail="passfail = $event"
      @update:site-filter="siteFilter = $event"
      @update:autosize-mode="autosizeMode = $event"
      @update:pinned-col="pinnedCol = $event"
      @load="reload"
      @export-excel="exportExcel"
      @export-csv="exportCsv"
    />

    <!-- 质量概览条（复用 /summary/ 接口，失败静默隐藏） -->
    <DataQualityBar :file-id="fileId" />

    <!-- 数据表格 -->
    <div v-loading="loading">
      <p v-if="dataLoaded" style="margin-bottom: 8px; font-size: 14px">
        共 <b>{{ rowCount }}</b> 条数据
        <span v-if="failRowCount > 0" style="color: var(--error); margin-left: 12px; font-weight: bold">
          （Fail: {{ failRowCount }} 行<template v-if="siteFilter">，Site {{ siteFilter }} 过滤后</template>）
        </span>
      </p>
      <div class="ag-grid-wrapper" :style="gridWrapperStyle" @contextmenu="onGridContextMenu">
        <el-empty v-if="!fileId" description="请先在上方选择文件" :image-size="80">
          <el-button type="primary" @click="emit('goto-files')">去文件列表选择</el-button>
        </el-empty>
        <!-- 服务端分页（Infinite Row Model）：fileId 存在即挂载（不能门控 dataLoaded——否则 datasource 鸡生蛋）；
             空态由 overlayNoRowsTemplate 呈现（筛选后 0 行 / 加载完成无匹配） -->
        <ag-grid-vue
          v-else
          :class="['ag-theme-quartz', isDark ? 'ag-theme-quartz-dark' : '', 'ag-custom-theme']"
          :theme="'legacy'"
          :style="{ height: `${tableHeight}px`, width: '100%', contain: 'layout style' }"
          :columnDefs="columnDefs"
          :rowModelType="'infinite'"
          :datasource="datasource"
          :infiniteInitialRowCount="BLOCK_SIZE"
          :cacheBlockSize="BLOCK_SIZE"
          :maxBlocksInCache="20"
          :overlayNoRowsTemplate="'没有匹配的数据'"
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
import { ref, computed, watch, onMounted, onUnmounted, markRaw } from 'vue'
import { AgGridVue } from 'ag-grid-vue3'
import { ElMessage } from 'element-plus'
import api from '../../api'
import { datafilesApi } from '../../api/datafiles'
import { authApi } from '../../api/auth'
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
import { ModuleRegistry, AllCommunityModule, type IDatasource } from 'ag-grid-community'
ModuleRegistry.registerModules([AllCommunityModule])

const props = defineProps<{ fileId: number | null; fileName?: string }>()
const emit = defineEmits<{ 'file-missing': []; 'goto-files': [] }>()
const themeStore = useThemeStore()
const filesStore = useFilesStore()
const isDark = computed(() => themeStore.currentTheme === 'night')

const passfail = ref('')
const siteFilter = ref('')
const autosizeMode = ref('none')
const pinnedCol = ref('')
// 显示测试列：选中集非空 = 表格仅显示这些测试列（系统列恒显）；空集 = 显示全部
const selectedTestCols = ref<string[]>([])
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
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  if (passfailTimer) clearTimeout(passfailTimer)
  // siteFilterTimer 也必须清：watcher 随组件作用域自动停止，但已排期的
  // setTimeout 仍会在卸载后触发 reload() → 对已销毁的 grid 发幽灵请求。
  if (siteFilterTimer) clearTimeout(siteFilterTimer)
})

const gridWrapperStyle = computed(() => ({
  containIntrinsicSize: `auto ${tableHeight.value}px`,
}))

const allCols = ref<string[]>([])
const colMeta = ref<Record<string, { unit: string; min: string; max: string }>>({})
const numericColumns = ref<string[]>([])
const siteOptions = ref<string[]>([])
const rowCount = ref(0)
const failRowCount = ref(0)

// 请求竞态防护：快速切换筛选时丢弃过期响应（只丢弃 refs 更新，grid 本身有块版本号守卫）
let loadSeq = 0

// 服务端分页块大小（IRM cacheBlockSize）
const BLOCK_SIZE = 100

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
    // 非数值列不弹。IRM 下无法全行扫描——后端 page==1 返回 numeric_columns
    // （dtype + object 列值级判定，镜像旧前端 Number.isFinite 语义）
    if (!numericColumns.value.includes(col)) return
    analyzeParam.value = col
    histDialogVisible.value = true
    return
  }
  handleBodyContextMenu(e)
}

// 系统列（记录级列）：恒显示且排在测试列之前，由后端按文件格式权威下发
// （/browse/ page==1 的 system_columns，来源 apps.datafiles.parsers.SYSTEM_COLUMNS）。
// 不用列名前缀启发式：测试项名可能与记录列同名前缀（Device_Fused_Flag1/2、
// SITE_CHECK 是测试项，却以 device_/site_ 开头，2026-08-25 曾被误判前置）。
const systemCols = ref<string[]>([])

// 默认隐藏列（系统设置 → 表格设置）：命中列 hide=true，列仍存在，用户可通过
// ag-grid 表头列菜单重新显示；与导出 Excel 的隐藏列共用同一份设置。
const defaultHiddenCols = ref<string[]>([])
onMounted(async () => {
  try {
    const { data } = await authApi.getSettings()
    defaultHiddenCols.value = Array.isArray(data?.default_hidden_columns)
      ? data.default_hidden_columns
      : []
  } catch {
    // 设置加载失败：保持全部可见（静默降级）
  }
})

function isSystemCol(name: string): boolean {
  return systemCols.value.includes(name)
}

// 全部测试列（系统列排除，供「显示测试列」选择器使用）
const testCols = computed(() => allCols.value.filter((c) => !isSystemCol(c)))

// 显示列：系统列始终显示；选中测试列非空时仅显示选中测试列（空集 = 全部显示）
const displayCols = computed(() => {
  const sysCols: string[] = []
  const testCols: string[] = []
  for (const c of allCols.value) {
    if (isSystemCol(c)) {
      sysCols.push(c)
    } else {
      testCols.push(c)
    }
  }
  let shown = testCols
  if (selectedTestCols.value.length) {
    shown = testCols.filter((c) => selectedTestCols.value.includes(c))
  }
  return [...sysCols, ...shown]
})

// ── 固定 Bin 列 fail 单元格右键菜单（判定链 + 定位逻辑见 composable） ──
const {
  gridApi,
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

// ── Site 筛选（服务端）：选项来自 page==1 响应的 site_options，过滤走 reload ──
const siteColDisabled = computed(() => {
  if (!allCols.value.length) return true
  return !allCols.value.some((c) => /site/i.test(c) && isSystemCol(c))
})

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
      // 服务端列过滤（方案 A）：数值列挂 number filter（等/不等/大于/小于/区间），
      // 其余挂 text filter（包含/开头/结尾）——IRM 下 filter 类型必须显式指定
      filter: numericColumns.value.includes(col) ? 'agNumberColumnFilter' : 'agTextColumnFilter',
    }

    // 默认隐藏列（系统设置）：列仍解析/保留，仅默认不可见（列菜单可重新显示）
    if (defaultHiddenCols.value.includes(col)) {
      colDef.hide = true
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
  // 服务端列过滤（方案 A）：apply/reset 按钮——避免每敲一键就触发整页重载（官方推荐服务端场景）
  filterParams: { buttons: ['apply', 'reset'] },
  wrapHeaderText: true,
  autoHeaderHeight: true,
  // __fail_cells__ 是原生数组（不再逐格 JSON.parse——ag-grid 每渲染一个可见单元格都会调用 cellStyle）
  cellStyle: (params: any) => {
    if (params.data && params.data.__fail_cells__) {
      const failCols: string[] = params.data.__fail_cells__
      if (failCols.includes(params.colDef.field)) {
        if (isDark.value) {
          return { backgroundColor: '#b91c1c', color: '#fecaca', fontWeight: 'bold' }
        }
        return { backgroundColor: 'var(--error-2)', color: '#ffffff', fontWeight: 'bold' }
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
    // 切换文件后 Site/显示测试列/元信息属于旧文件，重置避免误导
    siteFilter.value = ''
    selectedTestCols.value = []
    siteOptions.value = []
    numericColumns.value = []
    systemCols.value = []
    allCols.value = []
    colMeta.value = {}
    rowCount.value = 0
    failRowCount.value = 0
    dataLoaded.value = false
    if (props.fileId) {
      loadSeq++ // 递增代次：旧文件在途响应全部丢弃
      reload()
    } else {
      clearGrid()
    }
  }
)

// Pass/Fail 切换 → 服务端重新分页（IRM purge 全量重载）。
// 300ms 防抖：快速连点 Pass/Fail/All 只发最后一次。
let passfailTimer: ReturnType<typeof setTimeout> | null = null
watch(passfail, () => {
  if (passfailTimer) clearTimeout(passfailTimer)
  passfailTimer = setTimeout(() => {
    passfailTimer = null
    if (props.fileId) reload()
  }, 300)
})

// Site 筛选改服务端（原本地即时过滤）→ 同样 300ms 防抖
let siteFilterTimer: ReturnType<typeof setTimeout> | null = null
watch(siteFilter, () => {
  if (siteFilterTimer) clearTimeout(siteFilterTimer)
  siteFilterTimer = setTimeout(() => {
    siteFilterTimer = null
    if (props.fileId) reload()
  }, 300)
})

// 文件变更（删除等）后重新校验当前文件；若已被删除，后端 404 → 清空表格。
watch(() => filesStore.filesVersion, () => {
  if (props.fileId) reload()
})

// 筛选/行数变化触发行重排 → 右键菜单索引失效，关闭
watch([rowCount, siteFilter], () => closeBinMenu())

function clearGrid() {
  closeBinMenu()
  allCols.value = []
  colMeta.value = {}
  numericColumns.value = []
  siteOptions.value = []
  systemCols.value = []
  rowCount.value = 0
  failRowCount.value = 0
  dataLoaded.value = false
}

/**
 * IRM datasource（单例）：闭包读当前 ref 值（不快照）——purge 复用同一 datasource
 * 与 sortModel 快照，pass_filter/site_filter/sort 变化都必须取最新值。
 * 排序变更由 ag-grid 自动触发（sortChanged → reset → getRows 带新 sortModel）。
 */
const datasource: IDatasource = {
  getRows: async (params) => {
    if (!props.fileId) {
      params.failCallback()
      return
    }
    const seq = ++loadSeq
    try {
      const resp = await datafilesApi.browse({
        datafile_id: props.fileId,
        page: Math.floor(params.startRow / BLOCK_SIZE) + 1,
        page_size: BLOCK_SIZE,
        pass_filter: passfail.value,
        site_filter: siteFilter.value,
        sort_model: JSON.stringify(params.sortModel),
        filter_model: JSON.stringify(params.filterModel),
      })
      const d = resp.data
      // 新旧响应都喂 grid（IRM 有块版本号守卫丢弃过期块数据）；块数据 zip 成行对象
      params.successCallback(zipRows(d), d.total)
      if (seq !== loadSeq) return // 旧代响应只喂 grid，不更新 refs
      applyMeta(d)
    } catch (e: any) {
      params.failCallback() // 失败块不自动重试
      if (e?.response?.status === 404) {
        clearGrid()
        emit('file-missing')
      }
      if (seq === loadSeq) loading.value = false
    }
  },
}

/** 传输格式 zip：headers + data（行值数组）+ fail_cells（并行数组）→ markRaw 行对象。
 *  markRaw 跳过 Vue 深响应式（68k×142 依赖追踪实测 +1.3GB 堆 + 5s 阻塞；块 ≤100 行成本已低）。 */
function zipRows(d: { headers?: string[]; data?: unknown[][]; fail_cells?: string[][] }): Record<string, any>[] {
  const cols = d.headers ?? []
  const vals = d.data ?? []
  const fails = d.fail_cells ?? []
  const rows = new Array<Record<string, any>>(vals.length)
  for (let i = 0; i < vals.length; i++) {
    const v = vals[i]
    const o: Record<string, any> = { __fail_cells__: fails[i] ?? [] }
    for (let j = 0; j < cols.length; j++) o[cols[j]] = v[j]
    rows[i] = markRaw(o)
  }
  return rows
}

/** 首块（或代次最新块）响应的元信息落地；每块响应都带 headers/col_meta/bin_column */
function applyMeta(d: any) {
  allCols.value = d.headers ?? []
  colMeta.value = (d.col_meta ?? {}) as Record<string, { unit: string; min: string; max: string }>
  rowCount.value = d.total ?? 0
  failRowCount.value = d.fail_row_count ?? 0
  dataLoaded.value = true
  loading.value = false

  // 站点选项与数值列仅 page==1 响应携带
  if (d.site_options) {
    siteOptions.value = [...d.site_options].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
  }
  if (d.numeric_columns) numericColumns.value = d.numeric_columns
  // 系统列（记录级列）仅 page==1 响应携带（page>1 不覆盖、不置空）
  if (d.system_columns) systemCols.value = d.system_columns

  const binCol = d.bin_column as string
  if (!pinnedCol.value) {
    // 首次加载：自动固定 Bin 列
    if (binCol && allCols.value.includes(binCol)) {
      pinnedCol.value = binCol
    }
  } else if (!allCols.value.includes(pinnedCol.value)) {
    // 切换文件后旧固定列失效：回退到 Bin 列
    pinnedCol.value = binCol && allCols.value.includes(binCol) ? binCol : ''
  }
}

/** 重新加载：清空 IRM 缓存全部块 + 回顶部（purge 不重置滚动位置） */
function reload() {
  if (!props.fileId) return
  closeBinMenu()
  loading.value = true
  loadSeq++ // 新代次：旧在途响应不再更新 refs
  gridApi.value?.purgeInfiniteCache()
  gridApi.value?.ensureIndexVisible(0)
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
  --ag-background-color: var(--bg);
  --ag-foreground-color: var(--text);
  --ag-data-color: var(--text);
  --ag-header-background-color: var(--bg-2);
  --ag-header-foreground-color: var(--text);
  --ag-odd-row-background-color: var(--bg-2);
  --ag-row-hover-color: var(--bg-3);
  --ag-selected-row-background-color: rgba(37, 99, 235, 0.08);
  --ag-row-border-color: var(--border-2);
  --ag-border-color: var(--border-2);
  --ag-secondary-border-color: var(--border);
  --ag-cell-horizontal-padding: 8px;
  --ag-font-size: 12px;
  --ag-header-column-separator-display: block;
  --ag-header-column-separator-color: var(--border-2);
  --ag-input-focus-border-color: var(--brand);
  --ag-range-selection-border-color: var(--brand);
  /* flashCells 定位反馈色（light：品牌蓝） */
  --ag-value-change-value-highlight-background-color: rgba(37, 99, 235, 0.35);
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-row.row-odd) {
  background-color: var(--bg-2) !important;
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-row.row-even) {
  background-color: var(--bg) !important;
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-cell) {
  border-right: 1px solid var(--border-2);
  border-bottom: 1px solid var(--border-2);
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-header) {
  background-color: var(--bg-2) !important;
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-header-cell) {
  border-right: 1px solid var(--border-2);
  background-color: var(--bg-2) !important;
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-header-cell-label) {
  font-size: 12px;
  color: var(--text);
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-pinned-left-cols-container) {
  border-right: 2px solid var(--text-3);
  box-shadow: 2px 0 4px rgba(0, 0, 0, 0.05);
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-pinned-left-header) {
  border-right: 2px solid var(--text-3);
  background-color: var(--bg-2) !important;
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-cell-first-left-pinned) {
  border-right: 1px solid var(--border-2);
}

:deep(.ag-custom-theme.ag-theme-quartz .ag-header-cell-resize::after) {
  background-color: var(--border-2);
}

/* sorting icons */
:deep(.ag-custom-theme.ag-theme-quartz .ag-header-cell-sorted-asc .ag-header-cell-label,
      .ag-custom-theme.ag-theme-quartz .ag-header-cell-sorted-desc .ag-header-cell-label) {
  color: var(--text);
}
</style>
