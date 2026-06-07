<template>
  <div>
    <el-row :gutter="16" style="margin-bottom: 16px">
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
      <el-col :span="8">
        <el-button @click="loadData" type="primary">加载数据</el-button>
        <el-button @click="exportExcel" :loading="exporting">导出 Excel</el-button>
        <el-button @click="exportCsv" :loading="exporting">导出 CSV</el-button>
      </el-col>
    </el-row>

    <div v-loading="loading">
      <p v-if="dataLoaded">
        共 <b>{{ filteredRows.length }}</b> 条数据
        <span v-if="failRowCount > 0" style="color: var(--color-error); margin-left: 12px">
          （Fail: {{ failRowCount }} 行）
        </span>
      </p>
      <el-table
        :data="pagedRows"
        stripe
        border
        size="small"
        max-height="500"
        style="width: 100%"
        :cell-class-name="cellClassName"
      >
        <el-table-column
          v-for="col in displayCols"
          :key="col"
          :prop="col"
          :label="getColLabel(col)"
          min-width="140"
          show-overflow-tooltip
        />
      </el-table>
      <el-pagination
        v-if="dataLoaded"
        v-model:current-page="page"
        :page-size="pageSize"
        :total="filteredRows.length"
        layout="prev, pager, next, total"
        style="margin-top: 16px; justify-content: center"
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
const loading = ref(false)
const exporting = ref(false)
const dataLoaded = ref(false)
const allCols = ref<string[]>([])
const allRows = ref<Record<string, unknown>[]>([])
const failCellMap = ref<Record<number, string[]>>({})
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
    rows = rows.filter((_, idx) => !failCellMap.value[idx])
  } else if (passfail.value === 'Fail') {
    rows = rows.filter((_, idx) => failCellMap.value[idx])
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

function cellClassName({ row, column }: { row: Record<string, unknown>; column: { property: string } }): string {
  const rowIdx = allRows.value.indexOf(row)
  if (rowIdx >= 0 && failCellMap.value[rowIdx]?.includes(column.property)) {
    return 'fail-cell'
  }
  return ''
}

watch(
  () => props.fileId,
  () => {
    if (props.fileId) loadData()
  },
  { immediate: true }
)

async function loadData() {
  loading.value = true
  dataLoaded.value = false
  try {
    const resp = await api.get('/browse/', {
      params: { datafile_id: props.fileId, page_size: 99999 },
    })
    allCols.value = (resp.data.headers as string[]) ?? []
    allRows.value = (resp.data.rows as Record<string, unknown>[]) ?? []
    failCellMap.value = {}
    failRowCount.value = resp.data.fail_row_count ?? 0
    colMeta.value = (resp.data.col_meta as Record<string, { unit: string; min: string; max: string }>) ?? {}
    page.value = 1

    const failMask = resp.data.fail_mask as Record<string, string[]> | undefined
    if (failMask) {
      for (const [rowIdxStr, cols] of Object.entries(failMask)) {
        const rowIdx = Number(rowIdxStr)
        failCellMap.value[rowIdx] = cols
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
:deep(.fail-cell) {
  background-color: var(--color-error) !important;
  color: var(--text-inverse) !important;
  font-weight: bold;
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

:deep(.el-table) {
  --el-table-bg-color: var(--bg-secondary);
  --el-table-tr-bg-color: var(--bg-secondary);
  --el-table-header-bg-color: var(--bg-tertiary);
  --el-table-border-color: var(--border-default);
  --el-table-text-color: var(--text-primary);
}

:deep(.el-pagination) {
  --el-pagination-button-color: var(--text-primary);
  --el-pagination-hover-color: var(--brand-primary);
}
</style>
