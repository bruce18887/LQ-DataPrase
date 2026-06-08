<template>
  <div class="dashboard-page">
    <!-- 页面标题 -->
    <header class="dash-header">
      <h1 class="dash-title">
        <span class="dash-title-icon" aria-hidden="true">📊</span>
        <span class="dash-title-text">数据分析仪表板</span>
      </h1>
      <p class="dash-subtitle">
        <span>文件: <b>{{ data?.filename || '未选择' }}</b></span>
        <span v-if="data?.program_name" class="dash-subtitle-sep">|</span>
        <span v-if="data?.program_name">程序: <b>{{ data.program_name }}</b></span>
        <span class="dash-subtitle-sep">|</span>
        <span>更新: {{ updateTime }}</span>
      </p>
    </header>

    <el-tabs v-model="activeTab" class="dash-tabs">
      <el-tab-pane label="📊 单文件分析" name="single">
    <!-- 文件选择器 -->
    <div class="dash-toolbar">
      <el-select
        v-model="selectedFileId"
        placeholder="请选择数据文件"
        @change="onFileChange"
        :loading="filesLoading"
        clearable
        class="dash-file-select"
      >
        <el-option v-for="f in files" :key="f.id" :label="f.filename" :value="f.id" />
      </el-select>
    </div>

    <!-- 空态 / 加载态 / 错误态 -->
    <el-empty v-if="!filesLoading && files.length === 0" description="暂无数据文件，请先在数据管理页面上传 ATE 数据文件" />
    <div v-else-if="filesLoading && !data" v-loading="true" element-loading-text="加载文件列表..." style="min-height:200px" />
    <div v-else-if="loading" v-loading="loading" element-loading-text="加载仪表板数据..." style="min-height:200px" />
    <el-empty v-else-if="error" description="未选择数据文件或该文件暂无数据" />

    <!-- ==================== 数据态 ==================== -->
    <template v-else>
      <!-- 核心指标卡片 -->
      <KpiCards :metrics="metrics" />

      <!-- 质量警报 -->
      <QualityAlerts :alerts="qualityAlerts" />

      <!-- Bin 分布 -->
      <h2 class="sec-title"><span>📋</span> Bin 分布</h2>
      <BinDistribution :bin-pie-data="data?.bin_pie_data || []" />

      <!-- Site 良率分布 & Yield 分析 -->
      <h2 class="sec-title"><span>🟢</span> Site 良率分布 &amp; Yield 分析</h2>
      <SiteYieldAnalysis
        :site-yield-data="data?.site_yield_data || []"
        :overall-yield="metrics.yield_pct || 0"
      />

      <!-- Bin x Site 交叉表 -->
      <h2 class="sec-title"><span>📊</span> Bin &times; Site 交叉表</h2>
      <BinSiteCrossTable
        :bin-table-data="binTableData"
        :bin-site-columns="binSiteColumns"
      />

      <!-- 参数质量分析 (CPK) -->
      <CpkAnalysisSection :param-stats="paramStats" />

      <!-- Fail 测试项分析 -->
      <FailTestItemsSection
        :fail-test-items="failTestItems"
        :total-fail-count="totalFailCount"
      />

      <!-- UPH 效率分析 -->
      <h2 class="sec-title"><span>⚡</span> UPH 效率分析</h2>
      <UphCard :file-id="data?.file_id || null" />

      <!-- 数据质量概览 -->
      <DataQualityOverview
        :quality="quality"
        :metrics="metrics"
        :top-fail-item="topFailItem"
        :top-fail-count="topFailCount"
        :fail-test-items-length="failTestItems.length"
      />

      <!-- 导出 -->
      <ExportFooter
        :file-id="data?.file_id || null"
        :filename="data?.filename || ''"
        :update-time="updateTime"
      />
    </template>
      </el-tab-pane>

      <el-tab-pane label="📦 批次良率" name="batch">
        <BatchYieldTab />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onActivated, watch, computed } from 'vue'
import { useFilesStore } from '../../stores/files'
import api from '../../api'
import { analysisApi } from '../../api/analysis'
import UphCard from './components/UphCard.vue'
import BatchYieldTab from './components/BatchYieldTab.vue'
import KpiCards from './components/KpiCards.vue'
import QualityAlerts from './components/QualityAlerts.vue'
import BinDistribution from './components/BinDistribution.vue'
import SiteYieldAnalysis from './components/SiteYieldAnalysis.vue'
import BinSiteCrossTable from './components/BinSiteCrossTable.vue'
import CpkAnalysisSection from './components/CpkAnalysisSection.vue'
import FailTestItemsSection from './components/FailTestItemsSection.vue'
import DataQualityOverview from './components/DataQualityOverview.vue'
import ExportFooter from './components/ExportFooter.vue'

const filesStore = useFilesStore()

interface DashboardData {
  file_id: number
  filename: string
  program_name: string
  metrics: { total_rows: number; pass_count: number; fail_count: number; yield_pct: number; format: string }
  bin_pie_data: { name: string; value: number }[]
  site_yield_data: { Site: string; Yield: string; Total: number; PassCount: number }[]
  fail_test_items: { name: string; fail_count: number; percentage: number }[]
  quality_overview: {
    numeric_items: number
    items_with_limits: number
    site_count: number
    bin_types: number
    fail_bin_count: number
  }
  bin_table_data?: any[]
  bin_site_columns?: string[]
  param_stats?: any[]
  quality_alerts?: any[]
}

const files = ref<any[]>([])
const filesLoading = ref(true)
const selectedFileId = ref<number | null>(null)
const loading = ref(false)
const error = ref(false)
const activeTab = ref('single')
const data = ref<DashboardData | null>(null)
const metrics = ref({ total_rows: 0, pass_count: 0, fail_count: 0, yield_pct: 0, format: 'N/A' })
const failTestItems = ref<{ name: string; fail_count: number; percentage: number }[]>([])
const quality = ref({ numeric_items: 0, items_with_limits: 0, site_count: 0, bin_types: 0, fail_bin_count: 0 })
const binTableData = ref<any[]>([])
const binSiteColumns = ref<string[]>([])
const updateTime = ref('')
const paramStats = ref<any[]>([])
const qualityAlerts = ref<any[]>([])

const totalFailCount = computed(() => failTestItems.value.reduce((sum, item) => sum + item.fail_count, 0))

const topFailItem = computed(() => {
  if (!failTestItems.value.length) return '无'
  const name = failTestItems.value[0].name
  return name.length > 20 ? name.slice(0, 20) + '...' : name
})

const topFailCount = computed(() => failTestItems.value[0]?.fail_count ?? 0)

async function loadFiles() {
  filesLoading.value = true
  try {
    const { data } = await api.get('/files/')
    files.value = Array.isArray(data) ? data : data.results || []
  } catch {
    files.value = []
  } finally {
    filesLoading.value = false
  }
}

async function onFileChange() {
  if (!selectedFileId.value) {
    data.value = null
    error.value = false
    return
  }
  loading.value = true
  error.value = false
  try {
    const res = await analysisApi.getDashboard(selectedFileId.value)
    if (res.data.error) { error.value = true; return }
    const d = res.data as DashboardData
    data.value = d
    metrics.value = d.metrics
    failTestItems.value = d.fail_test_items
    quality.value = { ...d.quality_overview, fail_bin_count: d.quality_overview.fail_bin_count || 0 }
    binTableData.value = d.bin_table_data || []
    binSiteColumns.value = d.bin_site_columns || []
    paramStats.value = d.param_stats || []
    qualityAlerts.value = d.quality_alerts || []
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

// Reconcile the file selection after the list (re)loads. Without this, after
// deleting the viewed file the dashboard kept rendering stale `data` (old
// filename/program) and a frozen update time, because the watcher only
// reloaded the file list. Now we drop stale data and re-pick the latest file.
async function reconcileSelection() {
  updateTime.value = new Date().toLocaleTimeString('zh-CN')
  if (files.value.length === 0) {
    selectedFileId.value = null
    data.value = null
    error.value = false
    loading.value = false
    return
  }
  if (!selectedFileId.value || !files.value.some((f) => f.id === selectedFileId.value)) {
    selectedFileId.value = files.value[0].id
    await onFileChange()
  }
}

onMounted(async () => {
  await loadFiles()
  await reconcileSelection()
})

// SFTP 导入 / 删除等外部操作后刷新文件列表并复核选择
watch(() => filesStore.filesVersion, async () => {
  await loadFiles()
  await reconcileSelection()
})
// keep-alive 页面激活时刷新文件列表并复核选择
onActivated(async () => {
  await loadFiles()
  await reconcileSelection()
})
</script>

<style scoped>
/* ================================================================
   DataPhrase Dashboard — Industrial Data Terminal
   ================================================================ */

/* ----- Root & Containers ----- */
.dashboard-page {
  padding: 28px 32px;
  background: linear-gradient(165deg, #f8f9fb 0%, #edeff2 100%);
  min-height: 100%;
}

/* ----- Tabs ----- */
.dash-tabs {
  margin-top: 8px;
}

.dash-tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}

.dash-tabs :deep(.el-tabs__item) {
  font-size: 14px;
  font-weight: 600;
}

.dash-tabs :deep(.el-tabs__content) {
  padding: 0;
}

/* ----- Header ----- */
.dash-header {
  text-align: center;
  margin-bottom: 24px;
  padding-bottom: 20px;
  border-bottom: 1px solid #e0e3e7;
}
.dash-title {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin: 0 0 6px 0;
  font-size: 26px;
  font-weight: 750;
  color: #1a1f2e;
  letter-spacing: -0.3px;
}
.dash-title-icon { font-size: 30px; }
.dash-title-text {
  background: linear-gradient(135deg, #1d4ed8 0%, #2563eb 60%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.dash-subtitle {
  margin: 0;
  font-size: 13px;
  color: #6b7280;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
.dash-subtitle-sep { color: #d1d5db; }

/* ----- Toolbar (file selector) ----- */
.dash-toolbar {
  margin-bottom: 20px;
}
.dash-file-select { width: 320px; max-width: 100%; }

/* ================================================================
   Section Title
   ================================================================ */
.sec-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 17px;
  font-weight: 700;
  color: #1f2937;
  margin: 24px 0 12px 0;
  padding-left: 10px;
  border-left: 3px solid #2563eb;
  line-height: 1;
}

/* ================================================================
   Animations
   ================================================================ */
@media (prefers-reduced-motion: no-preference) {
  .dash-title-icon { animation: kpi-pulse 2.5s ease-in-out infinite; }
}
@keyframes kpi-pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50%      { transform: scale(1.08); opacity: .85; }
}
</style>

<!-- ================================================================
     Night Theme (data-theme="night") — Midnight Studio
     Global (non-scoped) selectors to override light theme.
     Follows NIGHT_THEME_STYLE_GUIDE.md colour system.
     ================================================================ -->
<style>
:root.theme-night .dashboard-page {
  background: linear-gradient(165deg, #1a1a2e 0%, #16213e 100%);
}

/* ----- Header ----- */
:root.theme-night .dash-header {
  border-bottom-color: rgba(255,255,255,0.1);
}
:root.theme-night .dash-title {
  color: #ffffff;
}
:root.theme-night .dash-title-text {
  background: linear-gradient(135deg, #f9a825 0%, #ffd54f 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
:root.theme-night .dash-subtitle {
  color: rgba(255,255,255,0.6);
}
:root.theme-night .dash-subtitle b {
  color: rgba(255,255,255,0.9);
}
:root.theme-night .dash-subtitle-sep {
  color: rgba(255,255,255,0.15);
}

/* ----- KPI Cards (scoped inside KpiCards.vue, but needs global override for night) ----- */
:root.theme-night .kpi-card {
  background: rgba(255,255,255,0.06);
  border-color: rgba(255,255,255,0.1);
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}
:root.theme-night .kpi-card:hover {
  background: rgba(255,255,255,0.1);
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
}
:root.theme-night .kpi-card--blue  { --kpi-accent: #4facfe; }
:root.theme-night .kpi-card--green { --kpi-accent: #11998e; }
:root.theme-night .kpi-card--amber { --kpi-accent: #f9a825; }
:root.theme-night .kpi-card--slate { --kpi-accent: rgba(255,255,255,0.4); }
:root.theme-night .kpi-card--blue::before  { background: linear-gradient(90deg, #4facfe, #00f2fe); }
:root.theme-night .kpi-card--green::before { background: linear-gradient(90deg, #11998e, #38ef7d); }
:root.theme-night .kpi-card--amber::before { background: linear-gradient(90deg, #c17900, #f9a825); }
:root.theme-night .kpi-card--slate::before { background: linear-gradient(90deg, rgba(255,255,255,0.2), rgba(255,255,255,0.4)); }
:root.theme-night .kpi-label {
  color: rgba(255,255,255,0.6);
}
:root.theme-night .kpi-value {
  color: #ffffff;
}
:root.theme-night .kpi-unit {
  color: rgba(255,255,255,0.6);
}
:root.theme-night .kpi-sub {
  color: rgba(255,255,255,0.4);
}

/* ----- Section Title (gold accent per night theme) ----- */
:root.theme-night .sec-title {
  color: rgba(255,255,255,0.9);
  border-left-color: #c17900;
}

/* ----- Panel Row & Card ----- */
:root.theme-night .panel-card {
  background: rgba(255,255,255,0.05);
  border-color: rgba(255,255,255,0.1);
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}
:root.theme-night .panel-head {
  background: rgba(255,255,255,0.03);
  color: rgba(255,255,255,0.85);
  border-bottom-color: rgba(255,255,255,0.06);
}

/* ----- Summary Cards ----- */
:root.theme-night .summary-card {
  background: rgba(255,255,255,0.05);
  border-color: rgba(255,255,255,0.1);
}
:root.theme-night .summary-card:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}
:root.theme-night .summary-card p {
  color: rgba(255,255,255,0.7);
}
:root.theme-night .summary-card p b {
  color: rgba(255,255,255,0.9);
}
:root.theme-night .summary-card--blue  { border-left-color: #4facfe; }
:root.theme-night .summary-card--blue  h4 { color: #4facfe; }
:root.theme-night .summary-card--red   { border-left-color: #f5576c; }
:root.theme-night .summary-card--red   h4 { color: #f5576c; }
:root.theme-night .summary-card--green { border-left-color: #38ef7d; }
:root.theme-night .summary-card--green h4 { color: #38ef7d; }

/* ----- Fail Total ----- */
:root.theme-night .fail-total {
  background: rgba(245,87,108,0.1);
  border-top-color: rgba(245,87,108,0.2);
}

/* ----- Yield Stats ----- */
:root.theme-night .yield-stat-label {
  color: rgba(255,255,255,0.6);
}
:root.theme-night .yield-stat-value {
  color: #ffffff;
}

/* ----- Table Cell Helpers ----- */
:root.theme-night .cell-active {
  color: rgba(255,255,255,0.9);
}
:root.theme-night .cell-inactive {
  color: rgba(255,255,255,0.3);
}
:root.theme-night .cell-count {
  color: rgba(255,255,255,0.8);
}
:root.theme-night .cell-unit {
  color: rgba(255,255,255,0.4);
}
:root.theme-night .cell-spec {
  color: rgba(255,255,255,0.8);
}
:root.theme-night .cell-na {
  color: rgba(255,255,255,0.4);
}

/* ----- Footer ----- */
:root.theme-night .dash-footer-note {
  color: rgba(255,255,255,0.3);
}

/* ----- Pulse animation — gold tint for night ----- */
@media (prefers-reduced-motion: no-preference) {
  :root.theme-night .dash-title-icon {
    animation-name: kpi-pulse-night;
  }
}
@keyframes kpi-pulse-night {
  0%, 100% { transform: scale(1); opacity: 1; text-shadow: 0 0 6px rgba(249,168,37,0.3); }
  50%      { transform: scale(1.08); opacity: .85; text-shadow: 0 0 14px rgba(249,168,37,0.5); }
}
</style>
