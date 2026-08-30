<template>
  <div class="dashboard-page">
    <!-- 页头仅留主标题（放大）；文件选择器下沉到单文件 Tab（与批次页头同一行式） -->
    <header class="dash-header">
      <h1 class="dash-title">
        <span class="dash-title-icon" aria-hidden="true">📊</span>
        <span class="dash-title-text">数据分析仪表板</span>
      </h1>
    </header>

    <el-tabs v-model="activeTab" class="dash-tabs">
      <el-tab-pane label="📊 单文件分析" name="single">
    <!-- 文件选择行（同批次页头结构） -->
    <header class="single-head">
      <FileSelect
        v-model="selectedFileId"
        :files="files"
        placeholder="请选择数据文件"
        show-meta
        @change="onFileChange"
        :loading="filesLoading"
        clearable
        class="dash-file-select"
      />
      <span class="dash-meta">更新: {{ updateTime }}</span>
    </header>
    <!-- 空态 / 加载态 / 错误态 -->
    <el-empty v-if="!filesLoading && files.length === 0" description="暂无数据文件，请先在数据管理页面上传 ATE 数据文件" />
    <div v-else-if="filesLoading && !data" v-loading="true" element-loading-text="加载文件列表..." style="min-height:200px" />
    <div v-else-if="loading" v-loading="loading" element-loading-text="加载仪表板数据..." style="min-height:200px" />
    <el-empty v-else-if="error && !data" description="未选择数据文件或该文件暂无数据" />

    <!-- 部分错误提示 -->
    <el-alert v-if="error && data" type="warning" title="部分数据加载失败，已显示缓存内容" :closable="false" show-icon style="margin-bottom: 16px" />

    <!-- ==================== 数据态 ==================== -->
    <template v-if="data">
      <!-- 总览条（信息记录中枢，取代 KPI 大卡） -->
      <OverviewStrip
        :metrics="metrics"
        :uph="uphData"
        :program="data?.program_name || ''"
        :test-start="testStartTime"
      />

      <!-- 质量警报（单横幅，可展开明细） -->
      <AlertBanner :alerts="qualityAlerts" />

      <!-- 图表双列：Bin 构成 Pareto + Site 良率柱线组合 -->
      <div class="dash-charts">
        <div class="sec-card">
          <div class="sec-head"><h3>📋 Bin 构成</h3><span class="sec-desc">Pareto 降序 · 色即语义</span></div>
          <div class="sec-body">
            <BinDistribution :bin-pie-data="data?.bin_pie_data || []" />
          </div>
        </div>
        <SiteYieldAnalysis
          :site-yield-data="data?.site_yield_data || []"
          :overall-yield="metrics.yield_pct || 0"
        />
      </div>

      <!-- Bin x Site 交叉表（表格 / 热力图页签） -->
      <BinSiteCrossTable
        :bin-table-data="binTableData"
        :bin-site-columns="binSiteColumns"
      />

      <!-- 测试项总览（11 列表格 + CPK 比例条 + Top 10 Fail chip） -->
      <TestItemOverviewSection
        :items="testItemOverview"
        :file-id="data?.file_id || null"
      />

      <!-- UPH 效率明细（紧凑信息带，页面最底部） -->
      <UphCard :file-id="data?.file_id || null" :uph-data="uphData" />

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
import { ref, onMounted, onActivated, watch } from 'vue'
import { useFilesStore } from '../../stores/files'
import api from '../../api'
import { analysisApi } from '../../api/analysis'
import UphCard from './components/UphCard.vue'
import BatchYieldTab from './components/BatchYieldTab.vue'
import OverviewStrip from './components/OverviewStrip.vue'
import AlertBanner from './components/AlertBanner.vue'
import BinDistribution from './components/BinDistribution.vue'
import SiteYieldAnalysis from './components/SiteYieldAnalysis.vue'
import BinSiteCrossTable from './components/BinSiteCrossTable.vue'
import TestItemOverviewSection from './components/TestItemOverviewSection.vue'
import type { TestItemOverview, UphData } from '../../types'
import ExportFooter from './components/ExportFooter.vue'
import FileSelect from '../../components/common/FileSelect.vue'

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
  test_item_overview?: TestItemOverview[]
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
const binTableData = ref<any[]>([])
const binSiteColumns = ref<string[]>([])
const updateTime = ref('')
const testItemOverview = ref<TestItemOverview[]>([])
const qualityAlerts = ref<any[]>([])
// 页面级 UPH 拉取：总览条与 UPH 明细共用同一份数据（避免重复请求）
const uphData = ref<UphData | null>(null)
// 测试开始：文件元数据 metadata.start_time（列表接口不带 metadata，走详情接口，去时区后缀保留到分钟）
const testStartTime = ref('')

async function loadUph(fileId: number) {
  try {
    const resp = await analysisApi.getUph(fileId)
    uphData.value = resp.data as UphData
  } catch {
    uphData.value = null
  }
}

async function loadFileMeta(fileId: number) {
  try {
    const { data } = await api.get(`/files/${fileId}/`)
    const st = data?.metadata?.start_time
    testStartTime.value = typeof st === 'string' ? st.replace(/\s+UTC[+-]\d+.*$/, '').slice(0, 16) : ''
  } catch {
    testStartTime.value = ''
  }
}

async function loadFiles() {
  filesLoading.value = true
  try {
    const { data } = await api.get('/files/', { params: { page_size: 9999 } })
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
    uphData.value = null
    return
  }
  loading.value = true
  error.value = false
  try {
    const res = await analysisApi.getDashboard(selectedFileId.value)
    const d = res.data as DashboardData
    if (res.data.error) {
      // Partial error: render whatever data came along
      data.value = d
      // 兜底：/summary/ 缺 metrics 时保持默认值，避免模板 metrics.yield_pct 抛 TypeError
      // （fresh-seed e2e 既有崩溃，2026-08-29 todo Review 已建议修复）
      metrics.value = d.metrics || metrics.value
      binTableData.value = d.bin_table_data || []
      binSiteColumns.value = d.bin_site_columns || []
      testItemOverview.value = d.test_item_overview || []
      qualityAlerts.value = d.quality_alerts || []
      error.value = true
      return
    }
    data.value = d
    metrics.value = d.metrics || metrics.value
    binTableData.value = d.bin_table_data || []
    binSiteColumns.value = d.bin_site_columns || []
    testItemOverview.value = d.test_item_overview || []
    qualityAlerts.value = d.quality_alerts || []
    loadUph(selectedFileId.value)
    loadFileMeta(selectedFileId.value)
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
   LQ-DataPrase Dashboard — 页面篇（指南 §11.2，定稿 2026-08-30）
   ================================================================ */

/* ----- Root & Containers ----- */
.dashboard-page {
  padding: 20px 24px 28px;
  background: var(--bg);
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

/* ----- Header（主标题放大；文件选择器已下沉到单文件 Tab） ----- */
.dash-header {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  padding: 2px 0 12px;
}
.dash-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--text);
  white-space: nowrap;
}
.dash-title-icon { font-size: 21px; }

/* 单文件 Tab 页头行（同批次页头：选择器 + 更新元信息） */
.single-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 2px 0 14px;
}
.dash-file-select { width: 320px; max-width: 100%; }
.dash-meta {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-3);
  white-space: nowrap;
}

/* ================================================================
   图表双列（Bin Pareto + Site 柱线组合，<900px 堆叠）
   ================================================================ */
.dash-charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 14px;
}
@media (max-width: 900px) {
  .dash-charts { grid-template-columns: 1fr; }
}

/* Section 卡（§10.4 定稿：浅底带卡头） */
.sec-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.sec-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg-2) 60%, var(--card));
  flex-shrink: 0;
}
.sec-head h3 {
  margin: 0;
  font-size: 13.5px;
  font-weight: 700;
  color: var(--text);
}
.sec-desc {
  font-size: 11px;
  color: var(--text-3);
}
.sec-body {
  flex: 1;
  min-height: 0;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
</style>
