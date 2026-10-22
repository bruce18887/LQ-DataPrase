<template>
  <div>
    <!-- 当前文件横幅（与导出工具 tab 同款）：文件级操作挂在右端，不再单独占一行 -->
    <ActiveFileBanner
      :model-value="props.fileId"
      :files="props.files"
      @update:model-value="emit('update:fileId', $event)"
    >
      <template #actions>
        <el-button type="primary" :loading="loading" @click="reload()">
          <el-icon><Refresh /></el-icon> 加载数据
        </el-button>
        <el-button :loading="exportingExcel" :disabled="!props.fileId" @click="exportExcel">
          <el-icon><Download /></el-icon> 导出 Excel
        </el-button>
        <!-- 导出改成作业后请求会立刻返回，进度条是用户唯一的「它还在跑」凭据 -->
        <JobProgressChip :percent="excelProgress" :active="exportingExcel" />
        <el-button :loading="exportingCsv" :disabled="!props.fileId" @click="exportCsv">
          <el-icon><Document /></el-icon> 导出 CSV
        </el-button>
      </template>
    </ActiveFileBanner>

    <!-- 控制栏（DataBrowserToolbar：筛选控件） -->
    <DataBrowserToolbar
      :test-cols="testCols"
      :selected-test-cols="selectedTestCols"
      :passfail="passfail"
      :site-filter="siteFilter"
      :site-options="siteOptions"
      :site-col-disabled="siteColDisabled"
      :autosize-mode="autosizeMode"
      :pinned-cols="pinnedCols"
      :all-cols="allCols"
      @update:selected-test-cols="selectedTestCols = $event"
      @update:passfail="passfail = $event"
      @update:site-filter="siteFilter = $event"
      @update:autosize-mode="autosizeMode = $event"
      @update:pinned-cols="pinnedCols = $event"
    />

    <!-- 质量概览条（复用 /summary/ 接口，失败静默隐藏） -->
    <DataQualityBar :file-id="fileId" />

    <!-- 数据表格 -->
    <div v-loading="loading">
      <p v-if="dataLoaded || (colCount && blockSize !== settingsPageSize)" style="margin-bottom: 8px; font-size: var(--p-fs-base)">
        <template v-if="dataLoaded">共 <b>{{ rowCount }}</b> 条数据
        <span v-if="failRowCount > 0" style="color: var(--error); margin-left: 12px; font-weight: bold">
          （Fail: {{ failRowCount }} 行<template v-if="siteFilter">，Site {{ siteFilter }} 过滤后</template>）
        </span></template>
        <!-- D3 口径变更必须可见；刻意不嵌进 v-if="dataLoaded"：首块失败/为空时 dataLoaded 为假，而那一刻最需要这句「每页怎么只有这么多行」的解释（class 用双主题各带取值的 .text-secondary，不新增 CSS） -->
        <span
          v-if="colCount && blockSize !== settingsPageSize" class="text-secondary"
          :title="`该文件 ${colCount} 列：每页行数已从 ${settingsPageSize} 降为 ${blockSize} 以控制内存`"
          style="margin-left: 12px; cursor: help"
        >每页 {{ blockSize }} 行</span>
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
          :infiniteInitialRowCount="blockSize"
          :cacheBlockSize="blockSize"
          :maxBlocksInCache="maxBlocks"
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
          @grid-ready="handleGridReady"
          @sort-changed="clearRowHighlights"
          @filter-changed="clearRowHighlights"
        />
      </div>
    </div>

    <!-- 列直方图对话框（表头右键菜单 → 展示分布图，复用分析页 HistogramChart + StatsSummary） -->
    <HistogramColumnDialog
      :visible="histDialogVisible"
      :file-id="props.fileId"
      :param="analyzeParam"
      :unit="colMeta[analyzeParam]?.unit ?? ''"
      @close="histDialogVisible = false"
    />

    <!-- 表头右键菜单：复制测试项名字 / 展示分布图 -->
    <HeaderContextMenu
      :visible="headerMenuVisible"
      :x="headerMenuX"
      :y="headerMenuY"
      :col-name="headerMenuCol"
      :is-system="headerMenuIsSystem"
      :is-numeric="headerMenuIsNumeric"
      @close="closeHeaderMenu"
      @copy="onHeaderMenuCopy"
      @show-histogram="onHeaderMenuShowHistogram"
    />

    <!-- 固定 Bin 列 fail 单元格右键菜单（定位到该行第一个异常单元格） -->
    <BinCellContextMenu
      :visible="binMenuVisible"
      :x="binMenuX"
      :y="binMenuY"
      :row-index="binMenuRowIndex"
      :bin-value="binMenuBinValue"
      :fail-cols="binMenuFailCols"
      :borderline-cols="binMenuBorderlineCols"
      @close="closeBinMenu"
      @goto-fail="goToFailCell"
    />

    <!-- 行高亮右键菜单（右键序列号单元格打开） -->
    <RowHighlightMenu
      :visible="rowHighlightMenuVisible"
      :x="rowHighlightMenuX"
      :y="rowHighlightMenuY"
      :row-index="rowHighlightMenuRowIndex"
      :serial-value="rowHighlightMenuSerialValue"
      :highlighted="isHighlighted(rowHighlightMenuRowIndex)"
      @close="closeRowHighlightMenu"
      @toggle="onRowHighlightToggle"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, onDeactivated } from 'vue'
import { AgGridVue } from 'ag-grid-vue3'
import { Refresh, Download, Document } from '@element-plus/icons-vue'
import { datafilesApi } from '../../api/datafiles'
import { useUserSettingsStore } from '../../stores/userSettings'
import { useThemeStore } from '../../stores/theme'
import { useFilesStore } from '../../stores/files'
import type { DataFile } from '../../types'
import ActiveFileBanner from './components/browser/ActiveFileBanner.vue'
import DataBrowserToolbar from './components/browser/DataBrowserToolbar.vue'
import HistogramColumnDialog from './components/browser/HistogramColumnDialog.vue'
import DataQualityBar from './components/browser/DataQualityBar.vue'
import BinCellContextMenu from './components/browser/BinCellContextMenu.vue'
import HeaderContextMenu from './components/browser/HeaderContextMenu.vue'
import RowHighlightMenu from './components/browser/RowHighlightMenu.vue'
import JobProgressChip from '../../components/common/JobProgressChip.vue'
import { useBinCellMenu } from './composables/useBinCellMenu'
import { useBrowserExport } from './composables/useBrowserExport'
import { useGridContextMenus } from './composables/useGridContextMenus'
import { useGridHeight } from './composables/useGridHeight'
import { useHeaderMenu } from './composables/useHeaderMenu'
import { useIrmSizing } from './composables/useIrmSizing'
import { useRowHighlight } from './composables/useRowHighlight'
import { browserCellStyle, buildBrowserColumnDefs, resolveDisplayCols } from './components/browser/browserColumns'
import { zipBrowserRows } from './components/browser/browserRows'

// Register ag-grid modules (required since v33+)
import { ModuleRegistry, AllCommunityModule, type IDatasource, type GridReadyEvent } from 'ag-grid-community'
ModuleRegistry.registerModules([AllCommunityModule])

const props = defineProps<{
  fileId: number | null
  /** 全量文件列表：横幅的文件下拉要用，导出文件名也从这里按 id 反查 */
  files: DataFile[]
  active?: boolean // v-show 下隐藏实例仍挂载 ⇒ 靠它决定要不要清块缓存（非激活标签释放）
}>()
const emit = defineEmits<{
  'update:fileId': [number | null]
  'file-missing': []
  'goto-files': []
}>()
const themeStore = useThemeStore()
const filesStore = useFilesStore()
const isDark = computed(() => themeStore.currentTheme === 'night')

const passfail = ref('')
const siteFilter = ref('')
const autosizeMode = ref('none')
// 固定列可多选（ag-grid 社区版原生支持多列 pinned:'left'）；顺序由 displayCols
// 的列序决定，系统列本就前置，所以 Bin 与序列列天然挨在一起。
const pinnedCols = ref<string[]>([])
// 用户是否已经「表过态」：没表过态时由 applyMeta 灌默认值（Bin + 序列列），
// 表过态（含主动清空）之后只按列是否还存在做裁剪，不回灌。
const pinsReady = ref(false)
// 显示测试列：选中集非空 = 表格仅显示这些测试列（系统列恒显）；空集 = 显示全部
const selectedTestCols = ref<string[]>([])
const loading = ref(false)
// 导出的两个状态住在 useBrowserExport 里（Excel=作业、CSV=同步），这里不再各挂一个 ref
const dataLoaded = ref(false)

// 表格高度随视口自适应；顶部带常量历次实测为 320/254/290。
// 口径是「表格下缘恒为 1023px」：顶部带增减一律由表格吸收，页面总高不变 ——
// 常量不动的话，加一行 chrome 就等于把整页推高 36px。
const { tableHeight, gridWrapperStyle } = useGridHeight(290)

onUnmounted(() => {
  if (passfailTimer) clearTimeout(passfailTimer)
  // siteFilterTimer 也必须清：watcher 随组件作用域自动停止，但已排期的
  // setTimeout 仍会在卸载后触发 reload() → 对已销毁的 grid 发幽灵请求。
  if (siteFilterTimer) clearTimeout(siteFilterTimer)
  markGridDead() // grid 随组件一起销毁：此后任何 purge/滚动都不许再打到它（AG Grid #26）
})

// 非激活就交出块缓存：v-show 的隐藏标签/隐藏 section 仍保持挂载（DataManagement.vue:43,57），千列文件的整叠驻留块常驻就是生产那次 oom 的体积
onDeactivated(() => purgeCacheIfAlive()) // 整页离开走这条（MainLayout.vue:12 keep-alive）
watch(() => props.active, (v) => { if (v === false) purgeCacheIfAlive() }) // 标签间切换走这条

const allCols = ref<string[]>([])
const colMeta = ref<Record<string, { unit: string; min: string; max: string }>>({})
const numericColumns = ref<string[]>([])
const siteOptions = ref<string[]>([])
// Bin 列与序列列由后端 page==1 权威下发（bin_column / serial_column）。
// binCol 必须单独存：右键菜单只对 Bin 列的 fail 单元格生效，不能再拿
// 「谁是固定列」去反推它是 Bin 列 —— 固定列现在是多个了。
const binCol = ref('')
const serialCol = ref('')
const rowCount = ref(0)
const failRowCount = ref(0)

// 请求竞态防护：快速切换筛选时丢弃过期响应（只丢弃 refs 更新，grid 本身有块版本号守卫）
let loadSeq = 0

// ── 列直方图 + 表头右键菜单（状态与复制/打开逻辑见 composable） ──
const {
  visible: headerMenuVisible,
  x: headerMenuX,
  y: headerMenuY,
  col: headerMenuCol,
  isSystem: headerMenuIsSystem,
  isNumeric: headerMenuIsNumeric,
  histDialogVisible,
  analyzeParam,
  open: openHeaderMenu,
  close: closeHeaderMenu,
  copyName: onHeaderMenuCopy,
  showHistogram: onHeaderMenuShowHistogram,
} = useHeaderMenu({
  numericColumns,
  isSystemCol: (c) => systemCols.value.includes(c),
  closeOtherMenu: () => closeBinMenu(),
})

// 统一右键路由（表头 / 序列号行菜单 / Bin fail 菜单 / 浏览器原生）

// 系统列（记录级列）：恒显示且排在测试列之前，由后端按文件格式权威下发
// （/browse/ page==1 的 system_columns，来源 apps.datafiles.parsers.SYSTEM_COLUMNS）。
// 不用列名前缀启发式：测试项名可能与记录列同名前缀（Device_Fused_Flag1/2、
// SITE_CHECK 是测试项，却以 device_/site_ 开头，2026-08-25 曾被误判前置）。
const systemCols = ref<string[]>([])

// 默认隐藏列（系统设置 → 表格设置）：命中列 hide=true，列仍存在，用户可通过
// ag-grid 表头列菜单重新显示；与导出 Excel 的隐藏列共用同一份设置。
// 每页行数顺带套进 IRM 块大小（见 applyBlockSize）。Task 6b：这两个值读 stores/userSettings
// 的缓存，那次 GET 由路由守卫的 ensureChartRenderer() 单飞 ⇒ 本页不再自己发请求。
const defaultHiddenCols = ref<string[]>([])
onMounted(async () => {
  const s = useUserSettingsStore()
  await s.ensure()
  // ensure() 自己吞掉失败并记为已取过（防请求风暴），raw=null 即本处要的静默降级：
  // 隐藏列全部可见、块大小用默认 100。不套 gridAlive/withLiveGrid —— 这段只写组件
  // 自己的 ref，从不碰 grid api（那两个守卫是给 purge/滚动用的，见 useIrmSizing）。
  const hidden = s.raw?.default_hidden_columns
  defaultHiddenCols.value = Array.isArray(hidden) ? hidden : []
  applyBlockSize(s.raw?.page_size)
})

function isSystemCol(name: string): boolean {
  return systemCols.value.includes(name)
}

// 显示列：系统列恒显示且前置；选中测试列非空时仅显示选中测试列（空集 = 全部）
const colSelection = computed(() =>
  resolveDisplayCols(allCols.value, systemCols.value, selectedTestCols.value),
)
const testCols = computed(() => colSelection.value.testCols)
const displayCols = computed(() => colSelection.value.displayCols)

// ── 固定 Bin 列 fail 单元格右键菜单（判定链 + 定位逻辑见 composable） ──
const {
  gridApi,
  visible: binMenuVisible,
  x: binMenuX,
  y: binMenuY,
  rowIndex: binMenuRowIndex,
  binValue: binMenuBinValue,
  failCols: binMenuFailCols,
  borderlineCols: binMenuBorderlineCols,
  onGridReady,
  close: closeBinMenu,
  handleBodyContextMenu,
  goToFailCell,
} = useBinCellMenu({ binCol, displayCols })

const {
  blockSize, settingsPageSize, colCount, maxBlocks, withLiveGrid,
  applyBlockSize, purgeCacheIfAlive, keyedDatasource, markGridAlive, markGridDead,
} = useIrmSizing({ props, gridApi })

function handleGridReady(e: GridReadyEvent) {
  onGridReady(e)
  markGridAlive() // #26 守卫的置位点：只有从这里之后 purge/滚动才允许打这个 api
}

// ── 行高亮：右键序列号单元格 → 菜单 → 高亮/取消 ──
const {
  isHighlighted,
  clear: clearRowHighlights,
  menuVisible: rowHighlightMenuVisible,
  menuX: rowHighlightMenuX,
  menuY: rowHighlightMenuY,
  menuRowIndex: rowHighlightMenuRowIndex,
  menuSerialValue: rowHighlightMenuSerialValue,
  openMenu: openRowHighlightMenu,
  closeMenu: closeRowHighlightMenu,
  toggleMenuRow: toggleRowHighlightMenu,
} = useRowHighlight()

/** 高亮触发列：序列列（可见时）；无序列列/被默认隐藏时没有触发点 */
const highlightTriggerCol = computed(() => {
  const serial = serialCol.value
  if (serial && allCols.value.includes(serial) && !defaultHiddenCols.value.includes(serial)) {
    return serial
  }
  return ''
})

function onRowHighlightToggle() {
  const idx = rowHighlightMenuRowIndex.value
  toggleRowHighlightMenu()
  // rowClassRules 的闭包读 highlightedRows ref；改完必须重绘该行才会重新求值
  const node = gridApi.value?.getDisplayedRowAtIndex(idx)
  if (node) gridApi.value?.redrawRows({ rowNodes: [node] })
}

const { onGridContextMenu } = useGridContextMenus({
  allCols,
  highlightTriggerCol,
  gridApi,
  closeBinMenu,
  closeHeaderMenu,
  closeRowHighlightMenu,
  openHeaderMenu,
  openRowHighlightMenu,
  handleBodyContextMenu,
})

// ── Site 筛选（服务端）：选项来自 page==1 响应的 site_options，过滤走 reload ──
const siteColDisabled = computed(() => {
  if (!allCols.value.length) return true
  return !allCols.value.some((c) => /site/i.test(c) && isSystemCol(c))
})

const columnDefs = computed<any[]>(() =>
  buildBrowserColumnDefs({
    displayCols: displayCols.value,
    colMeta: colMeta.value,
    numericColumns: numericColumns.value,
    defaultHiddenCols: defaultHiddenCols.value,
    pinnedCols: pinnedCols.value,
    highlightTriggerCol: highlightTriggerCol.value,
  }),
)

const defaultColDef = {
  editable: false,
  sortable: true,
  resizable: true,
  // 服务端列过滤（方案 A）：apply/reset 按钮——避免每敲一键就触发整页重载（官方推荐服务端场景）
  filterParams: { buttons: ['apply', 'reset'] },
  wrapHeaderText: true,
  autoHeaderHeight: true,
  // 红/橙规则住在 browserColumns.ts（T2 纯函数）；此处只注入主题
  cellStyle: (params: any) => browserCellStyle(params, isDark.value),
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
  'row-highlight': (params: any) => isHighlighted(params.node.rowIndex),
}

watch(
  () => props.fileId,
  () => {
    // 切换文件后 Site/PassFail/显示测试列/元信息属于旧文件，重置避免误导
    passfail.value = ''
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
      reload(false) // 换文件不 purge：上面那条 datasource 换身份已经把块和快照一起换掉了
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
watch([rowCount, siteFilter], () => {
  closeBinMenu()
  closeHeaderMenu()
  closeRowHighlightMenu()
})

function clearGrid() {
  closeBinMenu()
  closeHeaderMenu()
  clearRowHighlights()
  allCols.value = []
  colMeta.value = {}
  numericColumns.value = []
  siteOptions.value = []
  systemCols.value = []
  binCol.value = ''
  serialCol.value = ''
  pinnedCols.value = []
  // 文件没了（被删）→ 下次拿到元信息要重新灌默认固定列
  pinsReady.value = false
  rowCount.value = 0
  failRowCount.value = 0
  dataLoaded.value = false
}

/** IRM 取数闭包：getRows 读当前 ref 值（不快照）⇒ pass_filter / site_filter / sort 一律取最新值；
 *  交给网格的不是这个内容恒定的对象，而是下面那层按预算换身份的 computed。 */
const browseSource: IDatasource = {
  getRows: async (params) => {
    if (!props.fileId) {
      params.failCallback()
      return
    }
    const seq = ++loadSeq
    try {
      const resp = await datafilesApi.browse({
        datafile_id: props.fileId,
        page: Math.floor(params.startRow / blockSize.value) + 1,
        page_size: blockSize.value,
        pass_filter: passfail.value,
        site_filter: siteFilter.value,
        sort_model: JSON.stringify(params.sortModel),
        filter_model: JSON.stringify(params.filterModel),
      })
      const d = resp.data
      // 新旧响应都喂 grid（IRM 有块版本号守卫丢弃过期块数据）；块数据 zip 成行对象
      params.successCallback(zipBrowserRows(d), d.total)
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

/** 身份随 (fileId, blockSize, maxBlocks) 更换 ⇒ 逼 ag-grid `setDatasource → resetCache` 重取 cacheParams 快照（为什么必须换身份：useIrmSizing.keyedDatasource） */
const datasource = computed(() => keyedDatasource(browseSource))

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

  const binColName = d.bin_column as string
  binCol.value = typeof binColName === 'string' ? binColName : ''
  const serial = d.serial_column as string | null
  serialCol.value = typeof serial === 'string' ? serial : ''

  const defaultPins = () => [binCol.value, serialCol.value].filter((c) => c && allCols.value.includes(c))
  if (!pinsReady.value) {
    // 首次拿到列元信息：默认钉住 Bin + 序列列（每种格式的序列列名不同，
    // Serial_No / Serial # / PART_ID，由后端解析，前端不猜）
    pinnedCols.value = defaultPins()
    pinsReady.value = true
  } else {
    const kept = pinnedCols.value.filter((c) => allCols.value.includes(c))
    // 只有「列真的从数据里消失了」（换文件）才回落到默认。用户主动清空过
    // （kept 为空但没发生消失）不回灌，否则下一次换筛选就把他的清空撤销了。
    if (kept.length !== pinnedCols.value.length) {
      pinnedCols.value = kept.length ? kept : defaultPins()
    }
  }
}

/** 重新加载：回顶部 +（除换文件外）清 IRM 全部块（purge 本身不重置滚动位置）。
 *  换文件走 `reload(false)`：datasource 换身份已经把块和 `cacheParams` 一起重建了，
 *  再 purge 就是对首块多打一次 `/browse/`（那条重复的 page=1 就是这么来的）。 */
function reload(purgeBlocks = true) {
  if (!props.fileId) return
  closeBinMenu()
  closeHeaderMenu()
  clearRowHighlights() // 行序/筛选已变，旧的显示行索引不再指向原行
  loading.value = true
  loadSeq++ // 新代次：旧在途响应不再更新 refs
  if (purgeBlocks) purgeCacheIfAlive()
  withLiveGrid((api) => api.ensureIndexVisible(0))
}

/**
 * 当前表格的排序/列过滤模型（与 IRM getRows 同语义），供导出透传后端：
 * 看到的行 == 导出的行。grid 未就绪时返回空模型（= 不筛选不排序）。
 */
function currentGridModels(): { sort_model: string; filter_model: string } {
  const api = gridApi.value
  if (!api) return { sort_model: '[]', filter_model: '{}' }
  // IRM sortModel 形状 [{colId, sort}]：从列状态按 sortIndex 还原
  const cols = api.getColumnState().filter((c) => c.sort).sort(
    (a, b) => (a.sortIndex ?? 0) - (b.sortIndex ?? 0),
  )
  return {
    sort_model: JSON.stringify(cols.map((c) => ({ colId: c.colId, sort: c.sort }))),
    filter_model: JSON.stringify(api.getFilterModel() ?? {}),
  }
}

const {
  exportingExcel, exportingCsv, excelProgress, exportExcel, exportCsv,
} = useBrowserExport({
  fileId: () => props.fileId,
  passfail: () => passfail.value,
  siteFilter: () => siteFilter.value,
  gridModels: currentGridModels,
  filenameOf: (id) => props.files.find((f) => f.id === id)?.filename,
})
</script>

<style scoped src="./components/browser/data-browser-grid.css"></style>
