<template>
  <div class="sftp-browser">
    <!-- Header -->
    <div class="page-header">
      <div class="header-icon">
        <el-icon :size="32" color="#409EFF"><FolderOpened /></el-icon>
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
    <el-card v-if="!connected" class="connect-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <el-icon :size="18"><Connection /></el-icon>
          <span>连接配置</span>
        </div>
      </template>

      <el-form :model="conn" label-width="90px" @submit.prevent="doConnect" class="connect-form">
        <el-row :gutter="20">
          <el-col :span="8">
            <el-form-item label="主机" required>
              <el-input v-model="conn.host" placeholder="例如: 192.168.1.1" :prefix-icon="Monitor" clearable />
            </el-form-item>
          </el-col>
          <el-col :span="4">
            <el-form-item label="端口">
              <el-input-number v-model="conn.port" :min="1" :max="65535" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="用户名" required>
              <el-input v-model="conn.username" :prefix-icon="User" clearable />
            </el-form-item>
          </el-col>
          <el-col :span="6">
            <el-form-item label="密码" required>
              <el-input v-model="conn.password" type="password" show-password :prefix-icon="Lock" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item class="form-actions">
          <el-button type="primary" native-type="submit" :loading="connecting" size="large">
            <el-icon><Link /></el-icon> 连接
          </el-button>
          <el-button @click="saveCurrentConfig" :disabled="!conn.host" size="large">
            <el-icon><Star /></el-icon> 保存配置
          </el-button>
        </el-form-item>
      </el-form>

      <!-- Saved Configs -->
      <div v-if="savedConfigs.length > 0" class="saved-configs">
        <el-divider>
          <el-icon><Collection /></el-icon> 已保存配置
        </el-divider>
        <div class="config-grid">
          <el-card
            v-for="config in savedConfigs"
            :key="config.name"
            class="config-item"
            shadow="hover"
            :body-style="{ padding: '16px' }"
          >
            <div class="config-header">
              <el-icon :size="20" color="#409EFF"><OfficeBuilding /></el-icon>
              <span class="config-name">{{ config.name }}</span>
            </div>
            <div class="config-info">
              <div class="config-row">
                <el-icon :size="14"><Monitor /></el-icon>
                <span>{{ config.host }}:{{ config.port }}</span>
              </div>
              <div class="config-row">
                <el-icon :size="14"><User /></el-icon>
                <span>{{ config.username }}</span>
              </div>
            </div>
            <div class="config-actions">
              <el-button type="primary" size="small" @click="loadConfig(config)">
                <el-icon><Switch /></el-icon> 加载
              </el-button>
              <el-button type="danger" size="small" plain @click="deleteConfig(config.name)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </el-card>
        </div>
      </div>
    </el-card>

    <!-- File Browser -->
    <div v-else class="file-browser">
      <!-- Toolbar -->
      <el-card class="toolbar-card" shadow="never" :body-style="{ padding: '12px 20px' }">
        <el-row align="middle">
          <el-col :span="14">
            <div class="breadcrumb-wrap">
              <el-button size="small" circle @click="navigateToParent" class="back-btn">
                <el-icon><ArrowUp /></el-icon>
              </el-button>
              <el-breadcrumb separator="/">
                <el-breadcrumb-item @click="navigateTo('/')">
                  <el-icon><HomeFilled /></el-icon>
                </el-breadcrumb-item>
                <el-breadcrumb-item
                  v-for="(seg, i) in pathSegments"
                  :key="i"
                  @click="navigateTo(seg.path)"
                >
                  {{ seg.name }}
                </el-breadcrumb-item>
              </el-breadcrumb>
            </div>
          </el-col>
          <el-col :span="10" style="text-align: right">
            <el-input
              v-model="searchQuery"
              placeholder="搜索文件..."
              size="small"
              clearable
              style="width: 200px; margin-right: 12px"
              :prefix-icon="Search"
            />
            <el-button size="small" type="danger" plain @click="disconnect">
              <el-icon><CircleClose /></el-icon> 断开
            </el-button>
          </el-col>
        </el-row>
      </el-card>

      <!-- Batch Actions -->
      <div class="batch-bar" v-if="fileItems.length > 0">
        <el-checkbox v-model="allSelected" :indeterminate="isIndeterminate" @change="toggleSelectAll">
          全选
        </el-checkbox>
        <el-button size="small" @click="invertSelection">反选</el-button>
        <template v-if="selectedPaths.length > 0">
          <el-divider direction="vertical" />
          <el-tag type="info" size="small">已选 {{ selectedPaths.length }} 个文件</el-tag>
          <el-button size="small" type="primary" @click="batchDownload" :loading="batchDownloading">
            <el-icon><Download /></el-icon> 批量下载
          </el-button>
          <el-button size="small" type="success" @click="batchDownloadAndParse" :loading="batchParsing">
            <el-icon><DataAnalysis /></el-icon> 批量下载解析
          </el-button>
        </template>
      </div>

      <!-- Download Progress (SSE) -->
      <el-card v-if="downloading" class="download-progress-card" shadow="never">
        <div class="progress-info">
          <span class="progress-title">
            <el-icon><Download /></el-icon> 正在下载目录...
          </span>
          <span class="progress-stats">{{ dlProgress.current }}/{{ dlProgress.total }} 文件</span>
        </div>
        <el-progress :percentage="dlProgress.percent" :stroke-width="12" :format="(p: number) => `${p}%`" />
        <div class="progress-detail">
          <span>{{ dlProgress.currentFile }}</span>
          <span>{{ dlProgress.speed > 0 ? `${dlProgress.speed} MB/s` : '' }}{{ dlProgress.eta > 0 ? ` · 预计剩余 ${dlProgress.eta}s` : '' }}</span>
        </div>
      </el-card>

      <!-- File List -->
      <el-card class="file-list-card" shadow="never">
        <el-table
          :data="filteredItems"
          @row-click="handleRow"
          @sort-change="handleSortChange"
          class="file-table"
          :header-cell-style="{ background: '#f5f7fa', fontWeight: '600', fontSize: '13px' }"
        >
          <el-table-column width="40" align="center">
            <template #default="{row}">
              <el-checkbox
                v-if="!row.is_dir && isCsv(row.name)"
                v-model="row._selected"
                @click.stop
              />
            </template>
          </el-table-column>
          <el-table-column label="名称" min-width="280" column-key="name" sortable="custom" :sort-orders="['ascending', 'descending']">
            <template #default="{row}">
              <div class="file-name-cell" :class="{ 'is-dir': row.is_dir }">
                <div class="file-icon">
                  <el-icon v-if="row.is_dir" :size="22" color="#E6A23C"><Folder /></el-icon>
                  <el-icon v-else :size="22" color="#409EFF"><Document /></el-icon>
                </div>
                <div class="file-info">
                  <span class="file-name">{{ row.name }}</span>
                  <span v-if="!row.is_dir" class="file-ext">{{ getFileExt(row.name) }}</span>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="大小" width="120" align="right" column-key="size" sortable="custom" :sort-orders="['ascending', 'descending']">
            <template #default="{row}">
              <span v-if="row.is_dir" class="dir-label">文件夹</span>
              <span v-else class="file-size">{{ formatSize(row.size) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="修改时间" width="160" align="center" column-key="mtime" sortable="custom" :sort-orders="['ascending', 'descending']">
            <template #default="{row}">
              <span class="file-time">{{ row.mtime ? formatDate(row.mtime) : '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="220" align="center">
            <template #default="{row}">
              <div class="action-cell">
                <el-button-group v-if="!row.is_dir">
                  <el-button
                    v-if="isCsv(row.name)"
                    size="small"
                    @click.stop="downloadFile(row)"
                    :loading="isDownloading(`file_${row.name}`)"
                  >
                    <el-icon><Download /></el-icon> 下载
                  </el-button>
                  <el-button
                    v-if="isCsv(row.name)"
                    size="small"
                    type="primary"
                    @click.stop="downloadAndParse(row)"
                    :loading="isDownloading(`parse_${row.name}`)"
                  >
                    <el-icon><DataAnalysis /></el-icon> 解析
                  </el-button>
                  <el-tag v-if="!isCsv(row.name)" type="info" size="small" effect="plain">仅支持 CSV</el-tag>
                </el-button-group>
                <el-button-group v-else>
                  <el-button
                    size="small"
                    type="warning"
                    plain
                    @click.stop="downloadDirectory(row.name)"
                    :loading="isDownloading(`dir_${row.name}`)"
                  >
                    <el-icon><Download /></el-icon> 下载
                  </el-button>
                  <el-button size="small" type="info" plain @click.stop="navigateTo(currentPath + '/' + row.name)">
                    <el-icon><FolderOpened /></el-icon> 打开
                  </el-button>
                </el-button-group>
              </div>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="filteredItems.length === 0" description="暂无文件" :image-size="100">
          <template #image>
            <el-icon :size="60" color="#dcdfe6"><FolderOpened /></el-icon>
          </template>
        </el-empty>
      </el-card>

      <!-- Stats -->
      <div class="stats-bar">
        <el-tag type="info" effect="plain" size="small">
          <el-icon><Folder /></el-icon> {{ dirCount }} 个文件夹
        </el-tag>
        <el-tag type="info" effect="plain" size="small">
          <el-icon><Document /></el-icon> {{ fileCount }} 个文件
        </el-tag>
        <el-tag type="info" effect="plain" size="small">
          <el-icon><PieChart /></el-icon> 总计 {{ formatSize(totalSize) }}
        </el-tag>
        <el-tag effect="plain" size="small">
          共 {{ items.length }} 项
        </el-tag>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import {
  Folder, Document, FolderOpened, CircleCheck, CircleClose,
  Connection, Monitor, User, Lock, Link, Star, Collection,
  OfficeBuilding, Switch, Delete, ArrowUp, HomeFilled,
  Search, Download, DataAnalysis, PieChart,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { sftpApi } from '../../api/sftp'

interface SftpConfig {
  name: string
  host: string
  port: number
  username: string
  password: string
}

const conn = ref({ host: '', port: 22, username: '', password: '' })
const connected = ref(false)
const connecting = ref(false)
const currentPath = ref('/')
const items = ref<any[]>([])
const savedConfigs = ref<SftpConfig[]>([])
const searchQuery = ref('')
const sortBy = ref('name')
const sortOrder = ref<'asc' | 'desc'>('asc')
const batchDownloading = ref(false)
const batchParsing = ref(false)
const downloadingRows = ref<Set<string>>(new Set())

// SSE directory download progress
const downloading = ref(false)
const dlProgress = ref({ percent: 0, speed: 0, eta: 0, currentFile: '', current: 0, total: 0 })

const pathSegments = computed(() => {
  const segs = currentPath.value.split('/').filter(Boolean)
  let path = ''
  return segs.map(s => { path += '/' + s; return { name: s, path } })
})

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

onMounted(() => {
  loadSavedConfigs()
})

function loadSavedConfigs() {
  try {
    const data = localStorage.getItem('sftp_configs')
    if (data) savedConfigs.value = JSON.parse(data)
  } catch {
    savedConfigs.value = []
  }
}

function saveConfigs() {
  localStorage.setItem('sftp_configs', JSON.stringify(savedConfigs.value))
}

function saveCurrentConfig() {
  if (!conn.value.host) return
  const name = prompt('配置名称:', conn.value.host)
  if (!name) return
  const existing = savedConfigs.value.findIndex(c => c.name === name)
  const config: SftpConfig = { name, ...conn.value }
  if (existing >= 0) savedConfigs.value[existing] = config
  else savedConfigs.value.push(config)
  saveConfigs()
  ElMessage.success('配置已保存')
}

function loadConfig(config: SftpConfig) {
  conn.value = { ...config }
}

function deleteConfig(name: string) {
  savedConfigs.value = savedConfigs.value.filter(c => c.name !== name)
  saveConfigs()
  ElMessage.success('配置已删除')
}

async function doConnect() {
  connecting.value = true
  try {
    await sftpApi.connect(conn.value.host, conn.value.port, conn.value.username, conn.value.password)
    connected.value = true
    ElMessage.success('已连接')
    listFiles('/')
  } catch { ElMessage.error('连接失败') }
  finally { connecting.value = false }
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

function navigateToParent() {
  const segs = currentPath.value.split('/').filter(Boolean)
  if (segs.length === 0) return
  segs.pop()
  listFiles('/' + segs.join('/') || '/')
}

function handleRow(row: any) {
  if (row.is_dir) listFiles(currentPath.value + '/' + row.name)
}

// ------------------------------------------------------------------
// Sorting (el-table sort-change)
// ------------------------------------------------------------------

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
    const { data } = await sftpApi.downloadAndParse(currentPath.value + '/' + row.name)
    ElMessage.success(`已导入: ${row.name}`)
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
  } catch {
    ElMessage.error('批量下载解析失败')
  }
  batchParsing.value = false
}

// ------------------------------------------------------------------
// Helpers
// ------------------------------------------------------------------

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
}

function formatDate(timestamp: number): string {
  const d = new Date(timestamp * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function getFileExt(name: string): string {
  const ext = name.split('.').pop()
  return ext && ext !== name ? '.' + ext : ''
}

function isCsv(name: string): boolean {
  return name.toLowerCase().endsWith('.csv')
}

function isDownloading(key: string): boolean {
  return downloadingRows.value.has(key)
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

/* Connect Card */
.connect-card { border-radius: 8px; margin-bottom: 20px; }
.card-header { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 15px; color: var(--text-primary); }
.connect-form { padding-top: 8px; }
.form-actions { margin-top: 8px; margin-bottom: 0; }
.form-actions :deep(.el-form-item__content) { gap: 12px; }

/* Saved Configs */
.saved-configs { margin-top: 16px; }
.config-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; margin-top: 16px; }
.config-item { border-radius: 8px; transition: transform 0.3s ease, box-shadow 0.3s ease; }
.config-item:hover { transform: translateY(-2px); box-shadow: var(--shadow-lg); }
.config-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.config-name { font-weight: 600; font-size: 15px; color: var(--text-primary); }
.config-info { margin-bottom: 12px; }
.config-row { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-secondary); margin-bottom: 4px; }
.config-actions { display: flex; gap: 8px; }

/* File Browser */
.file-browser { animation: fadeIn 0.3s ease; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

.toolbar-card { border-radius: 8px; margin-bottom: 8px; }
.breadcrumb-wrap { display: flex; align-items: center; gap: 8px; }
.back-btn { margin-right: 4px; }

/* Batch Bar */
.batch-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  margin-bottom: 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
}

/* File List */
.file-list-card { border-radius: 8px; margin-bottom: 12px; }
.file-table { cursor: pointer; }

.file-name-cell { display: flex; align-items: center; gap: 10px; padding: 4px 0; }
.file-icon {
  display: flex; align-items: center; justify-content: center;
  width: 36px; height: 36px; background: var(--bg-tertiary); border-radius: 8px; flex-shrink: 0;
}
.is-dir .file-icon { background: rgba(217, 119, 6, 0.1); }
.file-info { display: flex; align-items: center; gap: 6px; min-width: 0; }
.file-name {
  font-size: 14px; color: var(--text-primary); font-weight: 500;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.is-dir .file-name { color: var(--color-warning); font-weight: 600; }
.file-ext {
  font-size: 12px; color: var(--text-secondary); background: var(--bg-tertiary);
  padding: 1px 6px; border-radius: 4px; white-space: nowrap;
}
.file-size { font-size: 13px; color: var(--text-secondary); font-family: var(--font-mono); }
.file-time { font-size: 13px; color: var(--text-tertiary); }
.dir-label {
  font-size: 12px; color: var(--color-warning);
  background: rgba(217, 119, 6, 0.1); padding: 2px 8px; border-radius: 4px;
}

/* Action Cell */
.action-cell { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.action-cell :deep(.el-button) { font-size: 12px; }
.action-cell :deep(.el-button .el-icon) { margin-right: 2px; }

/* Download Progress */
.download-progress-card {
  border-radius: 8px;
  margin-bottom: 8px;
  border-left: 4px solid var(--brand-primary);
}
.download-progress-card :deep(.el-card__body) { padding: 14px 20px; }
.progress-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.progress-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
}
.progress-stats { font-size: 13px; color: var(--text-secondary); }
.progress-detail {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}

/* Stats */
.stats-bar { display: flex; gap: 12px; justify-content: flex-end; padding: 0 4px; }

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
