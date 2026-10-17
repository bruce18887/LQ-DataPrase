<template>
  <div class="data-mgmt">
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
          <span v-if="tab.key === 'batch' && batchTotal" class="tab-badge">{{ batchTotal }}</span>
        </button>
      </div>
    </div>

    <!-- Content -->
    <div class="tab-content">
      <!-- 文件列表（单文件：上传、表头筛选、组合批次） -->
      <div v-show="activeTab === 'files'" role="tabpanel" class="content-section fade-in">
        <FileListTab
          @view-file="viewFile"
          @row-click="onRowClick"
          @total-change="fileTotal = $event"
        />
      </div>

      <!-- 批次数据（ZIP/SFTP 导入 + 组合生成的批次） -->
      <div v-show="activeTab === 'batch'" role="tabpanel" class="content-section fade-in">
        <BatchDataTab
          :active-file-id="activeFileId ?? undefined"
          @file-selected="onFileManagerSelect"
          @total-change="batchTotal = $event"
        />
      </div>

      <!-- 查看文件数据（当前文件横幅由组件自己渲染：横幅右端要挂它的加载/导出按钮） -->
      <div v-show="activeTab === 'view'" role="tabpanel" class="content-section fade-in">
        <DataBrowserAgGrid
          v-model:file-id="activeFileId"
          :files="files"
          @file-missing="onFileMissing"
          @goto-files="activeTab = 'files'"
        />
      </div>

      <!-- 导出工具 -->
      <div v-show="activeTab === 'export'" role="tabpanel" class="content-section fade-in">
        <ActiveFileBanner v-model="activeFileId" :files="files" />
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
import { ref, onMounted, onActivated, watch } from 'vue'
import api from '../../api'
import { useFilesStore } from '../../stores/files'
import ActiveFileBanner from './components/browser/ActiveFileBanner.vue'
import FileListTab from './components/FileListTab.vue'
import BatchDataTab from './components/BatchDataTab.vue'
import DataBrowserAgGrid from './DataBrowserAgGrid.vue'
import ExportToolsTab from './ExportToolsTab.vue'
import GageSummary from './GageSummary.vue'
import BuyoffForm from './BuyoffForm.vue'
import FileCorrelationSection from './components/correlation/FileCorrelationSection.vue'

// 用于导出下拉与当前文件名解析的轻量全量列表（FileListTab 自管分页列表）
const files = ref<any[]>([])
const fileTotal = ref(0)
const batchTotal = ref(0)
const activeTab = ref('files')
const activeFileId = ref<number | null>(null)
const filesStore = useFilesStore()

const tabs = [
  { key: 'files', label: '文件列表', icon: '📋' },
  { key: 'batch', label: '批次数据', icon: '📦' },
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

function onRowClick(id: number, _filename?: string) {
  activeFileId.value = id
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
   Tabs Navigation
   ============================ */
.tabs-wrapper {
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
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
  font-size: var(--p-fs-small);
  font-weight: 500;
  color: var(--text-3);
  transition: background-color 0.2s ease, color 0.2s ease, border-color 0.2s ease;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
}

.tab-btn:hover {
  color: var(--text);
  background: var(--bg-2);
  border-radius: 8px 8px 0 0;
}

.tab-btn.active {
  color: var(--brand);
  font-weight: 600;
  border-bottom-color: var(--brand);
}

.tab-icon {
  font-size: var(--p-fs-base);
}

.tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  background: var(--brand);
  color: var(--text-inverse);
  border-radius: 9px;
  font-size: var(--p-fs-micro);
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
:root[data-theme="night"] .tab-btn:hover {
  background: rgba(255, 255, 255, 0.05);
}

:root[data-theme="night"] .tab-badge {
  background: var(--brand);
  color: var(--text-inverse);
}
</style>
