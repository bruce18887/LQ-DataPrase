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

      <!-- 查看文件数据（多标签：一个标签一份独立表格实例，各自的筛选/固定列/滚动位置互不影响） -->
      <div v-show="activeTab === 'view'" role="tabpanel" class="content-section fade-in">
        <ViewFileTabs
          :tabs="viewTabsWithLabel"
          :active-id="activeViewTabId"
          :max="VIEW_TAB_MAX"
          @activate="activateViewTab"
          @close="closeViewTab"
          @add="addViewTab"
        />
        <!-- everActive 门控挂载：没被点开过的标签**一个请求都不发**（v-if 挡在组件之前）；
             每份挂起来的实例 = 一次 /summary/（由 DataQualityBar 发）+ 它自己的 ag-grid 块请求。
             账号设置在 Task 6b 后走 stores/userSettings，全文档只由路由守卫拉一次，与标签数无关。
             ⇒ 标签开满时 /summary/ 的上限是 VIEW_TAB_MAX(=4) 发。这是**上限口径、不是实测**：
             本轮没数过单次导航的 /summary/ 条数，也没有守卫钉它
             （在册：docs/tasks/todo.md「整改后遗留清单」的「/summary/ 请求数无守卫」那条）。
             v-show 切换保住各实例的滚动位置 -->
        <template v-for="t in viewTabs" :key="t.id">
          <DataBrowserAgGrid
            v-if="t.everActive"
            v-show="t.id === activeViewTabId"
            :file-id="t.fileId"
            :files="files"
            :active="activeTab === 'view' && t.id === activeViewTabId"
            @update:file-id="t.fileId = $event"
            @file-missing="onFileMissing(t)"
            @goto-files="activeTab = 'files'"
          />
        </template>
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
import { ref, computed, onActivated, watch } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'
import { useFilesStore } from '../../stores/files'
import ActiveFileBanner from './components/browser/ActiveFileBanner.vue'
import ViewFileTabs, { type ViewFileTab } from './components/browser/ViewFileTabs.vue'
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
const filesStore = useFilesStore()

// ── 查看数据的多文件标签页 ──
// 上限 4：每份表格实例是一个 ag-grid（IRM 驻留上限按列数动态：窄文件仍是 20 块，
// 宽文件由 blockCap.maxBlocksInCache 压低，× blockSize）
// + 一次 /summary/（DataQualityBar）。账号设置自 Task 6b 起不再是每实例一发 ——
// 全文档只有路由守卫那一次 GET（stores/userSettings），与标签数无关。
// 再往上加收益递减、内存与请求数线性涨。
const VIEW_TAB_MAX = 4
let viewTabSeq = 0
function newViewTab(fileId: number | null): ViewFileTab {
  return { id: ++viewTabSeq, fileId, label: '', everActive: true }
}
const viewTabs = ref<ViewFileTab[]>([newViewTab(null)])
const activeViewTabId = ref(viewTabs.value[0].id)

const viewTabsWithLabel = computed(() =>
  viewTabs.value.map((t) => ({
    ...t,
    label: t.fileId === null ? '' : (files.value.find((f) => f.id === t.fileId)?.filename ?? ''),
  })),
)

/**
 * 「当前文件」= 活动标签页的文件。
 *
 * 保留 get/set 双向是因为有三条既有通路把它当可写状态用：文件列表点行（预览）、
 * 导出工具横幅选文件、批次数据里选文件 —— 它们都应当改的是**当前那个标签**，
 * 而不是新开一个。改成 computed 写入即让这些通路一行都不用动。
 */
const activeFileId = computed<number | null>({
  get: () => viewTabs.value.find((t) => t.id === activeViewTabId.value)?.fileId ?? null,
  set: (v) => {
    const t = viewTabs.value.find((x) => x.id === activeViewTabId.value)
    if (t) t.fileId = v
  },
})

function activateViewTab(id: number) {
  const t = viewTabs.value.find((x) => x.id === id)
  if (!t) return
  t.everActive = true
  activeViewTabId.value = id
}

function addViewTab() {
  if (viewTabs.value.length >= VIEW_TAB_MAX) return
  const t = newViewTab(null)
  viewTabs.value.push(t)
  activeViewTabId.value = t.id
}

function closeViewTab(id: number) {
  if (viewTabs.value.length <= 1) return
  const idx = viewTabs.value.findIndex((t) => t.id === id)
  if (idx < 0) return
  const wasActive = activeViewTabId.value === id
  viewTabs.value.splice(idx, 1)
  if (wasActive) {
    // 优先落在右边邻居（像浏览器关标签），关的是最后一个则回落一格
    activateViewTab(viewTabs.value[Math.min(idx, viewTabs.value.length - 1)].id)
  }
}

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

/**
 * 「查看」按钮：该文件已在某个标签页里就激活它，否则占一个空白标签或新开一个。
 * 空白标签优先就地填入 —— 刚点过「+」的人要的就是「在这儿打开」，不该留一个空坑。
 */
function viewFile(id: number, _filename?: string) {
  activeTab.value = 'view'
  const existing = viewTabs.value.find((t) => t.fileId === id)
  if (existing) {
    activateViewTab(existing.id)
    return
  }
  const blank = viewTabs.value.find((t) => t.fileId === null)
  if (blank) {
    blank.fileId = id
    activateViewTab(blank.id)
    return
  }
  if (viewTabs.value.length >= VIEW_TAB_MAX) {
    ElMessage.warning(`最多同时打开 ${VIEW_TAB_MAX} 个文件，请先关闭一个标签页`)
    return
  }
  const t = newViewTab(id)
  viewTabs.value.push(t)
  activeViewTabId.value = t.id
}

// 点行 = 在**当前标签页**里预览这个文件（不新开标签，也不动导出工具的选择）
function onRowClick(id: number, _filename?: string) {
  activeFileId.value = id
}

function onFileManagerSelect(fileId: number) {
  activeFileId.value = fileId
  activeTab.value = 'view'
  loadFiles()
}

// 某个标签页正在看的文件被删除（DataBrowserAgGrid 收到后端 404）→ 只清那一个标签，
// 避免「查看数据 / 导出」页残留已删除文件的状态。
function onFileMissing(tab: ViewFileTab) {
  tab.fileId = null
}

// SFTP 导入等外部操作后自动刷新文件列表
watch(() => filesStore.filesVersion, () => { loadFiles() })

// 「进入即拉」只挂 onActivated —— 这里刻意**不写** onMounted，是承重的而不是漏的：
// `MainLayout.vue:12` 用 `<keep-alive :max="10">` 包本页，首次进入 mounted 与 activated
// **都**触发，两处各调一次 loadFiles ⇒ 一次导航发两条 `GET /files/?page_size=9999`
// （生产实测 2026-10-22：每条导航到数据管理都翻倍，正撞在渲染进程最忙的那几百毫秒上）。
// activated 在 mounted 之后的同一帧 post-flush 里跑，首屏不因此多等一个 tick。
// 判据：`e2e/data/data.spec.ts`「进数据管理页只发一次全量文件列表」（放 data 档是因为
// `affected-rules.mjs:35` 把 `pages/data/` 只映射到 data+exports，换档就抓不到本改）。
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
