<template>
  <div class="file-list-tab">
    <!-- Toolbar -->
    <div class="list-toolbar">
      <div class="toolbar-left">
        <span class="section-title">📋 文件列表</span>
        <span class="section-count">{{ total }} 个文件</span>
      </div>
      <div class="toolbar-right">
        <el-input
          v-model="searchText"
          placeholder="按文件名搜索"
          clearable
          class="search-input"
          @input="onSearchInput"
          @clear="onSearchInput"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-select
          v-model="productCode"
          placeholder="全部产品"
          clearable
          class="product-filter"
          @change="onFilterChange"
        >
          <el-option
            v-for="code in productCodes"
            :key="code"
            :label="code"
            :value="code"
          />
        </el-select>
        <el-button
          type="danger"
          plain
          :disabled="selectedIds.length === 0"
          @click="onBulkDelete"
        >
          <el-icon><Delete /></el-icon>
          批量删除{{ selectedIds.length ? ` (${selectedIds.length})` : '' }}
        </el-button>
      </div>
    </div>

    <el-table
      ref="tableRef"
      :data="files"
      stripe
      style="width: 100%"
      v-loading="loading"
      :header-cell-style="{ background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontWeight: '600' }"
      :row-class-name="tableRowClassName"
      @row-click="onRowClick"
      @selection-change="onSelectionChange"
      highlight-current-row
    >
      <el-table-column type="selection" width="44" align="center" />
      <el-table-column prop="id" label="ID" width="70" align="center">
        <template #default="{ row }">
          <span class="id-badge">#{{ row.id }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="filename" label="文件名" min-width="280">
        <template #default="{ row }">
          <div class="filename-cell">
            <span class="file-icon">📄</span>
            <span class="file-name">{{ row.filename }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="product_code" label="产品" width="130">
        <template #default="{ row }">
          <el-tag v-if="row.product_code" size="small" type="info" effect="plain">
            {{ row.product_code }}
          </el-tag>
          <span v-else class="empty-text">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="上传时间" width="160">
        <template #default="{ row }">
          <span class="time-text">{{ formatTime(row.created_at) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="source_mtime" label="原始修改时间" width="160">
        <template #default="{ row }">
          <span class="time-text">{{ row.source_mtime ? formatTime(row.source_mtime) : '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="file_size" label="文件大小" width="110" align="right">
        <template #default="{ row }">
          <span class="size-badge">{{ formatSize(row.file_size) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" align="center">
        <template #default="{ row }">
          <el-button size="small" type="primary" plain @click.stop="viewFile(row)">查看</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="list-pagination">
      <el-pagination
        v-if="total > pageSize"
        layout="total, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page="currentPage"
        background
        @current-change="onPageChange"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { Search, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, type ElTable } from 'element-plus'
import { datafilesApi } from '../../../api/datafiles'
import { useFilesStore } from '../../../stores/files'

const emit = defineEmits<{
  'view-file': [id: number, filename: string]
  'row-click': [id: number, filename: string]
  'total-change': [total: number]
}>()

const filesStore = useFilesStore()

const files = ref<any[]>([])
const loading = ref(false)
const total = ref(0)
const currentPage = ref(1)
const pageSize = 20

const searchText = ref('')
const productCode = ref('')
const productCodes = ref<string[]>([])
const selectedRows = ref<any[]>([])
const tableRef = ref<InstanceType<typeof ElTable>>()

const selectedIds = ref<number[]>([])
let searchTimer: ReturnType<typeof setTimeout> | undefined

async function loadFiles() {
  loading.value = true
  try {
    const { data } = await datafilesApi.listFiles({
      page: currentPage.value,
      search: searchText.value,
      product_code: productCode.value,
      ordering: '-created_at',
    })
    if (Array.isArray(data)) {
      files.value = data
      total.value = data.length
    } else {
      files.value = data.results ?? []
      total.value = data.count ?? files.value.length
    }
    emit('total-change', total.value)
  } catch {
    files.value = []
    total.value = 0
    emit('total-change', 0)
  } finally {
    loading.value = false
  }
}

async function loadProductCodes() {
  try {
    const { data } = await datafilesApi.getProductCodes()
    productCodes.value = data.product_codes ?? []
  } catch {
    productCodes.value = []
  }
}

function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    loadFiles()
  }, 300)
}

function onFilterChange() {
  currentPage.value = 1
  loadFiles()
}

function onPageChange(page: number) {
  currentPage.value = page
  loadFiles()
}

function onSelectionChange(rows: any[]) {
  selectedRows.value = rows
  selectedIds.value = rows.map((r) => r.id)
}

async function onBulkDelete() {
  if (selectedIds.value.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${selectedIds.value.length} 个文件吗？磁盘上的源文件也会被一并移除，此操作不可恢复。`,
      '批量删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    const ids = [...selectedIds.value]
    const { data } = await datafilesApi.bulkDelete(ids)
    ElMessage.success(`已删除 ${data?.deleted ?? ids.length} 个文件`)
    tableRef.value?.clearSelection()
    selectedRows.value = []
    selectedIds.value = []
    // 当前页删空且非首页时回到上一页
    if (files.value.length === ids.length && currentPage.value > 1) {
      currentPage.value -= 1
    }
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('批量删除失败')
  }
}

function formatTime(val: string) {
  if (!val) return ''
  return new Date(val).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function formatSize(val: number) {
  if (!val) return '--'
  if (val < 1024) return val + ' B'
  if (val < 1024 * 1024) return (val / 1024).toFixed(1) + ' KB'
  return (val / 1024 / 1024).toFixed(1) + ' MB'
}

function viewFile(row: any) {
  emit('view-file', row.id, row.filename)
}

function onRowClick(row: any) {
  emit('row-click', row.id, row.filename)
}

function tableRowClassName({ rowIndex }: { rowIndex: number }) {
  return rowIndex % 2 === 0 ? 'row-even' : 'row-odd'
}

// 外部操作（SFTP 导入/上传）后刷新列表
watch(() => filesStore.filesVersion, () => { loadFiles() })

onMounted(() => {
  loadFiles()
  loadProductCodes()
})

defineExpose({ reload: loadFiles })
</script>

<style scoped>
.list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.section-count {
  font-size: 12px;
  color: var(--text-tertiary);
  padding: 2px 8px;
  background: var(--bg-secondary);
  border-radius: 10px;
}

.search-input {
  width: 220px;
}

.product-filter {
  width: 160px;
}

.empty-text {
  color: var(--text-tertiary);
}

.list-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

/* ============================
   Table Styling
   ============================ */
:deep(.el-table) {
  --el-table-border-color: var(--border-muted);
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: var(--bg-secondary);
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--border-muted);
}

:deep(.el-table th.el-table__cell) {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

:deep(.el-table .row-even) {
  --el-table-tr-bg-color: transparent;
}

:deep(.el-table .row-odd) {
  --el-table-tr-bg-color: var(--bg-secondary);
}

:deep(.el-table .el-table__row) {
  cursor: pointer;
  transition: background 0.15s ease;
}

:deep(.el-table .el-table__row:hover > td) {
  background: var(--bg-secondary) !important;
}

.id-badge {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.filename-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.file-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.time-text {
  font-size: 12px;
  color: var(--text-secondary);
  font-family: var(--font-mono);
}

.size-badge {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-info);
  font-family: var(--font-mono);
}

/* ============================
   Night Theme Overrides
   ============================ */
:root[data-theme="night"] .section-count {
  background: rgba(255, 255, 255, 0.08);
}

:root[data-theme="night"] .size-badge {
  color: var(--color-info);
}
</style>
