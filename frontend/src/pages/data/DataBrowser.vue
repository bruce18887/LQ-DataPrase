<template>
  <div class="data-browser">
    <el-row :gutter="16" class="filter-row">
      <el-col :span="6">
        <el-input v-model="searchCol" placeholder="搜索列名…" clearable aria-label="搜索" />
      </el-col>
      <el-col :span="4">
        <el-select v-model="passfail" placeholder="Pass/Fail" clearable aria-label="搜索列">
          <el-option label="全部" value="" />
          <el-option label="Pass" value="Pass" />
          <el-option label="Fail" value="Fail" />
        </el-select>
      </el-col>
      <el-col :span="6">
        <el-select v-model="siteFilter" placeholder="Site 筛选" clearable aria-label="站点筛选">
          <el-option label="全部 Site" value="" />
          <el-option v-for="s in 8" :key="s" :label="'Site ' + s" :value="String(s)" />
        </el-select>
      </el-col>
      <el-col :span="8">
        <el-button @click="loadData" type="primary">加载数据</el-button>
        <el-button @click="exportExcel" :loading="exporting">导出 Excel</el-button>
        <el-button @click="exportCsv" :loading="exporting">导出 CSV</el-button>
      </el-col>
    </el-row>

    <div v-loading="loading" class="data-content">
      <p v-if="dataLoaded" class="data-summary">
        共 <b>{{ filteredRows.length }}</b> 条数据
        <span v-if="failRowCount > 0" class="fail-count">
          （Fail: {{ failRowCount }} 行）
        </span>
      </p>
      <el-table
        :data="pagedRows"
        stripe
        border
        size="small"
        max-height="500"
        class="data-table"
      >
        <el-table-column
          v-for="col in displayCols"
          :key="col"
          :prop="col"
          :label="getColLabel(col)"
          min-width="120"
          show-overflow-tooltip
        >
          <template #default="{ row }">
            <span
              :class="{ 'fail-cell': isFailCell(row, col) }"
            >
              {{ row[col] }}
            </span>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-if="dataLoaded"
        v-model:current-page="page"
        :page-size="pageSize"
        :total="filteredRows.length"
        layout="prev, pager, next, total"
        class="pagination"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'

const props = defineProps<{ fileId: number }>()

const searchCol = ref('')
const passfail = ref('')
const siteFilter = ref('')
const loading = ref(false)
const exporting = ref(false)
const dataLoaded = ref(false)
const allCols = ref<string[]>([])
const allRows = ref<Record<string, unknown>[]>([])
const failCells = ref<Record<number, string[]>>({})
const failRowCount = ref(0)
const colMeta = ref<Record<string, { unit: string; min: string; max: string }>>({})
const page = ref(1)
const pageSize = 50

const displayCols = computed(() => {
  if (!searchCol.value) return allCols.value
  return allCols.value.filter((c) =>
    c.toLowerCase().includes(searchCol.value.toLowerCase())
  )
})

const filteredRows = computed(() => {
  let rows = allRows.value
  if (passfail.value === 'Pass') {
    rows = rows.filter((_, idx) => !failCells.value[idx])
  } else if (passfail.value === 'Fail') {
    rows = rows.filter((_, idx) => failCells.value[idx])
  }
  return rows
})

const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize
  return filteredRows.value.slice(start, start + pageSize)
})

function getColLabel(col: string): string {
  const meta = colMeta.value[col]
  if (!meta) return col
  const parts = [col]
  if (meta.unit && meta.unit !== '-' && meta.unit !== 'None') {
    parts.push(` (${meta.unit})`)
  }
  if (meta.min !== '' || meta.max !== '') {
    parts.push(` [${meta.min || '-'}, ${meta.max || '-'}]`)
  }
  return parts.join('')
}

function getRowIndex(row: Record<string, unknown>): number {
  return allRows.value.indexOf(row)
}

function isFailCell(row: Record<string, unknown>, col: string): boolean {
  const idx = getRowIndex(row)
  return failCells.value[idx]?.includes(col) ?? false
}

watch(
  () => props.fileId,
  () => {
    if (props.fileId) loadData()
  }
)

async function loadData() {
  loading.value = true
  try {
    const resp = await api.get('/browse/', {
      params: { datafile_id: props.fileId, page_size: 99999 },
    })
    allCols.value = (resp.data.headers as string[]) ?? []
    allRows.value = (resp.data.rows as Record<string, unknown>[]) ?? []
    colMeta.value = (resp.data.col_meta as Record<string, { unit: string; min: string; max: string }>) ?? {}
    failCells.value = {}
    failRowCount.value = resp.data.fail_row_count ?? 0

    const failMask = resp.data.fail_mask as Record<string, string[]> | undefined
    if (failMask) {
      for (const [rowIdxStr, cols] of Object.entries(failMask)) {
        const rowIdx = Number(rowIdxStr)
        failCells.value[rowIdx] = cols
      }
    }

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
      {
        file_id: props.fileId,
        passfail: passfail.value,
        site_filter: siteFilter.value,
      },
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
      {
        file_id: props.fileId,
        passfail: passfail.value,
      },
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
.data-browser {
  padding: 16px;
  background: var(--bg-primary);
  border-radius: 8px;
}

.filter-row {
  margin-bottom: 16px;
}

.data-content {
  background: var(--bg-secondary);
  padding: 16px;
  border-radius: 8px;
  border: 1px solid var(--border-default);
}

.data-summary {
  margin-bottom: 16px;
  color: var(--text-primary);
  font-size: 14px;
}

.data-summary b {
  color: var(--brand-primary);
  font-weight: 600;
}

.fail-count {
  color: var(--color-error);
  margin-left: 12px;
  font-weight: 500;
}

.fail-cell {
  color: var(--color-error);
  font-weight: bold;
}

.data-table {
  width: 100%;
}

.pagination {
  margin-top: 16px;
  display: flex;
  justify-content: center;
}

/* Element Plus 组件覆盖 */
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
  box-shadow: 0 0 0 1px var(--border-default) inset;
  transition: box-shadow 0.2s;
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--brand-primary) inset;
}

:deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--brand-primary) inset;
}

:deep(.el-select) {
  --el-select-input-focus-border-color: var(--brand-primary);
}

:deep(.el-button) {
  border-radius: 8px;
}

:deep(.el-button--primary) {
  --el-button-bg-color: var(--brand-primary);
  --el-button-border-color: var(--brand-primary);
  --el-button-hover-bg-color: var(--brand-primary-hover);
  --el-button-hover-border-color: var(--brand-primary-hover);
}

:deep(.el-table) {
  --el-table-bg-color: var(--bg-primary);
  --el-table-tr-bg-color: var(--bg-primary);
  --el-table-header-bg-color: var(--bg-tertiary);
  --el-table-border-color: var(--border-default);
  --el-table-text-color: var(--text-primary);
  --el-table-header-text-color: var(--text-primary);
  border-radius: 8px;
  overflow: hidden;
}

:deep(.el-table__body tr:hover > td) {
  background-color: var(--bg-tertiary) !important;
}

:deep(.el-table--striped .el-table__body tr.el-table__row--striped td) {
  background-color: var(--bg-secondary);
}

:deep(.el-pagination) {
  --el-pagination-button-color: var(--text-primary);
  --el-pagination-hover-color: var(--brand-primary);
  --el-pagination-bg-color: var(--bg-primary);
  --el-pagination-button-bg-color: var(--bg-primary);
}

:deep(.el-pagination button) {
  background-color: var(--bg-primary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
}

:deep(.el-pagination button:hover) {
  color: var(--brand-primary);
  border-color: var(--brand-primary);
}

:deep(.el-pager li) {
  background-color: var(--bg-primary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  margin: 0 4px;
  color: var(--text-primary);
}

:deep(.el-pager li:hover) {
  color: var(--brand-primary);
  border-color: var(--brand-primary);
}

:deep(.el-pager li.is-active) {
  background-color: var(--brand-primary);
  border-color: var(--brand-primary);
  color: var(--text-inverse);
}
</style>
