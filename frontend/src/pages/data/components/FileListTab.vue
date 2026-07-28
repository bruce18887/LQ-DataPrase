<template>
  <div class="file-list-tab">
    <!-- Toolbar -->
    <FileListToolbar
      :total="total"
      :product-codes="productCodes"
      :selected-count="selectedIds.length"
      @search="onSearch"
      @filter-change="onFilterChange"
      @upload-click="showUpload = !showUpload"
      @fix-click="showConsistencyCheck = true"
      @bulk-delete="onBulkDelete"
    />

    <!-- Upload Area -->
    <FileUploadArea
      :visible="showUpload"
      @upload-success="onUploadSuccess"
    />

    <!-- Batch Management -->
    <BatchManagement
      ref="batchRef"
      :active-file-id="activeFileId"
      @file-selected="emit('file-selected', $event)"
      @data-changed="onBatchDataChanged"
    />

    <!-- File Table -->
    <el-table
      ref="tableRef"
      :data="files"
      :row-key="(row: any) => row.id"
      stripe
      style="width: 100%"
      v-loading="loading"
      :header-cell-style="{ background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontWeight: '600' }"
      :row-class-name="tableRowClassName"
      @row-click="onRowClick"
      @selection-change="onSelectionChange"
      @expand-change="onExpandChange"
      :expand-row-keys="expandedRowIds"
      highlight-current-row
    >
      <el-table-column type="expand">
        <template #default="{ row }">
          <FileRowDetail :row="row" @remove-tag="removeTag" />
        </template>
      </el-table-column>
      <el-table-column type="selection" width="44" align="center" />
      <el-table-column prop="id" label="ID" width="70" align="center">
        <template #default="{ row }">
          <span class="id-badge">#{{ row.id }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="filename" label="文件名" min-width="200">
        <template #default="{ row }">
          <div class="filename-cell">
            <span class="file-icon">📄</span>
            <span class="file-name" :title="row.filename">{{ truncateMiddle(row.filename, 32) }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="product_code" label="产品" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.product_code" size="small" type="info" effect="plain">
            {{ row.product_code }}
          </el-tag>
          <span v-else class="empty-text">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="format_type" label="格式" width="80" />
      <el-table-column label="行列" width="100" align="center">
        <template #default="{ row }">
          <span class="mono">{{ row.row_count }}×{{ row.col_count }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="program_name" label="测试程序" min-width="120">
        <template #default="{ row }">
          <span class="program-name-cell" :title="row.program_name">{{ row.program_name || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="标签" min-width="180" class-name="tag-cell">
        <template #default="{ row }">
          <div class="tag-cell-inner">
            <el-tag
              v-for="t in (row.tags || [])"
              :key="t"
              closable
              size="small"
              type="info"
              effect="light"
              class="file-tag"
              @close="removeTag(row, t)"
            >{{ t }}</el-tag>
            <div v-if="editingId === row.id" class="tag-input-wrapper">
              <input
                ref="tagInputRef"
                :value="newTagValue"
                type="text"
                class="tag-native-input"
                placeholder="新标签+回车"
                maxlength="50"
                @input="onTagInput"
                @keydown="onTagKeydown($event, row)"
                @blur="scheduleBlurCommit(row)"
              />
              <div v-if="showTagSuggestions && tagSuggestions.length > 0" class="tag-suggestions">
                <div
                  v-for="(s, i) in tagSuggestions"
                  :key="s"
                  class="tag-suggestion-item"
                  :class="{ 'is-active': i === selectedSuggestionIdx }"
                  @mousedown.prevent="selectSuggestion(s)"
                >
                  {{ s }}
                </div>
              </div>
            </div>
            <el-button
              v-else
              size="small"
              type="primary"
              plain
              class="add-tag-btn"
              @click.stop="startAddTag(row)"
            >
              <el-icon><Plus /></el-icon>
            </el-button>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="上传时间" width="140">
        <template #default="{ row }">
          <span class="time-text">{{ formatTime(row.created_at) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="file_size" label="大小" width="90" align="right">
        <template #default="{ row }">
          <span class="size-badge">{{ formatSize(row.file_size) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" align="center" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" plain @click.stop="viewFile(row)">查看</el-button>
          <el-button size="small" type="danger" plain @click.stop="deleteFile(row)">
            <el-icon><Delete /></el-icon>
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Pagination -->
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

    <!-- Consistency Check Dialog -->
    <ConsistencyCheckDialog
      v-model:visible="showConsistencyCheck"
      @done="onConsistencyDone"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { Plus, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, type ElTable } from 'element-plus'
import { datafilesApi } from '../../../api/datafiles'
import { useFilesStore } from '../../../stores/files'
import { truncateMiddle, formatSize, formatTime } from '../../../utils/format'
import { useTagEditing } from '../composables/useTagEditing'
import FileListToolbar from './FileListToolbar.vue'
import FileUploadArea from './FileUploadArea.vue'
import BatchManagement from './BatchManagement.vue'
import ConsistencyCheckDialog from './ConsistencyCheckDialog.vue'
import FileRowDetail from './FileRowDetail.vue'

const emit = defineEmits<{
  'view-file': [id: number, filename: string]
  'row-click': [id: number, filename: string]
  'total-change': [total: number]
  'file-selected': [id: number]
}>()

const props = defineProps<{
  activeFileId?: number
}>()

const filesStore = useFilesStore()

// ── Core state ──────────────────────────────────────────────────────
const files = ref<any[]>([])
const loading = ref(false)

// ── Tag editing composable ──────────────────────────────────────────
const {
  editingId, newTagValue, tagInputRef,
  tagSuggestions, showTagSuggestions, selectedSuggestionIdx,
  startAddTag, scheduleBlurCommit, removeTag,
  onTagInput, selectSuggestion, onTagKeydown,
} = useTagEditing(files)
const total = ref(0)
const currentPage = ref(1)
const pageSize = 20

const productCodes = ref<string[]>([])
const selectedRows = ref<any[]>([])
const tableRef = ref<InstanceType<typeof ElTable>>()
const selectedIds = ref<number[]>([])

// Current search/filter values (received from toolbar)
const currentSearch = ref('')
const currentProductCode = ref('')

// Upload toggle
const showUpload = ref(false)

// Consistency dialog toggle
const showConsistencyCheck = ref(false)

// BatchManagement ref (for calling loadBatchDirs externally)
const batchRef = ref<InstanceType<typeof BatchManagement>>()

// Expand row state
const expandedRowIds = ref<number[]>([])
function onExpandChange(_row: any, expanded: any[]) {
  expandedRowIds.value = expanded.map((r: any) => r.id)
}

// ── Data loading ────────────────────────────────────────────────────
async function loadFiles() {
  loading.value = true
  try {
    const { data } = await datafilesApi.listFiles({
      page: currentPage.value,
      search: currentSearch.value,
      product_code: currentProductCode.value,
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

// ── Toolbar event handlers ──────────────────────────────────────────
function onSearch(text: string) {
  currentSearch.value = text
  currentPage.value = 1
  loadFiles()
}

function onFilterChange(code: string) {
  currentProductCode.value = code
  currentPage.value = 1
  loadFiles()
}

function onUploadSuccess() {
  loadFiles()
  filesStore.notifyFilesChanged()
}

function onBatchDataChanged() {
  loadFiles()
  loadProductCodes()
}

function onConsistencyDone() {
  loadFiles()
  batchRef.value?.loadBatchDirs()
  filesStore.notifyFilesChanged()
}

// ── Pagination ──────────────────────────────────────────────────────
function onPageChange(page: number) {
  currentPage.value = page
  loadFiles()
}

function onSelectionChange(rows: any[]) {
  selectedRows.value = rows
  selectedIds.value = rows.map((r) => r.id)
}

// ── Delete operations ───────────────────────────────────────────────
async function deleteFile(row: any) {
  try {
    await ElMessageBox.confirm(
      `确定删除文件 "${row.filename}" 吗？此操作不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    await datafilesApi.remove(row.id)
    ElMessage.success('文件已删除')
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
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
    if (files.value.length === ids.length && currentPage.value > 1) {
      currentPage.value -= 1
    }
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('批量删除失败')
  }
}

// ── Row interactions ────────────────────────────────────────────────
function viewFile(row: any) {
  emit('view-file', row.id, row.filename)
}

function onRowClick(row: any) {
  emit('row-click', row.id, row.filename)
}

function tableRowClassName({ rowIndex }: { rowIndex: number }) {
  return rowIndex % 2 === 0 ? 'row-even' : 'row-odd'
}

// ── External refresh watcher ────────────────────────────────────────
watch(() => filesStore.filesVersion, () => {
  loadFiles()
  batchRef.value?.loadBatchDirs()
  loadProductCodes()
})

onMounted(() => {
  loadFiles()
  loadProductCodes()
  // BatchManagement loads its own dirs in its onMounted
})

defineExpose({ reload: loadFiles })
</script>

<style scoped>
.empty-text {
  color: var(--text-tertiary);
}

.list-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

/* ============================
   Tag Cell
   ============================ */
.tag-cell-inner {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 28px;
  max-height: 80px;
  overflow-y: auto;
}

.file-tag {
  margin: 0;
}

.add-tag-btn {
  font-size: 12px;
  padding: 2px 8px;
  height: 24px;
}

.tag-native-input {
  width: 140px;
  height: 24px;
  padding: 0 8px;
  font-size: 12px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--brand-primary);
  border-radius: 4px;
  outline: none;
  box-sizing: border-box;
}

.tag-native-input::placeholder {
  color: var(--text-tertiary);
}

.tag-input-wrapper {
  position: relative;
  display: inline-block;
}

.tag-suggestions {
  position: absolute;
  bottom: 100%;
  left: 0;
  min-width: 180px;
  max-height: 200px;
  overflow-y: auto;
  background: var(--bg-primary);
  border: 1px solid var(--border-default);
  border-radius: 6px;
  box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.15);
  z-index: 100;
  margin-bottom: 4px;
}

.tag-suggestion-item {
  padding: 6px 12px;
  font-size: 12px;
  color: var(--text-primary);
  cursor: pointer;
  transition: background 0.15s;
}

.tag-suggestion-item:hover,
.tag-suggestion-item.is-active {
  background: var(--bg-secondary);
  color: var(--brand-primary);
}

:root[data-theme="night"] .tag-suggestions {
  background: var(--bg-secondary);
  border-color: rgba(255, 255, 255, 0.1);
  box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.4);
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

.mono {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-secondary);
}

.program-name-cell {
  color: var(--text-secondary);
  font-size: 12px;
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
:root[data-theme="night"] .size-badge {
  color: var(--color-info);
}
</style>
