<template>
  <div class="batch-yield-tab">
    <!-- Batch selector -->
    <BatchSelectorBar
      :batches="batches"
      :selected-batch="selectedBatch"
      :loading="loading"
      :exporting="exporting"
      :has-data="!!batchData"
      @update:selectedBatch="onBatchSelect"
      @load="loadBatchData"
      @export="exportExcel"
    />

    <template v-if="batchData">
      <!-- 1. KPI Cards -->
      <KpiCards :kpi="batchData.kpi" />

      <!-- 2. Phase Summary -->
      <el-card v-if="batchData.phase_summary?.length" shadow="never" class="section-card">
        <template #header>📋 阶段汇总（明细）</template>
        <el-table :data="batchData.phase_summary" stripe size="small" :border="true">
          <el-table-column prop="phase" label="阶段" width="90" fixed />
          <el-table-column prop="file_count" label="文件数" width="70" align="center" />
          <el-table-column prop="total" label="测试总数" width="90" align="center" />
          <el-table-column prop="pass_count" label="Pass" width="80" align="center" />
          <el-table-column prop="fail_count" label="Fail" width="70" align="center">
            <template #default="{row}">
              <span :style="{ color: row.fail_count > 0 ? 'var(--color-error)' : 'var(--color-success)', fontWeight: 'bold' }">
                {{ row.fail_count }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="yield_pct" label="良率" width="90" align="center">
            <template #default="{row}">
              <el-tag size="small" :type="row.yield_pct >= 95 ? 'success' : row.yield_pct >= 90 ? 'warning' : 'danger'">
                {{ row.yield_pct }}%
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 3. Phase Detail Table -->
      <el-card shadow="never" class="section-card">
        <template #header>📊 阶段明细表</template>
        <el-table :data="batchData.phases" stripe size="small" :border="true" max-height="350">
          <el-table-column prop="phase" label="阶段" width="80" fixed />
          <el-table-column label="WAFER_ID" width="100" align="center">
            <template #default="{row}">{{ row.wafer_id || '-' }}</template>
          </el-table-column>
          <el-table-column prop="program_name" label="程序名称" width="140" show-overflow-tooltip />
          <el-table-column prop="lot_id" label="Lot ID" width="120" show-overflow-tooltip />
          <el-table-column prop="total" label="测试总数" width="90" align="center" />
          <el-table-column prop="pass_count" label="Pass" width="80" align="center" />
          <el-table-column prop="fail_count" label="Fail" width="70" align="center">
            <template #default="{row}">
              <span :style="{ color: row.fail_count > 0 ? 'var(--color-error)' : 'var(--color-success)', fontWeight: 'bold' }">
                {{ row.fail_count }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="yield_pct" label="良率" width="80" align="center">
            <template #default="{row}">
              <el-tag size="small" :type="row.yield_pct >= 95 ? 'success' : row.yield_pct >= 90 ? 'warning' : 'danger'">
                {{ row.yield_pct }}%
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="start_time" label="开始时间" width="170" show-overflow-tooltip />
          <el-table-column prop="end_time" label="结束时间" width="170" show-overflow-tooltip />
          <el-table-column prop="operator" label="操作员" width="100" show-overflow-tooltip />
          <el-table-column prop="station" label="工站" width="100" show-overflow-tooltip />
          <el-table-column prop="device_name" label="Device" width="140" show-overflow-tooltip />
          <el-table-column prop="tester_type" label="Tester" width="100" show-overflow-tooltip />
          <el-table-column prop="total_test_time" label="总测试时间" width="110" show-overflow-tooltip />
          <el-table-column prop="handler" label="Handler" width="100" show-overflow-tooltip />
        </el-table>
      </el-card>

      <!-- 4. Yield Trend Combo Chart (Bar + Line) -->
      <el-card shadow="never" class="section-card">
        <template #header>📈 良率趋势</template>
        <YieldTrendChart ref="yieldTrendChartRef" :phases="batchData.phases || []" :spc-limits="batchData.trend_data?.spc_limits" />
      </el-card>

      <!-- 5. QA Validation -->
      <el-card v-if="batchData.qa_checks?.length" shadow="never" class="section-card">
        <template #header>🔍 QA 数量校验</template>
        <el-table :data="batchData.qa_checks" stripe size="small" :border="true">
          <el-table-column prop="check" label="校验项" min-width="200" />
          <el-table-column prop="expected" label="期望" width="120" align="center" />
          <el-table-column prop="actual" label="实际" width="120" align="center" />
          <el-table-column prop="status" label="状态" width="150" align="center" />
        </el-table>
      </el-card>

      <!-- 6. Site Yield Matrix -->
      <el-card shadow="never" class="section-card">
        <template #header>🏭 各 Site 良率矩阵</template>
        <el-table :data="batchData.site_matrix" stripe size="small" :border="true" max-height="350">
          <el-table-column prop="phase" label="阶段" width="80" fixed />
          <template v-for="site in batchData.sorted_sites" :key="site">
            <el-table-column :label="`${site} 良率`" width="110" align="center">
              <template #default="{row}">
                <span :class="getYieldClass(row[`${site}_yield`])">{{ row[`${site}_yield`] }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="`${site} Pass/Total`" width="110" align="center">
              <template #default="{row}">{{ row[`${site}_ratio`] }}</template>
            </el-table-column>
          </template>
          <el-table-column label="All Site 良率" width="120" align="center" fixed="right">
            <template #default="{row}">
              <span :class="getYieldClass(row['all_yield'])">{{ row['all_yield'] }}</span>
            </template>
          </el-table-column>
          <el-table-column label="All Site Pass/Total" width="130" align="center" fixed="right">
            <template #default="{row}">{{ row['all_ratio'] }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 7. Bin Distribution + Site Yield + Bin×Site + UPH — 4 sub-sections
           consolidated under a single "📋 Bin 分布" card. Each sub-section is
           visually separated by an el-divider with a small heading. -->
      <el-card shadow="never" class="section-card">
        <template #header>📋 Bin 分布</template>

        <!-- 7.1 Bin 分布（per-phase 表格 + Bin 饼图 + Top Fail Bin 柱图） -->
        <div class="bin-selector">
          <el-select v-model="selectedPhase" placeholder="选择阶段查看Bin分布" @change="onPhaseChange" style="width: 220px">
            <el-option v-for="p in batchData.phases" :key="phaseKey(p)" :label="phaseLabel(p)" :value="phaseKey(p)" />
          </el-select>
          <span class="bin-hint">左侧表格与右侧 Bin 图随阶段切换</span>
        </div>

        <el-row :gutter="16">
          <!-- Left: per-phase bin table (2/5) -->
          <el-col :xs="24" :lg="9">
            <div class="chart-title">各阶段 Bin 明细（{{ selectedPhase || '-' }}）</div>
            <el-table
              v-if="selectedPhaseData"
              :data="selectedPhaseData.bin_info" stripe size="small" :border="true" max-height="640"
            >
              <el-table-column prop="name" label="Bin" width="80" />
              <el-table-column prop="value" label="数量" width="70" align="center" />
              <el-table-column prop="pct" label="占比" width="70" align="center" />
              <template v-for="site in batchData.sorted_sites" :key="site">
                <el-table-column :label="site" width="80" align="center">
                  <template #default="{row}">{{ row.sites?.[site] || 0 }}</template>
                </el-table-column>
              </template>
            </el-table>
            <el-empty v-else :image-size="60" description="无阶段数据" />
          </el-col>

          <!-- Right: charts (3/5) -->
          <el-col :xs="24" :lg="15">
            <div class="chart-title">阶段 Fail Bin（{{ selectedPhase || '-' }}）</div>
            <div ref="binPieRef" class="chart-container chart-sm" />
            <div class="chart-title" style="margin-top: 12px;">阶段 Top Fail Bin（{{ selectedPhase || '-' }}）</div>
            <div ref="binBarRef" class="chart-container chart-sm" />
          </el-col>
        </el-row>

        <!-- 7.2 Site 良率分布 & Yield 分析 -->
        <el-divider class="bin-card-divider">
          <span class="bin-card-section-title">🟢 Site 良率分布 &amp; Yield 分析</span>
        </el-divider>
        <SiteYieldAnalysis
          ref="siteYieldRef"
          :site-yield-data="siteYieldData"
          :overall-yield="overallYield"
        />

        <!-- 7.3 Bin × Site 交叉表 & 柱状图 -->
        <el-divider class="bin-card-divider">
          <span class="bin-card-section-title">📊 Bin &times; Site 交叉表 &amp; 柱状图</span>
        </el-divider>
        <BinSiteCrossTable
          ref="binSiteRef"
          :bin-table-data="binTableData"
          :bin-site-columns="binSiteColumns"
        />

        <!-- 7.4 UPH 效率分析 -->
        <el-divider class="bin-card-divider">
          <span class="bin-card-section-title">⚡ UPH 效率分析</span>
        </el-divider>
        <UphCard :uph-data="uphData" />
      </el-card>
    </template>

    <el-empty v-else-if="!loading" description="选择批次并加载数据" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'
import { getChartInitOpts } from '../../../utils/echarts-theme'
import { ElMessage } from 'element-plus'
import { batchApi } from '../../../api/batch'
import BatchSelectorBar from './batch/BatchSelectorBar.vue'
import KpiCards from './batch/KpiCards.vue'
import YieldTrendChart from './batch/YieldTrendChart.vue'
import SiteYieldAnalysis from './SiteYieldAnalysis.vue'
import BinSiteCrossTable from './BinSiteCrossTable.vue'
import UphCard from './UphCard.vue'

const batches = ref<any[]>([])
const selectedBatch = ref('')
const loading = ref(false)
const exporting = ref(false)
const batchData = ref<any>(null)
const selectedPhase = ref('')

// Ref to child chart components
const yieldTrendChartRef = ref<InstanceType<typeof YieldTrendChart>>()
const siteYieldRef = ref<InstanceType<typeof SiteYieldAnalysis>>()
const binSiteRef = ref<InstanceType<typeof BinSiteCrossTable>>()

// Computed props for the Site/Bin×Site/UPH sub-sections (consolidated under
// the Bin 分布 card). Pulled from the same batch payload the standalone
// BatchAnalysisCharts used to read.
const siteYieldData = computed(() => {
  const rows = batchData.value?.site_pass_data || []
  return rows.map((r: any) => ({
    Site: r.site,
    Yield: r.yield,
    Total: r.total,
    PassCount: r.pass,
  }))
})

const overallYield = computed(() => Number(batchData.value?.kpi?.overall_yield) || 0)

const binTableData = computed(() => batchData.value?.bin_table_data || [])
const binSiteColumns = computed(() => batchData.value?.bin_site_columns || [])
const uphData = computed(() => batchData.value?.uph || null)

// Chart refs for phase-scoped Bin analysis (remain inline)
const binPieRef = ref<HTMLElement>()
const binBarRef = ref<HTMLElement>()
let binPieChart: echarts.ECharts | null = null
let binBarChart: echarts.ECharts | null = null

const selectedPhaseData = computed(() => {
  if (!batchData.value || !selectedPhase.value) return null
  return batchData.value.phases.find((p: any) => phaseKey(p) === selectedPhase.value) || null
})

function phaseKey(p: any): string {
  return p.wafer_id ? `${p.phase}-W${p.wafer_id}` : p.phase
}

function phaseLabel(p: any): string {
  return p.wafer_id ? `${p.phase}-W${p.wafer_id}` : p.phase
}

function onBatchSelect(val: string) {
  selectedBatch.value = val
  onBatchChange()
}

function onBatchChange() {
  // Dispose old chart instances before removing DOM (v-if="batchData")
  binPieChart?.dispose(); binPieChart = null
  binBarChart?.dispose(); binBarChart = null
  batchData.value = null
  selectedPhase.value = ''
}

function onPhaseChange() {
  nextTick(() => {
    renderBinPieChart()
    renderBinBarChart()
  })
}

function getYieldClass(val: string): string {
  if (!val || val === 'N/A') return ''
  const v = parseFloat(val)
  if (v >= 95) return 'yield-good'
  if (v >= 90) return 'yield-warn'
  return 'yield-bad'
}

async function loadBatches() {
  try {
    const { data } = await batchApi.listBatches()
    batches.value = data.batches || []
  } catch { /* ignore */ }
}

async function loadBatchData() {
  if (!selectedBatch.value) return
  loading.value = true
  try {
    const { data } = await batchApi.getBatchYieldData(selectedBatch.value)
    batchData.value = data
    if (data.phases?.length > 0) {
      selectedPhase.value = phaseKey(data.phases[0])
    }
    // Double nextTick + rAF: wait for v-if DOM mount + layout settle
    nextTick(() => {
      requestAnimationFrame(() => renderInlineCharts())
    })
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '加载失败')
  } finally {
    loading.value = false
  }
}

function renderInlineCharts() {
  if (selectedPhaseData.value) {
    renderBinPieChart()
    renderBinBarChart()
  }
}

// Per-phase Bin pie chart (fail bins only)
function renderBinPieChart() {
  if (!binPieRef.value || !selectedPhaseData.value?.bin_info) return
  if (!binPieChart) binPieChart = echarts.init(binPieRef.value, undefined, getChartInitOpts())
  else binPieChart.clear()

  const failBins = selectedPhaseData.value.bin_info.filter(
    (b: any) => b.value > 0 && b.name !== '1' && !b.name.toLowerCase().includes('pass')
  )
  if (failBins.length === 0) return

  const colors = ['#f5576c', '#f9a825', '#4facfe', '#ff6b6b', '#74b9ff', '#fd79a8', '#e17055', '#00b894']
  binPieChart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', left: 'left', top: 'center', type: 'scroll', textStyle: { color: 'var(--text-primary)' } },
    series: [{
      type: 'pie',
      radius: ['35%', '65%'],
      center: ['60%', '50%'],
      data: failBins,
      color: colors,
      label: { formatter: '{b}\n{d}%', color: 'var(--text-primary)' },
      itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
    }],
  })
}

// Per-phase Bin horizontal bar chart (top 10 fail bins)
function renderBinBarChart() {
  if (!binBarRef.value || !selectedPhaseData.value?.bin_info) return
  if (!binBarChart) binBarChart = echarts.init(binBarRef.value, undefined, getChartInitOpts())
  else binBarChart.clear()

  const failBins = selectedPhaseData.value.bin_info
    .filter((b: any) => b.value > 0 && b.name !== '1' && !b.name.toLowerCase().includes('pass'))
    .sort((a: any, b: any) => b.value - a.value)
    .slice(0, 10)

  if (failBins.length === 0) return

  binBarChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '8%', bottom: '3%', top: '3%', containLabel: true },
    xAxis: { type: 'value' },
    yAxis: {
      type: 'category',
      data: failBins.map((b: any) => b.name).reverse(),
      axisLabel: { color: 'var(--text-primary)', fontSize: 11 },
    },
    series: [{
      type: 'bar',
      data: failBins.map((b: any) => b.value).reverse(),
      itemStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
          colorStops: [{ offset: 0, color: '#f093fb' }, { offset: 1, color: '#f5576c' }],
        },
      },
      label: { show: true, position: 'right', fontSize: 10, color: 'var(--text-primary)' },
    }],
  })
}

async function exportExcel() {
  if (!batchData.value) return
  exporting.value = true
  try {
    // Get file IDs from the batch
    await batchApi.generateReport(
      batchData.value.phases.map((_: any, i: number) => i) // placeholder
    )
    ElMessage.info('导出功能开发中')
  } finally {
    exporting.value = false
  }
}

function handleResize() {
  yieldTrendChartRef.value?.handleResize()
  siteYieldRef.value?.handleResize()
  binSiteRef.value?.handleResize()
  if (binPieChart && !binPieChart.isDisposed()) binPieChart.resize()
  if (binBarChart && !binBarChart.isDisposed()) binBarChart.resize()
}

onMounted(() => {
  loadBatches()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  binPieChart?.dispose(); binPieChart = null
  binBarChart?.dispose(); binBarChart = null
})

defineExpose({ handleResize })
</script>

<style scoped>
.batch-yield-tab {
  padding: 0;
}

.section-card {
  margin-bottom: 16px;
  border-radius: 8px;
}

.chart-container {
  height: 320px;
}

.chart-sm {
  height: 280px;
}

.chart-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
  text-align: center;
}

.bin-selector {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.bin-hint {
  font-size: 12px;
  color: var(--text-secondary);
}

.bin-card-divider {
  margin: 24px 0 16px;
}

.bin-card-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: 0.3px;
}

.yield-good { color: var(--color-success); font-weight: 600; }
.yield-warn { color: var(--color-warning); font-weight: 600; }
.yield-bad { color: var(--color-error); font-weight: 600; }

:deep(.el-card) {
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
}

:deep(.el-card__header) {
  background-color: var(--bg-tertiary);
  border-bottom: 1px solid var(--border-default);
  color: var(--text-primary);
  font-weight: 600;
  padding: 10px 16px;
}

:deep(.el-table) {
  --el-table-bg-color: var(--bg-secondary);
  --el-table-tr-bg-color: var(--bg-secondary);
  --el-table-header-bg-color: var(--bg-tertiary);
  --el-table-border-color: var(--border-default);
  --el-table-text-color: var(--text-primary);
  --el-table-header-text-color: var(--text-primary);
}

:deep(.el-table__body tr:hover > td) {
  background-color: var(--bg-tertiary) !important;
}
</style>
