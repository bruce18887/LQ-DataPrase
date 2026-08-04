<template>
  <div>
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
    <el-divider />

    <!-- Unregistered batch directories (from SFTP downloads) -->
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
      <div class="section-label-row">
        <span class="section-label">📦 已导入批次</span>
        <el-button
          size="small"
          text
          class="batch-toggle-all"
          data-testid="batch-toggle-all"
          @click="toggleAllBatches"
        >
          <el-icon><component :is="allBatchesExpanded ? ArrowUp : ArrowDown" /></el-icon>
          {{ allBatchesExpanded ? '全部折叠' : '全部展开' }}
        </el-button>
      </div>
      <div v-for="group in batchGroups" :key="group.name" class="batch-group" :data-testid="`batch-group-${group.name}`">
        <div
          class="batch-header batch-header-clickable"
          role="button"
          tabindex="0"
          :aria-expanded="isBatchExpanded(group.name)"
          :data-testid="`batch-header-${group.name}`"
          @click="toggleBatch(group.name)"
          @keydown.enter.prevent="toggleBatch(group.name)"
          @keydown.space.prevent="toggleBatch(group.name)"
        >
          <el-icon class="batch-chevron" :class="{ 'batch-chevron-open': isBatchExpanded(group.name) }">
            <ArrowRight />
          </el-icon>
          <span class="batch-name">📦 {{ group.name }}</span>
          <span class="batch-count">{{ group.files.length }} 个文件</span>
          <div style="flex:1" />
          <el-button size="small" type="danger" plain @click.stop="deleteBatch(group)">
            <el-icon><Delete /></el-icon> 删除批次
          </el-button>
        </div>
        <el-collapse-transition>
          <div v-show="isBatchExpanded(group.name)" class="batch-files-grid" :data-testid="`batch-files-${group.name}`">
            <el-row :gutter="12">
              <el-col :span="8" v-for="f in group.files" :key="f.id">
                <el-card shadow="hover" :class="{ 'active-file': f.id === activeFileId }">
                  <div style="font-weight:bold; color: var(--text-primary)">{{ f.filename }}</div>
                  <div style="color: var(--text-secondary); font-size:12px; margin:4px 0">
                    {{ f.format_type }} | {{ f.row_count }}行×{{ f.col_count }}列
                  </div>
                  <div style="color: var(--text-secondary); font-size:12px" v-if="f.program_name" class="program-name">{{ f.program_name }}</div>
                  <div v-if="f.tags && f.tags.length" class="tag-row">
                    <el-tag
                      v-for="t in f.tags"
                      :key="t"
                      size="small"
                      type="info"
                      effect="plain"
                      class="file-tag"
                    >{{ t }}</el-tag>
                  </div>
                  <el-row :gutter="8" style="margin-top:8px">
                    <el-col :span="16">
                      <el-button size="small" type="primary" @click="emit('file-selected', f.id)" style="width: 100%">
                        {{ f.id === activeFileId ? '✓ 当前文件' : '浏览数据' }}
                      </el-button>
                    </el-col>
                    <el-col :span="8">
                      <el-button size="small" type="danger" @click.stop="deleteFile(f)" aria-label="删除文件">
                        <el-icon><Delete /></el-icon>
                      </el-button>
                    </el-col>
                  </el-row>
                </el-card>
              </el-col>
            </el-row>
          </div>
        </el-collapse-transition>
      </div>
    </template>

    <!-- Single files (table + pagination + search) -->
    <template v-if="singleFilesRaw.length > 0 || filterKeyword || filterTag">
      <div class="section-label" v-if="batchGroups.length > 0 || unregisteredDirs.length > 0">📁 单文件</div>
      <FileSearchBar
        :available-tags="allTags"
        @change="onSearchChange"
      />
      <div v-if="filteredSingleFiles.length === 0" class="empty-filter">
        <el-empty description="没有匹配的单文件" :image-size="80" />
      </div>
      <SingleFileTable
        v-else
        :files="filteredSingleFiles"
        :active-file-id="activeFileId"
        @file-selected="(id) => emit('file-selected', id)"
        @delete-file="deleteFile"
        @tags-updated="onSingleTagsUpdated"
      />
    </template>

    <el-empty v-if="files.length === 0 && unregisteredDirs.length === 0" description="暂无文件" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { UploadFilled, Delete, Upload, ArrowRight, ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { datafilesApi, type BatchDirInfo } from '../../api/datafiles'
import { useFilesStore } from '../../stores/files'
import type { DataFile } from '../../types'
import SingleFileTable from './components/SingleFileTable.vue'
import FileSearchBar from './components/FileSearchBar.vue'

const props = defineProps<{ activeFileId?: number }>()
const emit = defineEmits<{ 'file-selected': [id: number] }>()

const files = ref<DataFile[]>([])
const uploadProgress = ref(0)
const batchDirs = ref<BatchDirInfo[]>([])
const importingDir = ref('')
const filesStore = useFilesStore()
const allTags = ref<string[]>([])
const filterKeyword = ref('')
const filterTag = ref('')

// Sync batchDirs when files change externally (e.g. SFTP auto-import)
watch(() => filesStore.filesVersion, () => {
  loadFiles()
  loadBatchDirs()
  loadAllTags()
})

const singleFilesRaw = computed(() => files.value.filter(f => f.file_type !== 'batch'))

const filteredSingleFiles = computed(() => {
  const kw = filterKeyword.value.toLowerCase()
  const tag = filterTag.value.toLowerCase()
  return singleFilesRaw.value.filter((f) => {
    if (tag) {
      const tags = Array.isArray(f.tags) ? f.tags : []
      if (!tags.some((t) => t.toLowerCase() === tag)) return false
    }
    if (!kw) return true
    if ((f.filename || '').toLowerCase().includes(kw)) return true
    if ((f.program_name || '').toLowerCase().includes(kw)) return true
    const tags = Array.isArray(f.tags) ? f.tags : []
    return tags.some((t) => t.toLowerCase().includes(kw))
  })
})

const unregisteredDirs = computed(() => batchDirs.value.filter(d => !d.registered))

// 已导入批次直接来自 batch-dirs（磁盘走查，返回全部批次），不再依赖分页 files —
// 否则新下载文件占满第 1 页后，旧批次被挤出列表而“消失”。
const batchGroups = computed(() =>
  batchDirs.value
    .filter(d => d.registered)
    .map(d => ({ name: d.name, files: d.files })),
)

// 已导入批次默认折叠：单批次可能含 100+ 文件，全部展开会撑高页面。
// 用户点击 header 单独展开需要的批次。
const expandedBatches = ref<Set<string>>(new Set())

function isBatchExpanded(name: string) {
  return expandedBatches.value.has(name)
}

function toggleBatch(name: string) {
  const next = new Set(expandedBatches.value)
  if (next.has(name)) {
    next.delete(name)
  } else {
    next.add(name)
  }
  expandedBatches.value = next
}

const allBatchesExpanded = computed(() => {
  if (batchGroups.value.length === 0) return false
  return batchGroups.value.every((g) => expandedBatches.value.has(g.name))
})

function toggleAllBatches() {
  if (allBatchesExpanded.value) {
    expandedBatches.value = new Set()
  } else {
    expandedBatches.value = new Set(batchGroups.value.map((g) => g.name))
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
}

function onSearchChange(payload: { keyword: string; tag: string }) {
  filterKeyword.value = payload.keyword
  filterTag.value = payload.tag
}

function onSingleTagsUpdated(updated: DataFile) {
  // Replace the row in the source list so props change triggers el-table re-render.
  // 直接修改 row.tags 不会触发响应式（Vue 不会深度追踪 props 内部对象），必须替换数组元素。
  const next = files.value.map((f) => (f.id === updated.id ? { ...f, tags: [...(updated.tags ?? [])] } : f))
  files.value = next
  // Refresh the allTags list so the search bar reflects new entries
  loadAllTags()
}

async function loadAllTags() {
  try {
    const { data } = await datafilesApi.listTags()
    allTags.value = Array.isArray(data?.tags) ? data.tags : []
  } catch {
    allTags.value = []
  }
}

async function handleUpload(options: { file: File }) {
  uploadProgress.value = 0
  try {
    await datafilesApi.upload(options.file, (pct: number) => {
      uploadProgress.value = pct
    })
    ElMessage.success(`${options.file.name} 上传成功`)
    await loadFiles()
    await loadAllTags()
    filesStore.notifyFilesChanged()
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  } finally {
    uploadProgress.value = 0
  }
}

async function loadFiles() {
  try {
    const { data } = await datafilesApi.list()
    files.value = Array.isArray(data) ? data : (data.results ?? [])
  } catch {
    // silently ignore fetch errors
  }
}

async function loadBatchDirs() {
  try {
    const { data } = await datafilesApi.listBatchDirs()
    batchDirs.value = Array.isArray(data) ? data : []
    // 清理已不存在的批次
    const valid = new Set(batchGroups.value.map((g) => g.name))
    const filtered = new Set([...expandedBatches.value].filter((n) => valid.has(n)))
    if (filtered.size !== expandedBatches.value.size) {
      expandedBatches.value = filtered
    }
  } catch {
    // silently ignore
  }
}

async function importDir(dir: BatchDirInfo) {
  importingDir.value = dir.name
  try {
    await datafilesApi.importBatchDir(dir.name)
    ElMessage.success(`批次 "${dir.name}" 已导入`)
    await Promise.all([loadFiles(), loadBatchDirs()])
    filesStore.notifyFilesChanged()
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
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
  } catch {
    // ElMessageBox 取消 reject "cancel"；真实错误 toast 由拦截器弹出
  }
}

async function deleteFile(file: DataFile) {
  try {
    await ElMessageBox.confirm(
      `确定删除文件 "${file.filename}" 吗？此操作不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await datafilesApi.remove(file.id)
    ElMessage.success('文件已删除')
    await loadFiles()
    await loadAllTags()
    filesStore.notifyFilesChanged()
  } catch {
    // ElMessageBox 取消 reject "cancel"；真实错误 toast 由拦截器弹出
  }
}

async function deleteBatch(group: { name: string; files: DataFile[] }) {
  try {
    await ElMessageBox.confirm(
      `确定删除批次 "${group.name}" 及其 ${group.files.length} 个文件吗？此操作不可恢复。`,
      '确认删除批次',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    // Delete all files in the batch
    for (const f of group.files) {
      try { await datafilesApi.remove(f.id) } catch {}
    }
    ElMessage.success(`批次 "${group.name}" 已删除`)
    await loadFiles()
    await loadAllTags()
    filesStore.notifyFilesChanged()
  } catch {
    // ElMessageBox 取消 reject "cancel"；真实错误 toast 由拦截器弹出
  }
}

onMounted(() => {
  loadFiles()
  loadBatchDirs()
  loadAllTags()
})
</script>

<style scoped>
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
.active-file {
  border: 2px solid var(--brand-primary);
}
.program-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}

.file-tag {
  font-size: 11px;
}

.batch-group {
  margin-bottom: 20px;
  padding: 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-radius: 10px;
}

.batch-group.unregistered {
  border-left: 3px solid var(--color-warning);
}

.batch-size {
  font-size: 12px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.batch-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.batch-header-clickable {
  cursor: pointer;
  user-select: none;
  padding: 4px 6px;
  margin-left: -6px;
  margin-right: -6px;
  border-radius: 6px;
  transition: background-color 0.15s ease;
}

.batch-header-clickable:hover {
  background: var(--bg-primary);
}

.batch-header-clickable:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: 2px;
}

.batch-chevron {
  font-size: 14px;
  color: var(--text-tertiary);
  transition: transform 0.2s ease, color 0.2s ease;
  flex-shrink: 0;
}

.batch-chevron-open {
  transform: rotate(90deg);
  color: var(--brand-primary);
}

.section-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.section-label-row .section-label {
  margin-bottom: 0;
}

.batch-toggle-all {
  font-size: 12px;
}

.batch-files-grid {
  /* 折叠/展开动画期间让 el-row 不溢出 */
  overflow: hidden;
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

.section-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.empty-filter {
  padding: 12px 0;
}

:deep(.el-upload-dragger) {
  background-color: var(--bg-secondary);
  border: 2px dashed var(--border-default);
  border-radius: 8px;
}

:deep(.el-upload-dragger:hover) {
  border-color: var(--brand-primary);
}

:deep(.el-card) {
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
}

:deep(.el-card:hover) {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12), 0 2px 6px rgba(0, 0, 0, 0.08);
}

/* ============================
   Night Theme Overrides
   ============================ */
:root[data-theme="night"] .batch-header-clickable:hover {
  background: rgba(255, 255, 255, 0.05);
}

:root[data-theme="night"] .batch-chevron {
  color: rgba(255, 255, 255, 0.6);
}

:root[data-theme="night"] .batch-chevron-open {
  color: var(--brand-primary);
}

:root[data-theme="night"] .batch-count {
  background: rgba(255, 255, 255, 0.08);
}
</style>
