<template>
  <div class="data-mgmt">
    <!-- Header -->
    <div class="page-header">
      <div class="header-accent"></div>
      <div class="header-content">
        <div class="header-left">
          <h1 class="page-title">
            <span class="title-icon">📦</span>
            <span class="title-text">数据管理</span>
          </h1>
          <p class="page-subtitle">上传、查看、导出你的测试数据文件</p>
        </div>
        <div class="header-stats">
          <div class="stat-chip">
            <span class="stat-label">文件总数</span>
            <span class="stat-value">{{ fileTotal }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Tabs -->
    <div class="tabs-wrapper">
      <div class="tabs-nav">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          role="tab"
          :aria-selected="activeTab === tab.key"
          :class="['tab-btn', { active: activeTab === tab.key }]"
          @click="activeTab = tab.key"
        >
          <span class="tab-icon">{{ tab.icon }}</span>
          <span class="tab-label">{{ tab.label }}</span>
          <span v-if="tab.key === 'files' && fileTotal" class="tab-badge">{{ fileTotal }}</span>
        </button>
      </div>
    </div>

    <!-- Content -->
    <div class="tab-content">
      <!-- 文件列表（整合上传、标签、批次管理） -->
      <div v-show="activeTab === 'files'" role="tabpanel" class="content-section fade-in">
        <FileListTab
          :active-file-id="activeFileId ?? undefined"
          @view-file="viewFile"
          @row-click="onRowClick"
          @total-change="fileTotal = $event"
          @file-selected="onFileManagerSelect"
        />
      </div>

      <!-- 查看文件数据 -->
      <div v-show="activeTab === 'view'" role="tabpanel" class="content-section fade-in">
        <div class="active-file-banner">
          <span class="banner-icon">📄</span>
          <span class="banner-label">当前文件</span>
          <FileSelect
            v-model="activeFileId"
            :files="files"
            placeholder="请选择一个文件"
            clearable
            show-meta
            aria-label="当前文件"
            class="banner-file-select"
            @update:model-value="onActiveFileSelect"
          />
        </div>
        <DataBrowserAgGrid
          :file-id="activeFileId"
          :file-name="activeFileName"
          @file-missing="onFileMissing"
          @goto-files="activeTab = 'files'"
        />
      </div>

      <!-- 导出工具 -->
      <div v-show="activeTab === 'export'" role="tabpanel" class="content-section fade-in">
        <div class="active-file-banner">
          <span class="banner-icon">📄</span>
          <span class="banner-label">当前文件</span>
          <FileSelect
            v-model="activeFileId"
            :files="files"
            placeholder="请选择一个文件"
            clearable
            show-meta
            aria-label="当前文件"
            class="banner-file-select"
            @update:model-value="onActiveFileSelect"
          />
        </div>
        <ExportToolsTab :files="files" :file-id="activeFileId" />
      </div>

      <!-- 文件对比 -->
      <div v-show="activeTab === 'compare'" role="tabpanel" class="content-section fade-in">
        <!-- active 控制重型结果表格的挂载：切走即卸载 DOM，避免切 tab 卡顿 -->
        <FileCorrelationSection :files="files" :active="activeTab === 'compare'" />
      </div>

      <!-- Gage Summary -->
      <div v-show="activeTab === 'gage'" role="tabpanel" class="content-section fade-in">
        <GageSummary :files="files" />
      </div>

      <!-- Buyoff Form -->
      <div v-show="activeTab === 'buyoff'" role="tabpanel" class="content-section fade-in">
        <BuyoffForm :files="files" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onActivated, watch } from 'vue'
import api from '../../api'
import { useFilesStore } from '../../stores/files'
import FileSelect from '../../components/common/FileSelect.vue'
import FileListTab from './components/FileListTab.vue'
import DataBrowserAgGrid from './DataBrowserAgGrid.vue'
import ExportToolsTab from './ExportToolsTab.vue'
import GageSummary from './GageSummary.vue'
import BuyoffForm from './BuyoffForm.vue'
import FileCorrelationSection from './components/correlation/FileCorrelationSection.vue'

// 用于导出下拉与当前文件名解析的轻量全量列表（FileListTab 自管分页列表）
const files = ref<any[]>([])
const fileTotal = ref(0)
const activeTab = ref('files')
const activeFileId = ref<number | null>(null)
const filesStore = useFilesStore()

const tabs = [
  { key: 'files', label: '文件列表', icon: '📋' },
  { key: 'view', label: '查看数据', icon: '🔍' },
  { key: 'export', label: '导出工具', icon: '📥' },
  { key: 'compare', label: '文件对比', icon: '📁' },
  { key: 'gage', label: 'Gage Summary', icon: '📊' },
  { key: 'buyoff', label: 'Buyoff Form', icon: '📝' },
]

async function loadFiles() {
  try {
    // 查看数据/导出工具顶部的文件下拉需能选任意文件，不能受默认分页（20 条）限制
    const { data } = await api.get('/files/', { params: { page_size: 9999 } })
    files.value = data.results || data
  } catch {
    files.value = []
  }
}

function viewFile(id: number, _filename?: string) {
  activeFileId.value = id
  activeTab.value = 'view'
}

// 当前查看文件的文件名（供导出文件名兜底解析）
const activeFileName = computed(() => {
  const f = files.value.find((f: any) => f.id === activeFileId.value)
  return f?.filename ?? undefined
})

function onRowClick(id: number, _filename?: string) {
  activeFileId.value = id
}

// 查看数据 / 导出工具 顶部下拉框选择文件（FileSelect 单选 emit 类型为
// number | number[] | null，实际单选只会是 number|null）
function onActiveFileSelect(id: number | number[] | null | undefined) {
  activeFileId.value = typeof id === 'number' ? id : null
}

function onFileManagerSelect(fileId: number) {
  activeFileId.value = fileId
  activeTab.value = 'view'
  loadFiles()
}

// 当前查看的文件被删除时（DataBrowserAgGrid 收到后端 404）重置选择，
// 避免「查看数据 / 导出」页残留已删除文件的状态。
function onFileMissing() {
  activeFileId.value = null
}

onMounted(loadFiles)

// SFTP 导入等外部操作后自动刷新文件列表
watch(() => filesStore.filesVersion, () => { loadFiles() })

// keep-alive 页面激活时刷新文件列表
onActivated(loadFiles)
</script>

<style scoped>
/* ============================
   Page Container
   ============================ */
.data-mgmt {
  padding: 0 0 24px 0;
  min-height: 100%;
}

/* ============================
   Header
   ============================ */
.page-header {
  position: relative;
  padding: 28px 32px 20px;
  background: var(--bg-primary);
  margin-bottom: 0;
}

.header-accent {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(
    90deg,
    var(--brand-primary) 0%,
    var(--color-info) 50%,
    var(--brand-secondary) 100%
  );
}

.header-content {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 4px 0;
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.title-icon {
  font-size: 24px;
}

.title-text {
  background: linear-gradient(135deg, var(--brand-primary), var(--color-info));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.page-subtitle {
  margin: 0;
  font-size: 13px;
  color: var(--text-tertiary);
  font-weight: 400;
}

.header-stats {
  display: flex;
  gap: 12px;
}

.stat-chip {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-radius: 10px;
  min-width: 80px;
}

.stat-label {
  font-size: 11px;
  color: var(--text-tertiary);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--brand-primary);
  line-height: 1.2;
}

/* ============================
   Tabs Navigation
   ============================ */
.tabs-wrapper {
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border-muted);
  padding: 0 32px;
}

.tabs-nav {
  display: flex;
  gap: 2px;
}

.tab-btn {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px 18px;
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-tertiary);
  transition: background-color 0.2s ease, color 0.2s ease, border-color 0.2s ease;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}

.tab-btn:hover {
  color: var(--text-primary);
  background: var(--bg-secondary);
  border-radius: 8px 8px 0 0;
}

.tab-btn.active {
  color: var(--brand-primary);
  font-weight: 600;
  border-bottom-color: var(--brand-primary);
}

.tab-icon {
  font-size: 15px;
}

.tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  background: var(--brand-primary);
  color: var(--text-inverse);
  border-radius: 9px;
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
}

/* ============================
   Tab Content
   ============================ */
.tab-content {
  padding: 20px 32px 0;
}

.content-section {
  min-height: 400px;
}

/* Active file banner */
.active-file-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  margin-bottom: 16px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-left: 3px solid var(--brand-primary);
  border-radius: 8px;
  font-size: 13px;
}

.banner-icon {
  font-size: 15px;
  flex-shrink: 0;
}

.banner-label {
  color: var(--text-tertiary);
  font-weight: 500;
  white-space: nowrap;
}

.banner-file-select {
  width: 320px;
  max-width: 100%;
}

/* Fade-in animation */
.fade-in {
  animation: fadeIn 0.25s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ============================
   Night Theme Overrides
   ============================ */
:root[data-theme="night"] .page-header {
  background: var(--bg-secondary);
}

:root[data-theme="night"] .stat-chip {
  background: rgba(255, 255, 255, 0.05);
  border-color: rgba(255, 255, 255, 0.08);
}

:root[data-theme="night"] .stat-value {
  color: var(--brand-primary);
}

:root[data-theme="night"] .tab-btn:hover {
  background: rgba(255, 255, 255, 0.05);
}

:root[data-theme="night"] .tab-badge {
  background: var(--brand-primary);
  color: var(--text-inverse);
}

:root[data-theme="night"] .active-file-banner {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.08);
}
</style>
