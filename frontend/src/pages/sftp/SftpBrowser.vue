<template>
  <div class="sftp-browser">
    <!-- Header -->
    <div class="page-header">
      <div class="header-icon">
        <el-icon :size="32" color="#409EFF" aria-hidden="true"><FolderOpened /></el-icon>
      </div>
      <div class="header-title">
        <h2>SFTP 浏览器</h2>
        <p class="header-subtitle">安全文件传输协议浏览器</p>
      </div>
      <el-tag v-if="connected" type="success" effect="dark" class="status-tag">
        <el-icon><CircleCheck /></el-icon> 已连接
      </el-tag>
      <el-tag v-else type="info" effect="dark" class="status-tag">
        <el-icon><CircleClose /></el-icon> 未连接
      </el-tag>
    </div>

    <!-- Connection Panel -->
    <SftpConnectionPanel v-if="!connected" @connected="onConnected" />

    <!-- File Browser -->
    <div v-else class="file-browser">
      <!-- Toolbar -->
      <SftpToolbar
        :current-path="currentPath"
        v-model:search-query="searchQuery"
        @navigate="navigateTo"
        @disconnect="disconnect"
      />

      <!-- Batch Actions -->
      <SftpBatchActions
        v-if="fileItems.length > 0"
        :selected-count="selectedPaths.length"
        :all-selected="allSelected"
        :is-indeterminate="isIndeterminate"
        :batch-downloading="batchDownloading"
        :batch-parsing="batchParsing"
        @select-all="toggleSelectAll"
        @invert="invertSelection"
        @batch-download="batchDownload"
        @batch-download-and-parse="batchDownloadAndParse"
      />

      <!-- Download Progress (SSE) -->
      <SftpDownloadProgress v-if="downloading" :progress="dlProgress" />

      <!-- File List -->
      <SftpFileTable
        :items="filteredItems"
        :current-path="currentPath"
        :downloading-rows="downloadingRows"
        @navigate="navigateTo"
        @sort-change="handleSortChange"
        @download="downloadFile"
        @download-and-parse="downloadAndParse"
        @download-directory="downloadDirectory"
      />

      <!-- Stats -->
      <SftpStatsBar
        :dir-count="dirCount"
        :file-count="fileCount"
        :total-size="totalSize"
        :total-count="items.length"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { FolderOpened, CircleCheck, CircleClose } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { sftpApi } from '../../api/sftp'
import { useFilesStore } from '../../stores/files'
import SftpConnectionPanel from './components/SftpConnectionPanel.vue'
import SftpToolbar from './components/SftpToolbar.vue'
import SftpBatchActions from './components/SftpBatchActions.vue'
import SftpDownloadProgress from './components/SftpDownloadProgress.vue'
import SftpFileTable from './components/SftpFileTable.vue'
import SftpStatsBar from './components/SftpStatsBar.vue'

const filesStore = useFilesStore()

const connected = ref(false)
const currentPath = ref('/')
const items = ref<any[]>([])
const searchQuery = ref('')
const sortBy = ref('name')
const sortOrder = ref<'asc' | 'desc'>('asc')
const batchDownloading = ref(false)
const batchParsing = ref(false)
const downloadingRows = ref<Set<string>>(new Set())

// SSE directory download progress
const downloading = ref(false)
const dlProgress = ref({ percent: 0, speed: 0, eta: 0, currentFile: '', current: 0, total: 0 })

const fileItems = computed(() => items.value.filter(i => !i.is_dir && isCsv(i.name)))

const filteredItems = computed(() => {
  if (!searchQuery.value) return items.value
  const q = searchQuery.value.toLowerCase()
  return items.value.filter(item => item.name.toLowerCase().includes(q))
})

const dirCount = computed(() => items.value.filter(i => i.is_dir).length)
const fileCount = computed(() => items.value.filter(i => !i.is_dir).length)
const totalSize = computed(() => items.value.filter(i => !i.is_dir).reduce((sum, i) => sum + (i.size || 0), 0))

const selectedPaths = computed(() => {
  return items.value
    .filter(i => !i.is_dir && i._selected)
    .map(i => currentPath.value + '/' + i.name)
})

const allSelected = computed({
  get: () => fileItems.value.length > 0 && fileItems.value.every(i => i._selected),
  set: () => {},
})

const isIndeterminate = computed(() => {
  const selected = fileItems.value.filter(i => i._selected).length
  return selected > 0 && selected < fileItems.value.length
})

function toggleSelectAll(val: boolean) {
  fileItems.value.forEach(i => { i._selected = val })
}

function invertSelection() {
  fileItems.value.forEach(i => { i._selected = !i._selected })
}

function isCsv(name: string): boolean {
  return name.toLowerCase().endsWith('.csv')
}

function onConnected() {
  connected.value = true
  listFiles('/')
}

async function disconnect() {
  try { await sftpApi.disconnect() } catch {}
  connected.value = false
  items.value = []
  currentPath.value = '/'
}

async function listFiles(path: string) {
  try {
    const { data } = await sftpApi.listFiles(path, sortBy.value, sortOrder.value)
    currentPath.value = data.path
    items.value = (data.items || []).map((item: any) => ({ ...item, _selected: false }))
  } catch { ElMessage.error('获取文件列表失败') }
}

function navigateTo(path: string) { listFiles(path) }

function handleSortChange({ prop, order }: { prop: string; order: string | null }) {
  sortBy.value = prop || 'name'
  sortOrder.value = order === 'descending' ? 'desc' : 'asc'
  listFiles(currentPath.value)
}

// ------------------------------------------------------------------
// Download
// ------------------------------------------------------------------

async function downloadFile(row: any) {
  const key = `file_${row.name}`
  downloadingRows.value.add(key)
  try {
    const { data } = await sftpApi.download(currentPath.value + '/' + row.name)
    ElMessage.success(`已保存: ${data.filename} (${formatSize(data.size)})`)
  } catch { ElMessage.error('下载失败') }
  finally { downloadingRows.value.delete(key) }
}

async function downloadAndParse(row: any) {
  const key = `parse_${row.name}`
  downloadingRows.value.add(key)
  try {
    await sftpApi.downloadAndParse(currentPath.value + '/' + row.name)
    ElMessage.success(`已导入: ${row.name}`)
    filesStore.notifyFilesChanged()
  } catch { ElMessage.error('下载并解析失败') }
  finally { downloadingRows.value.delete(key) }
}

async function downloadDirectory(dirName?: string) {
  const path = dirName ? currentPath.value + '/' + dirName : currentPath.value
  downloading.value = true
  dlProgress.value = { percent: 0, speed: 0, eta: 0, currentFile: '', current: 0, total: 0 }
  try {
    await sftpApi.downloadDirStream(
      path,
      false,
      (data) => {
        dlProgress.value = {
          percent: data.percent,
          speed: data.speed,
          eta: data.eta,
          currentFile: data.filename,
          current: data.current,
          total: data.total,
        }
      },
      (data) => {
        dlProgress.value.percent = 100
        ElMessage.success(`目录 "${data.dir_name}" 已保存 (${data.file_count} 个文件)`)
        filesStore.notifyFilesChanged()
        setTimeout(() => { downloading.value = false }, 1000)
      },
      (msg) => {
        ElMessage.error(msg || '目录下载失败')
        downloading.value = false
      },
    )
  } catch {
    ElMessage.error('目录下载失败')
    downloading.value = false
  }
}

async function batchDownload() {
  if (selectedPaths.value.length === 0) return
  batchDownloading.value = true
  try {
    const { data } = await sftpApi.downloadBatch(selectedPaths.value)
    ElMessage.success(`已保存 ${data.count} 个文件到 media 目录`)
  } catch { ElMessage.error('批量下载失败') }
  finally { batchDownloading.value = false }
}

async function batchDownloadAndParse() {
  const selected = items.value.filter(i => !i.is_dir && i._selected)
  if (selected.length === 0) return

  batchParsing.value = true
  try {
    const paths = selected.map(i => currentPath.value + '/' + i.name)
    const { data } = await sftpApi.downloadAndParseBatch(paths)
    ElMessage.success(`已成功导入 ${data.files?.length || 0}/${selected.length} 个文件（批次: ${data.batch_name}）`)
    filesStore.notifyFilesChanged()
  } catch {
    ElMessage.error('批量下载解析失败')
  }
  batchParsing.value = false
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
}
</script>

<style scoped>
.sftp-browser {
  padding: 8px;
}

/* Header */
.page-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
  padding: 16px 20px;
  background: var(--bg-secondary);
  border-radius: 8px;
  border: 1px solid var(--border-default);
  box-shadow: var(--shadow-sm);
}

.header-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  background: var(--bg-primary);
  border-radius: 8px;
  box-shadow: var(--shadow-sm);
}

.header-title { flex: 1; }
.header-title h2 { margin: 0; font-size: 22px; font-weight: 600; color: var(--text-primary); }
.header-subtitle { margin: 4px 0 0; font-size: 13px; color: var(--text-secondary); }
.status-tag { font-size: 13px; padding: 6px 14px; }

/* File Browser */
.file-browser { animation: fadeIn 0.3s ease; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

/* Element Plus Overrides */
:deep(.el-card) { background-color: var(--bg-secondary); border: 1px solid var(--border-default); border-radius: 8px; }
:deep(.el-table) {
  --el-table-bg-color: var(--bg-secondary);
  --el-table-tr-bg-color: var(--bg-secondary);
  --el-table-header-bg-color: var(--bg-tertiary);
  --el-table-border-color: var(--border-default);
  --el-table-text-color: var(--text-primary);
  --el-table-row-hover-bg-color: var(--bg-tertiary);
}
:deep(.el-input__wrapper) { background-color: var(--bg-primary); border-radius: 8px; box-shadow: 0 0 0 1px var(--border-default) inset; }
:deep(.el-input__wrapper:hover) { box-shadow: 0 0 0 1px var(--brand-primary) inset; }
:deep(.el-input__wrapper.is-focus) { box-shadow: 0 0 0 1px var(--brand-primary) inset; }
:deep(.el-button) { border-radius: 8px; }
:deep(.el-divider) { border-color: var(--border-default); }
:deep(.el-breadcrumb__item) { cursor: pointer; }
:deep(.el-breadcrumb__item:hover .el-breadcrumb__inner) { color: var(--brand-primary); }
:deep(.el-breadcrumb__inner) { color: var(--text-secondary); }
:deep(.el-breadcrumb__separator) { color: var(--text-tertiary); }
</style>
