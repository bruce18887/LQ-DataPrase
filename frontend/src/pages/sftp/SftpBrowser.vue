<template>
  <div class="sftp-browser">
    <!-- Header -->
    <div class="page-header">
      <div class="header-icon">
        <el-icon :size="32" aria-hidden="true"><FolderOpened /></el-icon>
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
    <SftpConnectionPanel
      v-if="!connected"
      :initial="prefill"
      :last-path-hint="pendingPath"
      @connected="onConnected"
    />

    <!-- File Browser -->
    <div v-else class="file-browser">
      <!-- Toolbar -->
      <SftpToolbar
        :current-path="currentPath"
        v-model:search-query="searchQuery"
        v-model:file-type="fileType"
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

      <!-- Download Progress (SSE): 单文件 / 目录下载共用 -->
      <SftpDownloadProgress
        v-if="fileDownloading"
        mode="file"
        :progress="fileProgress"
      />
      <SftpDownloadProgress v-if="dirDownloading" mode="dir" :progress="dlProgress" />

      <!-- File List -->
      <SftpFileTable
        :items="filteredItems"
        :current-path="currentPath"
        :downloading-rows="downloadingRows"
        :loading="listLoading"
        :sort-by="sortBy"
        :sort-order="sortOrder"
        @navigate="navigateTo"
        @sort-change="handleSortChange"
        @download="downloadFile"
        @download-and-parse="downloadAndParse"
        @download-directory="downloadDirectory"
      />

      <!-- Stats：按当前类型过滤视图统计（隐藏的文件不计入） -->
      <SftpStatsBar
        :dir-count="dirCount"
        :file-count="fileCount"
        :total-size="totalSize"
        :total-count="typeFilteredItems.length"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onActivated } from 'vue'
import { FolderOpened, CircleCheck, CircleClose } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { sftpApi, type SftpLastVisit } from '../../api/sftp'
import { useFilesStore } from '../../stores/files'
import { getSftpTimeoutSec } from '../../utils/sftpTimeout'
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
/** 文件名浏览过滤：默认仅 CSV，其它文件隐藏 */
const fileType = ref<'csv' | 'all'>('csv')
/** 下载超时（秒）：用户自由设定，持久化到 UserSetting.sftp_download_timeout */
const downloadTimeout = ref(600)
const sortBy = ref('mtime')
const sortOrder = ref<'asc' | 'desc'>('desc')
// 断线续连：上次访问信息（last_visit 接口），预填连接面板并恢复路径
const prefill = ref<{ host: string; port: number; username: string } | null>(null)
const pendingPath = ref('')
const restoring = ref(false)
const batchDownloading = ref(false)
const batchParsing = ref(false)
const downloadingRows = ref<Set<string>>(new Set())
// 卡顿根因：后端 _get_connection 每次请求都新建 paramiko.Transport 完成完整 SSH
// 握手（用完即 close），socket 无法跨请求复用，故每次进目录都有握手延迟。后端连接
// 池改动过大、超出本次范围；此处仅做体感优化：请求期间显示 loading 并屏蔽重复点击，
// 避免连点叠加多次握手把卡顿放大。
const listLoading = ref(false)

// SSE 单文件下载进度（download_file_stream）
const fileDownloading = ref(false)
const fileProgress = ref({
  percent: 0, speed: 0, eta: 0, currentFile: '',
  current: 0, total: 0, bytes_done: 0, total_bytes: 0,
})

// SSE 目录下载进度（download_dir）
const dirDownloading = ref(false)
const dlProgress = ref({
  percent: 0, speed: 0, eta: 0, currentFile: '',
  current: 0, total: 0, bytes_done: 0, total_bytes: 0,
})

const fileItems = computed(() => items.value.filter(i => !i.is_dir && isCsv(i.name)))

/** 按文件类型过滤（目录始终显示）；搜索在类型视图基础上叠加 */
const typeFilteredItems = computed(() => {
  if (fileType.value === 'all') return items.value
  return items.value.filter(i => i.is_dir || isCsv(i.name))
})

const filteredItems = computed(() => {
  if (!searchQuery.value) return typeFilteredItems.value
  const q = searchQuery.value.toLowerCase()
  return typeFilteredItems.value.filter(item => item.name.toLowerCase().includes(q))
})

const dirCount = computed(() => typeFilteredItems.value.filter(i => i.is_dir).length)
const fileCount = computed(() => typeFilteredItems.value.filter(i => !i.is_dir).length)
const totalSize = computed(
  () => typeFilteredItems.value.filter(i => !i.is_dir).reduce((sum, i) => sum + (i.size || 0), 0),
)

const selectedPaths = computed(() => {
  return items.value
    .filter(i => !i.is_dir && i._selected)
    .map(i => joinPath(currentPath.value, i.name))
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

/** 拼接远程路径，避免 currentPath='/' 时产生 '//sub1' 双斜杠 */
function joinPath(dir: string, name: string): string {
  const base = dir === '/' ? '' : dir.replace(/\/+$/, '')
  return `${base}/${name}`
}

/**
 * 断线续连：进入页面时检查上次访问信息。
 * - 上次用保存配置连接（can_auto_connect）→ 服务端自动重连，直接恢复路径；
 * - 否则（手动连接/配置被删）→ 预填表单 + 路径提示，用户输密码后跳回。
 * keep-alive 缓存页面：onMounted 只在 SPA 会话首次触发，须配合 onActivated。
 * allowAuto=false（用户主动断开后）：只刷新预填信息，绝不立即自动重连。
 */
async function checkLastVisit(allowAuto = true) {
  if (connected.value || restoring.value) return
  restoring.value = true
  try {
    const { data } = await sftpApi.getLastVisit()
    const last = data as SftpLastVisit
    if (allowAuto && last.can_auto_connect) {
      try {
        await sftpApi.autoConnect()
        connected.value = true
        ElMessage.success(`已自动重连，恢复路径：${last.last_path}`)
        listFiles(last.last_path)
      } catch {
        // 配置被删/握手失败 → 降级为手动预填
        prefill.value = { host: last.host, port: last.port, username: last.username }
        pendingPath.value = last.last_path
        ElMessage.info('自动重连失败，请手动输入密码连接')
      }
    } else if (last.host) {
      prefill.value = { host: last.host, port: last.port, username: last.username }
      pendingPath.value = last.last_path
    }
  } catch {
    // 接口异常静默：不打扰首屏
  } finally {
    restoring.value = false
  }
}

onMounted(() => {
  checkLastVisit()
  loadTimeout()
})
onActivated(() => {
  checkLastVisit()
  loadTimeout()
})

/** 读取用户设置的下载超时（30-3600s，系统设置页维护），回退默认 600s */
async function loadTimeout() {
  try {
    downloadTimeout.value = await getSftpTimeoutSec()
  } catch {
    downloadTimeout.value = 600
  }
}

function onConnected() {
  connected.value = true
  listFiles(pendingPath.value || '/')
}

async function disconnect() {
  // silent：断连失败静默处理，不弹全局错误提示（保持原有行为）
  try { await sftpApi.disconnect({ silent: true }) } catch {}
  connected.value = false
  items.value = []
  currentPath.value = '/'
  // 断开后刷新预填（后端 list_files 已记录最后浏览路径）；不允许自动重连，
  // 否则用户刚点「断开」就立刻被重连回来。
  checkLastVisit(false)
}

async function listFiles(path: string) {
  if (listLoading.value) return  // 屏蔽请求未完成时的重复点击，避免叠加多次 SSH 握手
  listLoading.value = true
  try {
    const { data } = await sftpApi.listFiles(path, sortBy.value, sortOrder.value)
    currentPath.value = data.path
    items.value = (data.items || []).map((item: any) => ({ ...item, _selected: false }))
  } catch { /* 错误 toast 由 axios 拦截器统一弹出 */ }
  finally { listLoading.value = false }
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
  await singleFileDownload(row, `file_${row.name}`)
}

/** 「解析」按钮 = 下载 + 注册（后端语义同上，与下载按钮等价），复用同一 SSE 流 */
async function downloadAndParse(row: any) {
  await singleFileDownload(row, `parse_${row.name}`)
}

async function singleFileDownload(row: any, key: string) {
  downloadingRows.value.add(key)
  startFileProgress(row.name)
  try {
    await sftpApi.downloadFileStream(
      joinPath(currentPath.value, row.name),
      downloadTimeout.value,
      (d) => {
        fileProgress.value = {
          percent: d.percent, speed: d.speed, eta: d.eta,
          currentFile: d.filename, bytes_done: d.bytes_done, total_bytes: d.total_bytes,
          current: 0, total: 1,
        }
      },
      (d) => {
        fileProgress.value.percent = 100
        fileProgress.value.bytes_done = fileProgress.value.total_bytes
        ElMessage.success(`已导入: ${d.filename} (${formatSize(d.size)})`)
        filesStore.notifyFilesChanged()
        setTimeout(() => { fileDownloading.value = false }, 1000)
      },
      (msg) => {
        fileDownloading.value = false
        ElMessage.error(msg || '下载失败')
      },
    )
  } catch {
    fileDownloading.value = false
  } finally {
    downloadingRows.value.delete(key)
  }
}

function startFileProgress(filename: string) {
  fileDownloading.value = true
  fileProgress.value = {
    percent: 0, speed: 0, eta: 0, currentFile: filename,
    current: 0, total: 1, bytes_done: 0, total_bytes: 0,
  }
}

async function downloadDirectory(dirName?: string) {
  const path = dirName ? joinPath(currentPath.value, dirName) : currentPath.value
  dirDownloading.value = true
  dlProgress.value = { percent: 0, speed: 0, eta: 0, currentFile: '', current: 0, total: 0, bytes_done: 0, total_bytes: 0 }
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
          bytes_done: 0,
          total_bytes: 0,
        }
      },
      (data) => {
        dlProgress.value.percent = 100
        ElMessage.success(`目录 "${data.dir_name}" 已保存 (${data.file_count} 个文件)`)
        filesStore.notifyFilesChanged()
        setTimeout(() => { dirDownloading.value = false }, 1000)
      },
      (msg) => {
        ElMessage.error(msg || '目录下载失败')
        dirDownloading.value = false
      },
    )
  } catch {
    // downloadDirStream 走原生 fetch，其失败经 onError 回调提示（见上），
    // 此处仅兜底重置下载状态。
    dirDownloading.value = false
  }
}

async function batchDownload() {
  if (selectedPaths.value.length === 0) return
  batchDownloading.value = true
  try {
    const { data } = await sftpApi.downloadBatch(
      selectedPaths.value,
      { timeout: downloadTimeout.value * 1000 },
    )
    ElMessage.success(`已导入 ${data.count} 个文件`)
    filesStore.notifyFilesChanged()
  } catch { /* 错误 toast 由 axios 拦截器统一弹出 */ }
  finally { batchDownloading.value = false }
}

async function batchDownloadAndParse() {
  const selected = items.value.filter(i => !i.is_dir && i._selected)
  if (selected.length === 0) return

  batchParsing.value = true
  try {
    const paths = selected.map(i => joinPath(currentPath.value, i.name))
    const { data } = await sftpApi.downloadAndParseBatch(
      paths,
      { timeout: downloadTimeout.value * 1000 },
    )
    ElMessage.success(`已成功导入 ${data.files?.length || 0}/${selected.length} 个文件（批次: ${data.batch_name}）`)
    filesStore.notifyFilesChanged()
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
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
  color: var(--brand-primary);
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
