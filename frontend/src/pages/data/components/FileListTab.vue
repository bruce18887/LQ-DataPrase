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
          placeholder="按文件名/程序名/标签搜索"
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
          type="primary"
          @click="showUpload = !showUpload"
        >
          <el-icon><Upload /></el-icon>
          上传文件
        </el-button>
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

    <!-- Upload Area (Collapsible) -->
    <el-collapse-transition>
      <div v-show="showUpload" class="upload-section">
        <el-upload
          drag
          :http-request="handleUpload"
          accept=".csv,.txt,.dat,.zip,.7z,.rar"
          :show-file-list="false"
          multiple
        >
          <el-icon :size="48"><UploadFilled /></el-icon>
          <div class="upload-text">拖拽文件到此处 或 <em>点击上传</em></div>
          <div class="upload-hint">支持多文件上传，ZIP/7z/RAR 压缩包会自动解压</div>
        </el-upload>
        <el-progress
          v-if="uploadProgress > 0 && uploadProgress < 100"
          :percentage="uploadProgress"
          style="margin-top: 8px"
        />
      </div>
    </el-collapse-transition>

    <!-- Batch Management (Conditional) -->
    <template v-if="unregisteredDirs.length > 0 || batchGroups.length > 0">
      <div class="batch-section">
        <!-- Unregistered batch directories -->
        <template v-if="unregisteredDirs.length > 0">
          <div class="section-label">📂 SFTP 下载目录（未导入）</div>
          <div v-for="dir in unregisteredDirs" :key="dir.name" class="batch-group unregistered">
            <div class="batch-header">
              <span class="batch-name">📁 {{ dir.name }}</span>
              <span class="batch-count">{{ dir.file_count }} 个文件</span>
              <span class="batch-size">{{ formatSize(dir.total_size) }}</span>
              <div style="flex:1" />
              <el-button size="small" type="success" @click="importDir(dir)" :loading="importingDir === dir.name">
                <el-icon><Upload /></el-icon> 导入
              </el-button>
              <el-button size="small" type="danger" plain @click="deleteDir(dir)">
                <el-icon><Delete /></el-icon> 删除
              </el-button>
            </div>
          </div>
        </template>

        <!-- Batch files grouped (registered) -->
        <template v-if="batchGroups.length > 0">
          <div class="section-label">📦 已导入批次</div>
          <div v-for="group in batchGroups" :key="group.name" class="batch-group">
            <div class="batch-header">
              <span class="batch-name">📦 {{ group.name }}</span>
              <span class="batch-count">{{ group.files.length }} 个文件</span>
              <div style="flex:1" />
              <el-button size="small" type="danger" plain @click="deleteBatch(group)">
                <el-icon><Delete /></el-icon> 删除批次
              </el-button>
            </div>
            <div class="batch-files">
              <el-tag
                v-for="f in group.files"
                :key="f.id"
                :type="f.id === activeFileId ? 'primary' : 'info'"
                :effect="f.id === activeFileId ? 'dark' : 'plain'"
                class="batch-file-tag"
                @click="emit('file-selected', f.id)"
              >
                {{ f.filename }}
              </el-tag>
            </div>
          </div>
        </template>
      </div>
    </template>

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
          <div class="row-detail">
            <div class="detail-row">
              <span class="detail-label">完整文件名</span>
              <span class="detail-value mono">{{ row.filename }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">测试程序</span>
              <span class="detail-value">{{ row.program_name || '—' }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">所有标签</span>
              <div class="detail-value tag-wrap">
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
                <span v-if="!row.tags || row.tags.length === 0" class="empty-text">无标签</span>
              </div>
            </div>
          </div>
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
            <input
              v-if="editingId === row.id"
              ref="tagInputRef"
              v-model="newTagValue"
              type="text"
              class="tag-native-input"
              placeholder="新标签+回车"
              maxlength="50"
              @keyup.enter="commitNewTag(row)"
              @blur="scheduleBlurCommit(row)"
            />
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
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { Search, Delete, Upload, UploadFilled, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, type ElTable } from 'element-plus'
import { datafilesApi, type BatchDirInfo } from '../../../api/datafiles'
import { useFilesStore } from '../../../stores/files'

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

// Upload state
const showUpload = ref(false)
const uploadProgress = ref(0)

// Batch management state
const batchDirs = ref<BatchDirInfo[]>([])
const importingDir = ref('')

// Tag editing state
const editingId = ref<number | null>(null)
const newTagValue = ref('')
const tagInputRef = ref<any>(null)

// Expand row state (driven by expand-row-keys)
const expandedRowIds = ref<number[]>([])
function onExpandChange(_row: any, expanded: any[]) {
  expandedRowIds.value = expanded.map((r) => r.id)
}

// 中段省略号：保留首尾有信息量的部分（适合文件名/路径）
function truncateMiddle(s: string, max: number) {
  if (!s || s.length <= max) return s
  const head = Math.ceil(max / 2) - 1
  const tail = Math.floor(max / 2) - 1
  return s.slice(0, head) + '…' + s.slice(-tail)
}

// Computed
const unregisteredDirs = computed(() => batchDirs.value.filter(d => !d.registered))

const batchGroups = computed(() => {
  const batches = files.value.filter(f => f.file_type === 'batch' && f.batch_name)
  const groups = new Map<string, any[]>()
  for (const f of batches) {
    const key = f.batch_name || 'unknown'
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key)!.push(f)
  }
  return Array.from(groups.entries()).map(([name, files]) => ({ name, files }))
})

// Load files
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

// Batch management
async function loadBatchDirs() {
  try {
    const { data } = await datafilesApi.listBatchDirs()
    batchDirs.value = Array.isArray(data) ? data : []
  } catch {
    batchDirs.value = []
  }
}

async function importDir(dir: BatchDirInfo) {
  importingDir.value = dir.name
  try {
    await datafilesApi.importBatchDir(dir.name)
    ElMessage.success(`批次 "${dir.name}" 已导入`)
    await Promise.all([loadFiles(), loadBatchDirs()])
    filesStore.notifyFilesChanged()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '导入失败')
  } finally {
    importingDir.value = ''
  }
}

async function deleteDir(dir: BatchDirInfo) {
  try {
    await ElMessageBox.confirm(
      `确定删除目录 "${dir.name}" 及其 ${dir.file_count} 个文件吗？此操作不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await datafilesApi.deleteBatchDir(dir.name)
    ElMessage.success(`目录 "${dir.name}" 已删除`)
    await Promise.all([loadFiles(), loadBatchDirs()])
    filesStore.notifyFilesChanged()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e?.response?.data?.error || '删除失败')
    }
  }
}

async function deleteBatch(group: { name: string; files: any[] }) {
  try {
    await ElMessageBox.confirm(
      `确定删除批次 "${group.name}" 及其 ${group.files.length} 个文件吗？此操作不可恢复。`,
      '确认删除批次',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    for (const f of group.files) {
      try { await datafilesApi.remove(f.id) } catch {}
    }
    ElMessage.success(`批次 "${group.name}" 已删除`)
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

// Upload
async function handleUpload(options: { file: File }) {
  uploadProgress.value = 0
  try {
    await datafilesApi.upload(options.file, (pct: number) => {
      uploadProgress.value = pct
    })
    ElMessage.success(`${options.file.name} 上传成功`)
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch {
    ElMessage.error(`${options.file.name} 上传失败`)
  } finally {
    uploadProgress.value = 0
  }
}

// Search and filter
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

// Delete operations
async function deleteFile(row: any) {
  try {
    await ElMessageBox.confirm(
      `确定删除文件 "${row.filename}" 吗？此操作不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
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

// Tag management
function startAddTag(row: any) {
  editingId.value = row.id
  newTagValue.value = ''
  nextTick(() => {
    const el = (tagInputRef.value as any)?.$el ?? tagInputRef.value
    if (el && typeof el.focus === 'function') el.focus()
  })
}

let blurTimer: ReturnType<typeof setTimeout> | null = null
function scheduleBlurCommit(row: any) {
  if (blurTimer) clearTimeout(blurTimer)
  blurTimer = setTimeout(() => {
    blurTimer = null
    if (editingId.value !== row.id) return
    const t = newTagValue.value.trim()
    if (t) {
      commitNewTag(row)
    } else {
      editingId.value = null
      newTagValue.value = ''
    }
  }, 150)
}

async function commitNewTag(row: any) {
  const t = newTagValue.value.trim()
  if (!t) {
    editingId.value = null
    newTagValue.value = ''
    return
  }
  const current = Array.isArray(row.tags) ? row.tags : []
  if (current.some((x: string) => x.toLowerCase() === t.toLowerCase())) {
    ElMessage.warning(`标签「${t}」已存在`)
    editingId.value = null
    newTagValue.value = ''
    return
  }
  const next = [...current, t]
  try {
    const { data } = await datafilesApi.setTags(row.id, next)
    row.tags = data.tags
    ElMessage.success(`已添加标签「${t}」`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.tags?.[0] || '标签更新失败')
  } finally {
    editingId.value = null
    newTagValue.value = ''
  }
}

async function removeTag(row: any, tag: string) {
  const current = Array.isArray(row.tags) ? row.tags : []
  const next = current.filter((x: string) => x.toLowerCase() !== tag.toLowerCase())
  if (next.length === current.length) return
  try {
    const { data } = await datafilesApi.setTags(row.id, next)
    row.tags = data.tags
    ElMessage.success(`已移除标签「${tag}」`)
  } catch {
    ElMessage.error('标签移除失败')
  }
}

// Utility
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

// External operations (SFTP import/upload) refresh list
watch(() => filesStore.filesVersion, () => {
  loadFiles()
  loadBatchDirs()
})

onMounted(() => {
  loadFiles()
  loadProductCodes()
  loadBatchDirs()
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
   Upload Section
   ============================ */
.upload-section {
  margin-bottom: 16px;
  padding: 16px;
  background: var(--bg-secondary);
  border: 1px dashed var(--border-default);
  border-radius: 10px;
}

.upload-text {
  font-size: 14px;
  color: var(--text-secondary);
  margin-top: 8px;
}

.upload-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 4px;
}

/* ============================
   Batch Section
   ============================ */
.batch-section {
  margin-bottom: 16px;
}

.section-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.batch-group {
  margin-bottom: 12px;
  padding: 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-radius: 10px;
}

.batch-group.unregistered {
  border-left: 3px solid var(--color-warning);
}

.batch-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.batch-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.batch-count {
  font-size: 12px;
  color: var(--text-tertiary);
  padding: 2px 8px;
  background: var(--bg-primary);
  border-radius: 10px;
}

.batch-size {
  font-size: 12px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.batch-files {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.batch-file-tag {
  cursor: pointer;
  transition: all 0.2s ease;
}

.batch-file-tag:hover {
  transform: translateY(-1px);
}

/* ============================
   Expand Row Detail
   ============================ */
.row-detail {
  padding: 12px 24px 16px 56px;
  background: var(--bg-secondary);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 6px 8px;
}
.detail-row {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  min-height: 20px;
}
.detail-label {
  flex-shrink: 0;
  width: 96px;
  font-size: 12px;
  color: var(--text-tertiary);
  padding-top: 1px;
}
.detail-value {
  flex: 1;
  font-size: 13px;
  color: var(--text-primary);
  word-break: break-all;
  line-height: 1.5;
}
.detail-value.tag-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
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
:root[data-theme="night"] .section-count {
  background: rgba(255, 255, 255, 0.08);
}

:root[data-theme="night"] .size-badge {
  color: var(--color-info);
}

:root[data-theme="night"] .upload-section {
  border-color: rgba(255, 255, 255, 0.1);
}

:root[data-theme="night"] .batch-group {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.08);
}

:root[data-theme="night"] .batch-group.unregistered {
  border-left-color: var(--color-warning);
}
</style>
