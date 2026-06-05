<template>
  <div class="batch-yield-tab">
    <!-- Batch selector -->
    <div class="batch-selector">
      <el-select v-model="selectedBatch" placeholder="选择批次" clearable @change="onBatchChange" style="width: 300px">
        <el-option v-for="b in batches" :key="b.batch_name" :label="`${b.batch_name} (${b.count}文件)`" :value="b.batch_name" />
      </el-select>
      <el-button type="primary" @click="loadBatchData" :loading="loading" :disabled="!selectedBatch">
        🔍 加载批次报表
      </el-button>
      <el-button v-if="batchData" @click="exportExcel" :loading="exporting">
        📥 导出 Excel
      </el-button>
    </div>

    <template v-if="batchData">
      <!-- 1. KPI Cards -->
      <el-row :gutter="16" class="kpi-row">
        <el-col :span="6">
          <div class="kpi-card kpi-blue">
            <div class="kpi-label">📥 CP+FT 投入数量</div>
            <div class="kpi-value">{{ batchData.kpi.input_total?.toLocaleString() }}</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="kpi-card kpi-green">
            <div class="kpi-label">✅ 总 Pass</div>
            <div class="kpi-value">{{ batchData.kpi.pass?.toLocaleString() }}</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="kpi-card kpi-orange">
            <div class="kpi-label">📈 整体良率</div>
            <div class="kpi-value">{{ batchData.kpi.overall_yield }}%</div>
            <div class="kpi-sub">Bin1 / CP+FT投入</div>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="kpi-card kpi-purple">
            <div class="kpi-label">❌ 总 Fail</div>
            <div class="kpi-value">{{ batchData.kpi.fail?.toLocaleString() }}</div>
          </div>
        </el-col>
      </el-row>

      <!-- 2. Phase Summary + Aggregated Bin (1:1) -->
      <el-card v-if="batchData.phase_summary?.length" shadow="never" class="section-card">
        <template #header>📋 阶段总览 & Bin 分布</template>
        <el-row :gutter="16">
          <el-col :xs="24" :lg="12">
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
          </el-col>
          <el-col :xs="24" :lg="12">
            <div class="chart-title">🔴 Bin 分布（全批次汇总）</div>
            <div ref="aggBinChartRef" class="chart-container" />
          </el-col>
        </el-row>
      </el-card>

      <!-- 3. Phase Detail Table -->
      <el-card shadow="never" class="section-card">
        <template #header>📊 阶段总览</template>
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

      <!-- 3. Yield Trend Combo Chart (Bar + Line) -->
      <el-card shadow="never" class="section-card">
        <template #header>📈 良率趋势</template>
        <div ref="trendChartRef" class="chart-container" />
      </el-card>

      <!-- 4. QA Validation -->
      <el-card v-if="batchData.qa_checks?.length" shadow="never" class="section-card">
        <template #header>🔍 QA 数量校验</template>
        <el-table :data="batchData.qa_checks" stripe size="small" :border="true">
          <el-table-column prop="check" label="校验项" min-width="200" />
          <el-table-column prop="expected" label="期望" width="120" align="center" />
          <el-table-column prop="actual" label="实际" width="120" align="center" />
          <el-table-column prop="status" label="状态" width="150" align="center" />
        </el-table>
      </el-card>

      <!-- 5. Site Yield Matrix -->
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

      <!-- 6. Bin Distribution & Site Pass Rate (combined, left table + right charts) -->
      <el-card shadow="never" class="section-card">
        <template #header>📋 Bin 分布 & Site 通过率</template>
        <div class="bin-selector">
          <el-select v-model="selectedPhase" placeholder="选择阶段查看Bin分布" @change="onPhaseChange" style="width: 220px">
            <el-option v-for="p in batchData.phases" :key="phaseKey(p)" :label="phaseLabel(p)" :value="phaseKey(p)" />
          </el-select>
          <span class="bin-hint">左侧表格与「阶段 Bin」图随阶段切换，「Site 通过率/Bin 汇总」为全批次汇总</span>
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
            <el-row :gutter="12">
              <el-col :xs="24" :md="12">
                <div class="chart-title">阶段 Fail Bin（{{ selectedPhase || '-' }}）</div>
                <div ref="binPieRef" class="chart-container chart-sm" />
              </el-col>
              <el-col :xs="24" :md="12">
                <div class="chart-title">🟢 Site 通过率（{{ selectedPhase || '全批次' }}）</div>
                <div ref="siteChartRef" class="chart-container chart-sm" />
              </el-col>
            </el-row>
            <el-row :gutter="12" style="margin-top: 12px;">
              <el-col :span="24">
                <div class="chart-title">阶段 Top Fail Bin（{{ selectedPhase || '-' }}）</div>
                <div ref="binBarRef" class="chart-container chart-sm" />
              </el-col>
            </el-row>
          </el-col>
        </el-row>
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

const batches = ref<any[]>([])
const selectedBatch = ref('')
const loading = ref(false)
const exporting = ref(false)
const batchData = ref<any>(null)
const selectedPhase = ref('')

// Chart refs
const trendChartRef = ref<HTMLElement>()
const siteChartRef = ref<HTMLElement>()
const aggBinChartRef = ref<HTMLElement>()
const binPieRef = ref<HTMLElement>()
const binBarRef = ref<HTMLElement>()
let trendChart: echarts.ECharts | null = null
let siteChart: echarts.ECharts | null = null
let aggBinChart: echarts.ECharts | null = null
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

function onBatchChange() {
  // Dispose old chart instances before removing DOM (v-if="batchData")
  trendChart?.dispose(); trendChart = null
  siteChart?.dispose(); siteChart = null
  aggBinChart?.dispose(); aggBinChart = null
  binPieChart?.dispose(); binPieChart = null
  binBarChart?.dispose(); binBarChart = null
  batchData.value = null
  selectedPhase.value = ''
}

function onPhaseChange() {
  nextTick(() => {
    renderBinPieChart()
    renderBinBarChart()
    renderSiteChart()
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
      requestAnimationFrame(() => renderAllCharts())
    })
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '加载失败')
  } finally {
    loading.value = false
  }
}

function renderAllCharts() {
  renderTrendChart()
  renderSiteChart()
  renderAggBinChart()
  if (selectedPhaseData.value) {
    renderBinPieChart()
    renderBinBarChart()
  }
}

// 3. Yield Trend Combo (Bar + Line dual Y-axis)
function renderTrendChart() {
  if (!trendChartRef.value || !batchData.value?.phases?.length) return
  if (!trendChart) trendChart = echarts.init(trendChartRef.value, undefined, getChartInitOpts())
  else trendChart.clear()

  const phases = batchData.value.phases
  const spc = batchData.value.trend_data?.spc_limits || {}

  trendChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: { data: ['测试总数', 'Pass数量', '良率', 'UCL', 'CL', 'LCL'], top: 5, textStyle: { color: 'var(--text-primary)' } },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '18%', containLabel: true },
    xAxis: {
      type: 'category',
      data: phases.map((p: any) => p.phase),
      axisLine: { lineStyle: { color: 'var(--border-default)' } },
      axisLabel: { color: 'var(--text-primary)' },
    },
    yAxis: [
      {
        type: 'value',
        name: '数量',
        position: 'left',
        axisLine: { lineStyle: { color: 'var(--border-default)' } },
        axisLabel: { color: 'var(--text-primary)' },
        splitLine: { lineStyle: { color: 'var(--border-muted)' } },
      },
      {
        type: 'value',
        name: '良率(%)',
        min: 0,
        max: 100,
        position: 'right',
        axisLabel: { formatter: '{value}%', color: 'var(--text-primary)' },
        nameTextStyle: { color: 'var(--text-primary)' },
        axisLine: { lineStyle: { color: 'var(--border-default)' } },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '测试总数', type: 'bar', data: phases.map((p: any) => p.total),
        itemStyle: { color: '#4facfe' }, barWidth: '25%',
      },
      {
        name: 'Pass数量', type: 'bar', data: phases.map((p: any) => p.pass_count),
        itemStyle: { color: '#11998e' }, barWidth: '25%',
      },
      {
        name: '良率', type: 'line', yAxisIndex: 1,
        data: phases.map((p: any) => p.yield_pct),
        itemStyle: { color: '#f5576c' }, lineStyle: { width: 3 },
        symbol: 'circle', symbolSize: 8,
        label: { show: true, formatter: '{c}%', fontSize: 11, color: 'var(--text-primary)' },
      },
      ...(spc.ucl != null ? [{
        name: 'UCL', type: 'line', yAxisIndex: 1,
        data: Array(phases.length).fill(spc.ucl),
        lineStyle: { type: 'dashed' as const, color: '#f5576c' }, symbol: 'none',
      }] : []),
      ...(spc.cl != null ? [{
        name: 'CL', type: 'line', yAxisIndex: 1,
        data: Array(phases.length).fill(spc.cl),
        lineStyle: { type: 'dashed' as const, color: '#11998e' }, symbol: 'none',
      }] : []),
      ...(spc.lcl != null ? [{
        name: 'LCL', type: 'line', yAxisIndex: 1,
        data: Array(phases.length).fill(spc.lcl),
        lineStyle: { type: 'dashed' as const, color: '#f5576c' }, symbol: 'none',
      }] : []),
    ],
  })
}

// 5. Site Pass Rate bar chart — uses selected phase site data, falls back to batch-level
function renderSiteChart() {
  if (!siteChartRef.value) return

  // Prefer selected phase site data; fall back to batch-level
  let d: any[] = []
  const phase = selectedPhaseData.value
  if (phase?.site_total && phase.site_pass && Object.keys(phase.site_total).length > 0) {
    d = Object.keys(phase.site_total).map((site: string) => {
      const total = phase.site_total[site] || 0
      const pass = phase.site_pass[site] || 0
      return { site, yield: total > 0 ? Math.round(pass / total * 10000) / 100 : 0 }
    }).sort((a: any, b: any) => a.site.localeCompare(b.site))
  } else if (batchData.value?.site_pass_data?.length) {
    d = batchData.value.site_pass_data
  }
  if (!d.length) return

  if (!siteChart) siteChart = echarts.init(siteChartRef.value, undefined, getChartInitOpts())
  else siteChart.clear()

  siteChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true },
    xAxis: {
      type: 'category',
      data: d.map((s: any) => s.site),
      axisLine: { lineStyle: { color: 'var(--border-default)' } },
      axisLabel: { color: 'var(--text-primary)' },
    },
    yAxis: {
      type: 'value',
      name: 'Yield%',
      max: 100,
      axisLabel: { formatter: '{value}%', color: 'var(--text-primary)' },
      nameTextStyle: { color: 'var(--text-primary)' },
      axisLine: { lineStyle: { color: 'var(--border-default)' } },
      splitLine: { lineStyle: { color: 'var(--border-muted)' } },
    },
    series: [{
      type: 'bar',
      data: d.map((s: any) => ({
        value: s.yield,
        itemStyle: {
          color: s.yield >= 95 ? '#11998e' : s.yield >= 90 ? '#f9a825' : '#f5576c',
        },
      })),
      barWidth: '50%',
      label: { show: true, position: 'top', formatter: '{c}%', color: 'var(--text-primary)' },
    }],
  })
}

// Aggregated Bin pie chart
function renderAggBinChart() {
  if (!aggBinChartRef.value || !batchData.value?.bin_distribution?.length) return
  if (!aggBinChart) aggBinChart = echarts.init(aggBinChartRef.value, undefined, getChartInitOpts())
  else aggBinChart.clear()

  aggBinChart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', left: 'left', type: 'scroll', textStyle: { color: 'var(--text-primary)' } },
    series: [{
      type: 'pie',
      radius: ['35%', '70%'],
      center: ['60%', '50%'],
      data: batchData.value.bin_distribution,
      label: { formatter: '{b}\n{d}%', color: 'var(--text-primary)' },
    }],
  })
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
    const resp = await batchApi.generateReport(
      batchData.value.phases.map((_: any, i: number) => i) // placeholder
    )
    ElMessage.info('导出功能开发中')
  } finally {
    exporting.value = false
  }
}

function handleResize() {
  // Guard: only resize if chart is alive and its DOM is still in document
  if (trendChart && !trendChart.isDisposed()) trendChart.resize()
  if (siteChart && !siteChart.isDisposed()) siteChart.resize()
  if (aggBinChart && !aggBinChart.isDisposed()) aggBinChart.resize()
  if (binPieChart && !binPieChart.isDisposed()) binPieChart.resize()
  if (binBarChart && !binBarChart.isDisposed()) binBarChart.resize()
}

onMounted(() => {
  loadBatches()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  trendChart?.dispose(); trendChart = null
  siteChart?.dispose(); siteChart = null
  aggBinChart?.dispose(); aggBinChart = null
  binPieChart?.dispose(); binPieChart = null
  binBarChart?.dispose(); binBarChart = null
})

defineExpose({ handleResize })
</script>

<style scoped>
.batch-yield-tab {
  padding: 0;
}

.batch-selector {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}

.kpi-row {
  margin-bottom: 20px;
}

.kpi-card {
  padding: 20px 16px;
  border-radius: 10px;
  text-align: center;
  color: #fff;
}

.kpi-blue { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
.kpi-green { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }
.kpi-orange { background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }
.kpi-purple { background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }

.kpi-value {
  font-size: 28px;
  font-weight: 700;
  margin: 8px 0 4px;
}

.kpi-label {
  font-size: 13px;
  opacity: 0.9;
}

.kpi-sub {
  font-size: 11px;
  opacity: 0.7;
  margin-top: 2px;
}

.section-card {
  margin-bottom: 16px;
  border-radius: 8px;
}

.charts-row {
  margin-bottom: 16px;
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
