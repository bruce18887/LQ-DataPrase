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

    <!-- 连接配置 -->
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
              <el-input
                v-model="conn.host"
                placeholder="例如: 192.168.1.1"
                :prefix-icon="Monitor"
                clearable
              />
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

      <!-- 已保存配置 -->
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

    <!-- 文件浏览器 -->
    <div v-else class="file-browser">
      <!-- 工具栏 -->
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
            <el-button size="small" type="warning" @click="downloadDirectory" :loading="downloadingDir">
              <el-icon><Download /></el-icon> 下载目录
            </el-button>
            <el-button size="small" type="danger" plain @click="disconnect">
              <el-icon><CircleClose /></el-icon> 断开
            </el-button>
          </el-col>
        </el-row>
      </el-card>

      <!-- 文件列表 -->
      <el-card class="file-list-card" shadow="never">
        <el-table
          :data="filteredItems"
          @row-click="handleRow"
          class="file-table"
          :header-cell-style="{ background: '#f5f7fa', fontWeight: '600', fontSize: '13px' }"
        >
          <el-table-column label="名称" min-width="280">
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
          <el-table-column label="大小" width="120" align="right">
            <template #default="{row}">
              <span v-if="row.is_dir" class="dir-label">文件夹</span>
              <span v-else class="file-size">{{ formatSize(row.size) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="修改时间" width="160" align="center">
            <template #default="{row}">
              <span class="file-time">{{ row.mtime ? formatDate(row.mtime) : '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="权限" width="80" align="center">
            <template #default="{row}">
              <el-tag v-if="row.mode" size="small" type="info" effect="plain">{{ formatMode(row.mode) }}</el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="220" align="center">
            <template #default="{row}">
              <el-button-group v-if="!row.is_dir">
                <el-button size="small" @click.stop="downloadFile(row)">
                  <el-icon><Download /></el-icon> 下载
                </el-button>
                <el-button size="small" type="primary" @click.stop="downloadAndParse(row)">
                  <el-icon><DataAnalysis /></el-icon> 解析
                </el-button>
              </el-button-group>
              <el-button v-else size="small" type="info" plain disabled>
                <el-icon><FolderOpened /></el-icon> 文件夹
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 空状态 -->
        <el-empty v-if="filteredItems.length === 0" description="暂无文件" :image-size="100">
          <template #image>
            <el-icon :size="60" color="#dcdfe6"><FolderOpened /></el-icon>
          </template>
        </el-empty>
      </el-card>

      <!-- 统计信息 -->
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
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
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
const downloadingDir = ref(false)
const savedConfigs = ref<SftpConfig[]>([])
const searchQuery = ref('')

const pathSegments = computed(() => {
  const segs = currentPath.value.split('/').filter(Boolean)
  let path = ''
  return segs.map(s => { path += '/' + s; return { name: s, path } })
})

const filteredItems = computed(() => {
  if (!searchQuery.value) return items.value
  const q = searchQuery.value.toLowerCase()
  return items.value.filter(item => item.name.toLowerCase().includes(q))
})

const dirCount = computed(() => items.value.filter(i => i.is_dir).length)
const fileCount = computed(() => items.value.filter(i => !i.is_dir).length)
const totalSize = computed(() => items.value.filter(i => !i.is_dir).reduce((sum, i) => sum + (i.size || 0), 0))

onMounted(() => {
  loadSavedConfigs()
})

function loadSavedConfigs() {
  try {
    const data = localStorage.getItem('sftp_configs')
    if (data) {
      savedConfigs.value = JSON.parse(data)
    }
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
  const config: SftpConfig = {
    name,
    host: conn.value.host,
    port: conn.value.port,
    username: conn.value.username,
    password: conn.value.password,
  }

  if (existing >= 0) {
    savedConfigs.value[existing] = config
  } else {
    savedConfigs.value.push(config)
  }
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
    const { data } = await sftpApi.listFiles(path)
    currentPath.value = data.path
    items.value = data.items
  } catch { ElMessage.error('获取文件列表失败') }
}

function navigateTo(path: string) { listFiles(path) }

function navigateToParent() {
  const segs = currentPath.value.split('/').filter(Boolean)
  if (segs.length === 0) return
  segs.pop()
  const parentPath = '/' + segs.join('/')
  listFiles(parentPath || '/')
}

function handleRow(row: any) {
  if (row.is_dir) listFiles(currentPath.value + '/' + row.name)
}

async function downloadFile(row: any) {
  try {
    const resp = await sftpApi.download(currentPath.value + '/' + row.name)
    const url = URL.createObjectURL(resp.data)
    const a = document.createElement('a')
    a.href = url
    a.download = row.name
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('下载完成')
  } catch { ElMessage.error('下载失败') }
}

async function downloadAndParse(row: any) {
  try {
    const resp = await sftpApi.download(currentPath.value + '/' + row.name)
    const blob = resp.data as Blob
    const file = new File([blob], row.name, { type: 'text/csv' })

    const formData = new FormData()
    formData.append('file', file)

    const api = (await import('../../api')).default
    await api.post('/upload/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    ElMessage.success('文件已下载并导入到系统')
  } catch { ElMessage.error('下载并解析失败') }
}

async function downloadDirectory() {
  downloadingDir.value = true
  try {
    const files = items.value.filter(item => !item.is_dir)
    if (files.length === 0) {
      ElMessage.warning('当前目录没有文件')
      return
    }

    const zip = new (window as any).JSZip()
    const folder = zip.folder(currentPath.value.split('/').pop() || 'download')

    for (const file of files) {
      try {
        const resp = await sftpApi.download(currentPath.value + '/' + file.name)
        const blob = resp.data as Blob
        const arrayBuffer = await blob.arrayBuffer()
        folder?.file(file.name, arrayBuffer)
      } catch {
        // Skip failed files
      }
    }

    const content = await zip.generateAsync({ type: 'blob' })
    const url = URL.createObjectURL(content)
    const a = document.createElement('a')
    a.href = url
    a.download = `${currentPath.value.split('/').pop() || 'download'}.zip`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('目录已打包下载')
  } catch { ElMessage.error('目录下载失败') }
  finally { downloadingDir.value = false }
}

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

function formatMode(mode: number): string {
  const perms = ['---', '--x', '-w-', '-wx', 'r--', 'r-x', 'rw-', 'rwx']
  const owner = perms[(mode >> 6) & 7]
  const group = perms[(mode >> 3) & 7]
  const other = perms[mode & 7]
  return owner + group + other
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
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.06);
}

.header-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  background: var(--bg-primary);
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.06);
}

.header-title {
  flex: 1;
}

.header-title h2 {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
}

.header-subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}

.status-tag {
  font-size: 13px;
  padding: 6px 14px;
}

/* Connect Card */
.connect-card {
  border-radius: 8px;
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 15px;
  color: var(--text-primary);
}

.connect-form {
  padding-top: 8px;
}

.form-actions {
  margin-top: 8px;
  margin-bottom: 0;
}

.form-actions :deep(.el-form-item__content) {
  gap: 12px;
}

/* Saved Configs */
.saved-configs {
  margin-top: 16px;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
  margin-top: 16px;
}

.config-item {
  border-radius: 8px;
  transition: all 0.3s ease;
}

.config-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12), 0 2px 6px rgba(0, 0, 0, 0.08);
}

.config-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.config-name {
  font-weight: 600;
  font-size: 15px;
  color: var(--text-primary);
}

.config-info {
  margin-bottom: 12px;
}

.config-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.config-actions {
  display: flex;
  gap: 8px;
}

/* File Browser */
.file-browser {
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

.toolbar-card {
  border-radius: 8px;
  margin-bottom: 12px;
}

.breadcrumb-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.back-btn {
  margin-right: 4px;
}

.file-list-card {
  border-radius: 8px;
  margin-bottom: 12px;
}

.file-table {
  cursor: pointer;
}

.file-name-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
}

.file-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  background: var(--bg-tertiary);
  border-radius: 8px;
  flex-shrink: 0;
}

.is-dir .file-icon {
  background: rgba(217, 119, 6, 0.1);
}

.file-info {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.file-name {
  font-size: 14px;
  color: var(--text-primary);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.is-dir .file-name {
  color: var(--color-warning);
  font-weight: 600;
}

.file-ext {
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--bg-tertiary);
  padding: 1px 6px;
  border-radius: 4px;
  white-space: nowrap;
}

.file-size {
  font-size: 13px;
  color: var(--text-secondary);
  font-family: 'Courier New', monospace;
}

.file-time {
  font-size: 13px;
  color: var(--text-tertiary);
}

.dir-label {
  font-size: 12px;
  color: var(--color-warning);
  background: rgba(217, 119, 6, 0.1);
  padding: 2px 8px;
  border-radius: 4px;
}

/* Stats Bar */
.stats-bar {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  padding: 0 4px;
}

/* Element Plus Overrides */
:deep(.el-card) {
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
}

:deep(.el-table) {
  --el-table-bg-color: var(--bg-secondary);
  --el-table-tr-bg-color: var(--bg-secondary);
  --el-table-header-bg-color: var(--bg-tertiary);
  --el-table-border-color: var(--border-default);
  --el-table-text-color: var(--text-primary);
  --el-table-row-hover-bg-color: var(--bg-tertiary);
}

:deep(.el-input__wrapper) {
  background-color: var(--bg-primary);
  border-radius: 8px;
  box-shadow: 0 0 0 1px var(--border-default) inset;
}

:deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--brand-primary) inset;
}

:deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--brand-primary) inset;
}

:deep(.el-button) {
  border-radius: 8px;
}

:deep(.el-divider) {
  border-color: var(--border-default);
}

:deep(.el-breadcrumb__item) {
  cursor: pointer;
}

:deep(.el-breadcrumb__item:hover .el-breadcrumb__inner) {
  color: var(--brand-primary);
}

:deep(.el-breadcrumb__inner) {
  color: var(--text-secondary);
}

:deep(.el-breadcrumb__separator) {
  color: var(--text-tertiary);
}
</style>
