<template>
  <div>
    <!-- 控制栏 -->
    <el-row :gutter="12" style="margin-bottom: 12px">
      <el-col :span="6">
        <el-input v-model="searchCol" placeholder="搜索列名…" clearable aria-label="搜索" />
      </el-col>
      <el-col :span="4">
        <el-select v-model="searchTestCol" placeholder="搜索测试项" clearable aria-label="搜索列">
          <el-option label="全部显示" value="" />
          <el-option v-for="c in allCols" :key="c" :label="c" :value="c" />
        </el-select>
      </el-col>
      <el-col :span="3">
        <el-select v-model="passfail" placeholder="Pass/Fail筛选" aria-label="Pass/Fail筛选">
          <el-option label="全部" value="" />
          <el-option label="Pass" value="Pass" />
          <el-option label="Fail" value="Fail" />
        </el-select>
      </el-col>
      <el-col :span="3">
        <el-select v-model="siteFilter" placeholder="Site筛选" aria-label="站点筛选">
          <el-option label="全部 Site" value="" />
          <el-option v-for="s in 8" :key="s" :label="'Site ' + s" :value="String(s)" />
        </el-select>
      </el-col>
      <el-col :span="4">
        <el-select v-model="autosizeMode" placeholder="列宽自适应" aria-label="列宽模式">
          <el-option label="适应内容宽度" value="fitCellContents" />
          <el-option label="适应网格宽度" value="fitGridWidth" />
          <el-option label="手动调整" value="none" />
        </el-select>
      </el-col>
      <el-col :span="6">
        <el-input v-model="pinnedCol" placeholder="固定列（留空则不固定）" clearable aria-label="固定列数" />
      </el-col>
    </el-row>

    <!-- 操作按钮 -->
    <el-row style="margin-bottom: 12px">
      <el-col>
        <el-button @click="loadData" type="primary" :loading="loading">
          <el-icon><Refresh /></el-icon> 加载数据
        </el-button>
        <el-button @click="exportExcel" :loading="exporting">
          <el-icon><Download /></el-icon> 导出 Excel
        </el-button>
        <el-button @click="exportCsv" :loading="exporting">
          <el-icon><Document /></el-icon> 导出 CSV
        </el-button>
      </el-col>
    </el-row>

    <!-- 数据表格 -->
    <div v-loading="loading">
      <p v-if="dataLoaded" style="margin-bottom: 8px; font-size: 14px">
        共 <b>{{ rowCount }}</b> 条数据
        <span v-if="failRowCount > 0" style="color: var(--color-error); margin-left: 12px; font-weight: bold">
          （Fail: {{ failRowCount }} 行）
        </span>
      </p>
      <div class="ag-grid-wrapper">
        <ag-grid-vue
        v-if="dataLoaded && rowCount > 0"
        :class="['ag-theme-quartz', isDark ? 'ag-theme-quartz-dark' : '', 'ag-custom-theme']"
        :style="{ height: `${tableHeight}px`, width: '100%', contain: 'layout style' }"
        :columnDefs="columnDefs"
        :rowData="rowData"
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
      />
      <el-empty v-else-if="dataLoaded" description="没有匹配的数据" :image-size="80" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { AgGridVue } from 'ag-grid-vue3'
import { ElMessage } from 'element-plus'
import { Refresh, Download, Document } from '@element-plus/icons-vue'
import api from '../../api'
import { useThemeStore } from '../../stores/theme'

// Register ag-grid modules (required since v33+)
import { ModuleRegistry, AllCommunityModule } from 'ag-grid-community'
ModuleRegistry.registerModules([AllCommunityModule])

const props = defineProps<{ fileId: number | null }>()
const themeStore = useThemeStore()
const isDark = computed(() => themeStore.currentTheme === 'night')

const searchCol = ref('')
const searchTestCol = ref('')
const passfail = ref('')
const siteFilter = ref('')
const autosizeMode = ref('none')
const pinnedCol = ref('')
const loading = ref(false)
const exporting = ref(false)
const dataLoaded = ref(false)
const tableHeight = ref(700)

const allCols = ref<string[]>([])
const rowData = ref<Record<string, any>[]>([])
const colMeta = ref<Record<string, { unit: string; min: string; max: string }>>({})
const failRowCount = ref(0)

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

const rowCount = computed(() => rowData.value.length)

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
    if (props.fileId) loadData()
  }
)

watch([passfail], () => {
  if (dataLoaded.value) {
    loadData()
  }
})

async function loadData() {
  loading.value = true
  try {
    const resp = await api.get('/browse/', {
      params: {
        datafile_id: props.fileId,
        page_size: 99999,
        pass_filter: passfail.value,
      },
    })

    allCols.value = (resp.data.headers as string[]) ?? []
    failRowCount.value = resp.data.fail_row_count ?? 0

    const rawColMeta = (resp.data.col_meta ?? {}) as Record<string, { unit: string; min: string; max: string }>
    colMeta.value = rawColMeta

    if (!pinnedCol.value) {
      const binCol = resp.data.bin_column as string
      if (binCol && allCols.value.includes(binCol)) {
        pinnedCol.value = binCol
      }
    }

    rowData.value = (resp.data.rows as Record<string, any>[]) ?? []

    dataLoaded.value = true
  } catch {
    ElMessage.error('加载失败')
  } finally {
    loading.value = false
  }
}

async function exportExcel() {
  exporting.value = true
  try {
    const resp = await api.post(
      '/export/to_excel/',
      { file_id: props.fileId, passfail: passfail.value, site_filter: siteFilter.value },
      { responseType: 'blob' }
    )
    downloadBlob(resp.data as Blob, 'export.xlsx')
  } catch {
    ElMessage.error('导出失败')
  } finally {
    exporting.value = false
  }
}

async function exportCsv() {
  exporting.value = true
  try {
    const resp = await api.post(
      '/export/to_csv/',
      { file_id: props.fileId, passfail: passfail.value, site_filter: siteFilter.value },
      { responseType: 'blob' }
    )
    downloadBlob(resp.data as Blob, 'export.csv')
  } catch {
    ElMessage.error('导出失败')
  } finally {
    exporting.value = false
  }
}

function downloadBlob(data: Blob, filename: string) {
  const url = URL.createObjectURL(data)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('下载完成')
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

:deep(.el-input) {
  --el-input-bg-color: var(--bg-primary);
  --el-input-border-color: var(--border-default);
  --el-input-hover-border-color: var(--brand-primary);
  --el-input-focus-border-color: var(--brand-primary);
  --el-input-text-color: var(--text-primary);
  --el-input-placeholder-color: var(--text-secondary);
}

:deep(.el-input__wrapper) {
  background-color: var(--bg-primary);
  border-radius: 8px;
}

:deep(.el-select) {
  --el-select-input-focus-border-color: var(--brand-primary);
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
</style>
