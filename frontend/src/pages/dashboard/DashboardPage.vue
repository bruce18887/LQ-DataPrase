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
      <!-- ===== 核心指标卡片 ===== -->
      <div class="kpi-row">
        <div class="kpi-card kpi-card--blue">
          <div class="kpi-icon">📋</div>
          <div class="kpi-label">总记录数</div>
          <div class="kpi-value">{{ metrics.total_rows?.toLocaleString() }}</div>
        </div>
        <div class="kpi-card kpi-card--green">
          <div class="kpi-icon">✅</div>
          <div class="kpi-label">Pass 数量</div>
          <div class="kpi-value">{{ metrics.pass_count?.toLocaleString() }}</div>
        </div>
        <div class="kpi-card kpi-card--amber">
          <div class="kpi-icon">📈</div>
          <div class="kpi-label">Yield</div>
          <div class="kpi-value">{{ metrics.yield_pct?.toFixed(2) }}<span class="kpi-unit">%</span></div>
          <div class="kpi-sub">Fail: {{ metrics.fail_count?.toLocaleString() }}</div>
        </div>
        <div class="kpi-card kpi-card--slate">
          <div class="kpi-icon">🔧</div>
          <div class="kpi-label">数据格式</div>
          <el-tag effect="dark" round size="small" type="info" class="kpi-tag">{{ metrics.format }}</el-tag>
        </div>
      </div>

      <!-- ===== 质量警报 ===== -->
      <div v-if="qualityAlerts.length" class="alerts-bar">
        <el-alert
          v-for="a in qualityAlerts"
          :key="a.type"
          :type="a.level"
          :title="a.message"
          :closable="false"
          show-icon
          class="alerts-bar-item"
        >
          <template v-if="a.params">
            <div class="alerts-detail">问题参数: {{ a.params.join(', ') }}</div>
          </template>
          <template v-if="a.max_site">
            <div class="alerts-detail">最高: {{ a.max_site }} | 最低: {{ a.min_site }}</div>
          </template>
        </el-alert>
      </div>

      <!-- ===== Section: Bin 分布 ===== -->
      <h2 class="sec-title"><span>📋</span> Bin 分布</h2>
      <div class="panel-row panel-row--h420">
        <div class="panel-card">
          <div class="panel-head">🔴 Bin 分布饼图</div>
          <div class="panel-body"><div ref="binChart" class="chart-fill" role="img" aria-label="Bin分布饼图" /></div>
        </div>
        <div class="panel-card">
          <div class="panel-head">💹 Bin 占比一览</div>
          <el-table :data="binPieTableData" stripe size="small" max-height="380" border class="panel-table">
            <el-table-column prop="name" label="Bin" min-width="90">
              <template #default="{ row }">
                <el-tag :type="row.name.includes('1') ? 'success' : 'danger'" size="small">{{ row.name }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="value" label="数量" width="80" align="right" sortable />
            <el-table-column prop="pct" label="占比" width="120" align="center">
              <template #default="{ row }">
                <el-progress :percentage="Number(row.pct)" :color="row.name.includes('1') ? '#059669' : '#dc2626'" :stroke-width="12" />
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>

      <!-- ===== Section: Site 良率分布 & Yield ===== -->
      <h2 class="sec-title"><span>🟢</span> Site 良率分布 &amp; Yield 分析</h2>
      <div class="panel-row panel-row--h320">
        <div class="panel-card">
          <div class="panel-head">📊 Site 良率柱状图</div>
          <div class="panel-body"><div ref="siteYieldBarChart" class="chart-fill" role="img" aria-label="Site良率柱状图" /></div>
        </div>
        <div class="panel-card panel-card--col">
          <div ref="yieldGaugeChart" style="height:130px" role="img" aria-label="整体Yield仪表盘" />
          <div class="yield-stats">
            <div class="yield-stat">
              <span class="yield-stat-tag" style="background:#05966920;color:#059669">{{ siteYieldStats.maxSite }}</span>
              <span class="yield-stat-label">最高</span>
              <span class="yield-stat-value">{{ siteYieldStats.max }}%</span>
            </div>
            <div class="yield-stat">
              <span class="yield-stat-tag" style="background:#dc262620;color:#dc2626">{{ siteYieldStats.minSite }}</span>
              <span class="yield-stat-label">最低</span>
              <span class="yield-stat-value">{{ siteYieldStats.min }}%</span>
            </div>
            <div class="yield-stat">
              <span class="yield-stat-tag" style="background:#6b728020;color:#6b7280">Δ</span>
              <span class="yield-stat-label">差异</span>
              <span class="yield-stat-value">{{ siteYieldStats.diff }}%</span>
            </div>
          </div>
        </div>
      </div>

      <!-- ===== Section: Bin × Site 交叉表 ===== -->
      <h2 class="sec-title"><span>📊</span> Bin &times; Site 交叉表</h2>
      <div class="panel-row panel-row--wider panel-row--h400">
        <div class="panel-card panel-card--wider">
          <div class="panel-head">📋 Bin × Site 数据</div>
          <el-table :data="formattedBinTableData" stripe size="small" max-height="360" border class="panel-table">
            <el-table-column prop="bin" label="Bin" width="80" align="center" fixed="left">
              <template #default="{ row }">
                <el-tag :type="row.bin.includes('1') ? 'success' : row.bin === 'Total' ? 'info' : 'danger'" size="small">{{ row.bin }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column v-for="col in binSiteColumns" :key="col" :prop="col" :label="`Site ${col}`" align="center" min-width="120">
              <template #default="{ row }">
                <span class="cell-count">{{ row[col] }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="all_site" label="ALL Site" align="center" min-width="140" fixed="right">
              <template #default="{ row }">
                <el-tag :type="row.bin === 'Total' ? 'info' : 'primary'" size="small" effect="plain">{{ row.all_site }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div class="panel-card">
          <div class="panel-head">📊 Bin × Site 柱状图</div>
          <div class="panel-body"><div ref="binBarChart" class="chart-fill" role="img" aria-label="Bin×Site柱状图" /></div>
        </div>
      </div>

      <!-- ===== Section: 参数质量分析 ===== -->
      <h2 v-if="paramStats.length" class="sec-title"><span>📊</span> 参数质量分析 (Top 10 CPK)</h2>
      <div v-if="paramStats.length" class="panel-row panel-row--wider panel-row--h350">
        <div class="panel-card panel-card--wider">
          <div class="panel-head">📋 CPK 参数表</div>
          <el-table :data="topParamStats" stripe size="small" max-height="310" border class="panel-table">
            <el-table-column prop="param" label="参数名称" min-width="140" show-overflow-tooltip />
            <el-table-column prop="cpk" label="CPK" width="80" align="center">
              <template #default="{ row }">
                <el-tag :type="getCpkTagType(row.cpk)" size="small">{{ row.cpk.toFixed(2) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="cpk_level" label="等级" width="90" align="center">
              <template #default="{ row }">
                <span :style="{ color: row.cpk_color, fontWeight: 'bold' }">{{ row.cpk_level }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="mean" label="均值" width="120" align="right">
              <template #default="{ row }">{{ row.mean.toFixed(4) }} <span class="cell-unit">{{ row.unit }}</span></template>
            </el-table-column>
            <el-table-column prop="std" label="标准差" width="90" align="right">
              <template #default="{ row }">{{ row.std.toFixed(4) }}</template>
            </el-table-column>
            <el-table-column label="规格限" width="180" align="center">
              <template #default="{ row }">
                <span v-if="row.lsl !== null && row.usl !== null" class="cell-spec">{{ row.lsl.toFixed(4) }} ~ {{ row.usl.toFixed(4) }}</span>
                <span v-else class="cell-na">未设置</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div class="panel-card">
          <div class="panel-head">CPK 分布统计</div>
          <div class="panel-body"><div ref="cpkDistChart" class="chart-fill" role="img" aria-label="CPK分布统计饼图" /></div>
        </div>
      </div>

      <!-- ===== Section: Fail 测试项分析 ===== -->
      <h2 class="sec-title"><span>📉</span> Fail 测试项分析</h2>
      <div class="panel-row panel-row--h320">
        <div class="panel-card">
          <div class="panel-head">📋 Fail 测试项明细</div>
          <el-table :data="failTestItems" stripe size="small" max-height="280" border class="panel-table">
            <el-table-column prop="name" label="测试项名称" show-overflow-tooltip min-width="180" />
            <el-table-column prop="fail_count" label="Fail数量" width="90" align="center" />
            <el-table-column prop="percentage" label="占比" width="80" align="center">
              <template #default="{ row }">{{ row.percentage }}%</template>
            </el-table-column>
          </el-table>
          <div class="fail-total">总 Fail 次数: <b>{{ totalFailCount }}</b></div>
        </div>
        <div class="panel-card">
          <div class="panel-head">Top 10 Fail 测试项</div>
          <div class="panel-body"><div ref="failBarChart" class="chart-fill" role="img" aria-label="Top 10 Fail测试项柱状图" /></div>
        </div>
      </div>

      <!-- ===== Section: UPH 效率分析 ===== -->
      <h2 class="sec-title"><span>⚡</span> UPH 效率分析</h2>
      <UphCard :file-id="data?.file_id || null" />

      <!-- ===== Section: 数据质量概览 ===== -->
      <h2 class="sec-title"><span>🔍</span> 数据质量概览</h2>
      <div class="summary-row">
        <div class="summary-card summary-card--blue">
          <h4>📊 测试项统计</h4>
          <p>数值测试项: <b>{{ quality.numeric_items }}</b></p>
          <p>有 Limit 测试项: <b>{{ quality.items_with_limits }}</b></p>
          <p>Site 数量: <b>{{ quality.site_count }}</b></p>
        </div>
        <div class="summary-card summary-card--red">
          <h4>🎯 Bin 分布</h4>
          <p>Bin 种类: <b>{{ quality.bin_types }}</b></p>
          <p>Fail Bin: <b>{{ quality.fail_bin_count }}</b></p>
          <p>Pass 率: <b>{{ metrics.yield_pct?.toFixed(2) }}%</b></p>
        </div>
        <div class="summary-card summary-card--green">
          <h4>⚠️ 关键问题</h4>
          <p>Top Fail 项: <b>{{ topFailItem }}</b></p>
          <p>Fail 次数: <b>{{ topFailCount }}</b></p>
          <p>总 Fail 项: <b>{{ failTestItems.length }}</b></p>
        </div>
      </div>

      <!-- 导出 -->
      <div class="dash-footer">
        <el-button type="primary" size="large" :loading="exporting" @click="exportHtml">
          <span>📥</span> 保存 HTML 报表
        </el-button>
        <p class="dash-footer-note">📅 最后更新: {{ updateTime }} | LiqunData ATE 数据分析软件</p>
      </div>
    </template>
      </el-tab-pane>

      <el-tab-pane label="📦 批次良率" name="batch">
        <BatchYieldTab />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, watch, computed } from 'vue'
import * as echarts from 'echarts'
import { getChartInitOpts } from '../../utils/echarts-theme'
import { useThemeStore } from '../../stores/theme'
import api from '../../api'
import { analysisApi } from '../../api/analysis'
import UphCard from './components/UphCard.vue'
import BatchYieldTab from './components/BatchYieldTab.vue'

// Helper for theme-aware ECharts colors
const _tc = () => getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#ffffff'
const themeStore = useThemeStore()
const _ts = () => getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim() || 'rgba(255,255,255,0.8)'

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
const exporting = ref(false)
const data = ref<DashboardData | null>(null)
const metrics = ref({ total_rows: 0, pass_count: 0, fail_count: 0, yield_pct: 0, format: 'N/A' })
const failTestItems = ref<{ name: string; fail_count: number; percentage: number }[]>([])
const quality = ref({ numeric_items: 0, items_with_limits: 0, site_count: 0, bin_types: 0, fail_bin_count: 0 })
const binTableData = ref<any[]>([])
const binSiteColumns = ref<string[]>([])
const updateTime = ref('')
const paramStats = ref<any[]>([])
const qualityAlerts = ref<any[]>([])

// Chart refs
const binChart = ref<HTMLElement>()
const yieldGaugeChart = ref<HTMLElement>()
const failBarChart = ref<HTMLElement>()
const cpkDistChart = ref<HTMLElement>()
const binBarChart = ref<HTMLElement>()
const siteYieldBarChart = ref<HTMLElement>()

// Chart instances
let binChartInstance: echarts.ECharts | null = null
let yieldGaugeChartInstance: echarts.ECharts | null = null
let failBarChartInstance: echarts.ECharts | null = null
let cpkDistChartInstance: echarts.ECharts | null = null
let binBarChartInstance: echarts.ECharts | null = null
let siteYieldBarChartInstance: echarts.ECharts | null = null

const siteYieldStats = computed(() => {
  const siteData = data.value?.site_yield_data || []
  if (!siteData.length) return { max: 0, min: 0, diff: 0, maxSite: '-', minSite: '-' }

  // 解析Yield值，处理可能的字符串格式
  const yieldsWithSites = siteData.map((d) => {
    const yieldValue = typeof d.Yield === 'string' ? parseFloat(d.Yield) : d.Yield
    return { yield: isNaN(yieldValue) ? 0 : yieldValue, site: d.Site }
  }).filter((item) => !isNaN(item.yield))

  if (!yieldsWithSites.length) return { max: 0, min: 0, diff: 0, maxSite: '-', minSite: '-' }

  const maxItem = yieldsWithSites.reduce((prev, curr) => curr.yield > prev.yield ? curr : prev)
  const minItem = yieldsWithSites.reduce((prev, curr) => curr.yield < prev.yield ? curr : prev)

  return {
    max: Math.round(maxItem.yield * 100) / 100,
    min: Math.round(minItem.yield * 100) / 100,
    diff: Math.round((maxItem.yield - minItem.yield) * 100) / 100,
    maxSite: maxItem.site,
    minSite: minItem.site
  }
})

const binPieTableData = computed(() => {
  const pieData = data.value?.bin_pie_data || []
  const total = pieData.reduce((s, item) => s + item.value, 0)
  return pieData.map(item => ({
    name: item.name,
    value: item.value,
    pct: total > 0 ? ((item.value / total) * 100).toFixed(1) : '0.0',
  }))
})

/** Bin × Site 交叉表 — 格式化为 "count (pct%)" */
const formattedBinTableData = computed(() => {
  const raw = binTableData.value
  const cols = binSiteColumns.value
  if (!raw.length || !cols.length) return raw

  // Find the "Total" row to get per-column totals
  const totalRow = raw.find(r => r.bin === 'Total')
  if (!totalRow) return raw

  return raw.map(row => {
    const formatted: Record<string, any> = { bin: row.bin, all_site: row.all_site }
    for (const col of cols) {
      const val = row[col] || 0
      const colTotal = totalRow[col] || 1
      const pct = colTotal > 0 ? ((val / colTotal) * 100).toFixed(1) : '0.0'
      formatted[col] = `${val} (${pct}%)`
    }
    // Format ALL Site relative to grand total (Total row's all_site)
    const grandTotal = totalRow.all_site || 1
    const allPct = grandTotal > 0 ? ((row.all_site / grandTotal) * 100).toFixed(1) : '0.0'
    if (row.bin === 'Total') {
      formatted.all_site = row.all_site // Total row itself keeps raw number
    } else {
      formatted.all_site = `${row.all_site || 0} (${allPct}%)`
    }
    return formatted
  })
})

const totalFailCount = computed(() => failTestItems.value.reduce((sum, item) => sum + item.fail_count, 0))

const topFailItem = computed(() => {
  if (!failTestItems.value.length) return '无'
  const name = failTestItems.value[0].name
  return name.length > 20 ? name.slice(0, 20) + '...' : name
})

const topFailCount = computed(() => failTestItems.value[0]?.fail_count ?? 0)
const topParamStats = computed(() => paramStats.value.slice(0, 10))

function getCpkTagType(cpk: number): string {
  if (cpk >= 1.67) return 'success'
  if (cpk >= 1.33) return 'warning'
  return 'danger'
}

function renderYieldGaugeChart() {
  if (!yieldGaugeChart.value) return
  if (!yieldGaugeChartInstance) {
    yieldGaugeChartInstance = echarts.init(yieldGaugeChart.value, undefined, getChartInitOpts())
  } else {
    yieldGaugeChartInstance.clear()
  }

  const yieldPct = metrics.value.yield_pct

  yieldGaugeChartInstance.setOption({
    series: [{
      type: 'gauge',
      startAngle: 180,
      endAngle: 0,
      min: 0,
      max: 100,
      splitNumber: 10,
      axisLine: {
        lineStyle: {
          width: 8,
          color: [
            [0.90, '#dc2626'],  // 0-90%: 红色
            [0.95, '#d97706'],  // 90-95%: 橙色
            [1, '#059669'],     // 95-100%: 绿色
          ],
        },
      },
      pointer: { icon: 'path://M12.8,0.7l12,40.1H0.7L12.8,0.7z', length: '60%', width: 6 },
      axisTick: { length: 10, lineStyle: { color: 'inherit', width: 2 } },
      splitLine: { length: 15, lineStyle: { color: 'inherit', width: 3 } },
      axisLabel: { color: getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#fff', fontSize: 10, distance: -40 },
      title: { offsetCenter: [0, '-20%'], fontSize: 14 },
      detail: { fontSize: 24, offsetCenter: [0, '0%'], valueAnimation: true, formatter: '{value}%', color: 'inherit' },
      data: [{ value: Math.round(yieldPct * 100) / 100, name: '整体Yield' }],
    }],
  })
}

function renderBinChart() {
  if (!binChart.value || !data.value?.bin_pie_data?.length) return
  if (!binChartInstance) {
    binChartInstance = echarts.init(binChart.value, undefined, getChartInitOpts())
  } else {
    binChartInstance.clear()
  }

  const allBinColors = ['#059669', '#dc2626', '#d97706', '#2563eb', '#7c3aed', '#ea580c', '#0284c7', '#db2777', '#c2410c', '#047857']

  binChartInstance.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', left: 'left', top: 'center', type: 'scroll', textStyle: { color: _tc() } },
    series: [{
      type: 'pie',
      radius: ['35%', '75%'],
      center: ['60%', '50%'],
      data: data.value.bin_pie_data,
      color: allBinColors,
      label: { formatter: '{b}\n{d}%', fontSize: 11 },
      emphasis: { label: { fontSize: 14, fontWeight: 'bold' } },
      itemStyle: { borderRadius: 8, borderColor: '#fff', borderWidth: 2 },
    }],
  })
}

function renderFailBarChart() {
  if (!failBarChart.value || !failTestItems.value.length) return
  if (!failBarChartInstance) {
    failBarChartInstance = echarts.init(failBarChart.value, undefined, getChartInitOpts())
  } else {
    failBarChartInstance.clear()
  }

  const top10 = failTestItems.value.slice(0, 10)

  failBarChartInstance.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '8%', bottom: '3%', top: '3%', containLabel: true },
    xAxis: { type: 'value', axisLabel: { color: _tc() } },
    yAxis: {
      type: 'category',
      data: top10.map((t) => (t.name.length > 25 ? t.name.slice(0, 25) + '...' : t.name)).reverse(),
      axisLabel: { fontSize: 10, color: _tc() },
    },
    series: [{
      type: 'bar',
      data: top10.map((t) => t.fail_count).reverse(),
      itemStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 1, y2: 0,
          colorStops: [{ offset: 0, color: '#f87171' }, { offset: 1, color: '#dc2626' }],
        },
      },
      label: { show: true, position: 'right', fontSize: 10 },
    }],
  })
}

function renderCpkDistChart() {
  if (!cpkDistChart.value || !paramStats.value.length) return

  if (!cpkDistChartInstance) {
    cpkDistChartInstance = echarts.init(cpkDistChart.value, undefined, getChartInitOpts())
  } else {
    cpkDistChartInstance.clear()
  }

  // 统计CPK分布 - 使用实际的等级名称（带括号）
  const levels: Record<string, number> = {}
  paramStats.value.forEach(p => {
    const level = p.cpk_level || ''
    if (level) {
      levels[level] = (levels[level] || 0) + 1
    }
  })

  // 过滤掉值为0的等级
  const chartData = Object.entries(levels)
    .filter(([_, value]) => value > 0)
    .map(([name, value]) => ({ name, value }))

  // 如果所有等级都是0，显示空状态
  if (chartData.length === 0) {
    cpkDistChartInstance.setOption({
      title: {
        text: '暂无CPK数据',
        left: 'center',
        top: 'center',
        textStyle: { color: _ts(), fontSize: 14 }
      }
    })
    return
  }

  // 定义颜色映射 - 根据等级前缀匹配
  const getColorByLevel = (levelName: string) => {
    if (levelName.startsWith('A级')) return '#059669'  // 绿色 - 优秀
    if (levelName.startsWith('B级')) return '#d97706'  // 橙色 - 良好
    if (levelName.startsWith('C级')) return '#dc2626'  // 红色 - 一般
    if (levelName.startsWith('D级')) return '#9ca3af'  // 灰色 - 不足
    return '#d1d5db'
  }

  cpkDistChartInstance.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c}个 ({d}%)' },
    legend: { orient: 'vertical', left: 'left', top: 'center', textStyle: { color: _tc() } },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['60%', '50%'],
      data: chartData.map(item => ({
        name: item.name,
        value: item.value,
        itemStyle: { color: getColorByLevel(item.name) }
      })),
      label: { formatter: '{b}: {c}个\n({d}%)' },
      color: chartData.map(item => getColorByLevel(item.name))
    }]
  })
}

function renderBinBarChart() {
  if (!binBarChart.value || !binTableData.value.length || !binSiteColumns.value.length) return
  if (!binBarChartInstance) {
    binBarChartInstance = echarts.init(binBarChart.value, undefined, getChartInitOpts())
  } else {
    binBarChartInstance.clear()
  }

  // Filter out the 'Total' row, reverse so Bin 1 is at the top
  const chartRows = binTableData.value.filter(r => r.bin !== 'Total').reverse()
  const bins = chartRows.map(r => r.bin)
  const sites = binSiteColumns.value

  // Color palette for sites
  const sitePalette = ['#11998e', '#f5576c', '#f9a825', '#4facfe', '#a8edea', '#ff6b6b', '#74b9ff', '#fd79a8']

  const series = sites.map((site, idx) => ({
    name: `Site ${site}`,
    type: 'bar' as const,
    data: chartRows.map(r => r[site] || 0),
    itemStyle: { color: sitePalette[idx % sitePalette.length] },
    barGap: '10%',
    emphasis: { focus: 'series' as const },
  }))

  binBarChartInstance.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const items = Array.isArray(params) ? params : [params]
        const total = items.reduce((s: number, p: any) => s + (p.value || 0), 0)
        let html = `<b>${items[0].axisValue}</b><br/>`
        items.forEach((p: any) => {
          html += `${p.marker} ${p.seriesName}: <b>${p.value}</b><br/>`
        })
        html += `<hr style="margin:4px 0"/>合计: <b>${total}</b>`
        return html
      },
    },
    legend: {
      bottom: 0,
      textStyle: { color: _tc(), fontSize: 12 },
    },
    grid: { left: '3%', right: '4%', bottom: '12%', top: '5%', containLabel: true },
    xAxis: { type: 'value', axisLabel: { color: _tc() } },
    yAxis: {
      type: 'category',
      data: bins,
      axisLabel: { color: _tc(), fontSize: 12 },
      inverse: true,
    },
    series,
  })
}

function renderSiteYieldBarChart() {
  if (!siteYieldBarChart.value || !data.value?.site_yield_data?.length) return
  if (!siteYieldBarChartInstance) {
    siteYieldBarChartInstance = echarts.init(siteYieldBarChart.value, undefined, getChartInitOpts())
  } else {
    siteYieldBarChartInstance.clear()
  }

  const siteData = data.value.site_yield_data
  const siteNames = siteData.map(d => d.Site)
  const siteYields = siteData.map(d => {
    const v = typeof d.Yield === 'string' ? parseFloat(d.Yield) : d.Yield
    return isNaN(v) ? 0 : v
  })

  // Color: green ≥95%, orange 90-95%, red <90%
  const getYieldColor = (y: number) => y >= 95 ? '#059669' : y < 90 ? '#dc2626' : '#d97706'

  siteYieldBarChartInstance.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params
        return `<b>${p.name}</b><br/>Yield: <b>${p.value.toFixed(2)}%</b>`
      },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true },
    xAxis: {
      type: 'category',
      data: siteNames,
      axisLabel: { fontSize: 12, color: _tc() },
    },
    yAxis: {
      type: 'value',
      max: 100,
      axisLabel: { formatter: '{value}%', color: _tc() },
    },
    series: [{
      type: 'bar',
      data: siteYields.map(y => ({
        value: y,
        itemStyle: { color: getYieldColor(y) },
      })),
      barWidth: '50%',
      label: { show: true, position: 'top', formatter: '{c}%', fontSize: 12, fontWeight: 'bold' },
    }],
  })
}

function renderAllCharts() {
  nextTick(() => {
    renderSiteYieldBarChart()
    renderYieldGaugeChart()
    renderBinChart()
    renderFailBarChart()
    renderCpkDistChart()
    renderBinBarChart()
  })
}

watch(data, async () => {
  renderAllCharts()
})

watch(() => themeStore.currentTheme, () => {
  // If component is cached by keep-alive (DOM detached), skip expensive chart re-render
  if (!binChart.value?.isConnected) return
  requestAnimationFrame(() => renderAllCharts())
})

watch(activeTab, (val) => {
  if (val === 'single') {
    nextTick(() => handleResize())
  }
})

async function exportHtml() {
  exporting.value = true
  try {
    const resp = await api.post('/export/dashboard_html/', {
      file_id: data.value?.file_id,
    }, { responseType: 'blob' })
    const url = window.URL.createObjectURL(new Blob([resp.data]))
    const link = document.createElement('a')
    link.href = url
    const now = new Date()
    const ts = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}${String(now.getSeconds()).padStart(2, '0')}`
    const fileLabel = (data.value?.filename || 'report').replace('.csv', '')
    link.download = `Dashboard_${fileLabel}_${ts}.html`
    link.click()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    console.error('导出失败:', error)
  } finally {
    exporting.value = false
  }
}

// 窗口 resize 处理（必须在 setup 同步阶段注册，不能在 async onMounted 的 await 之后）
const handleResize = () => {
  binChartInstance?.resize()
  yieldGaugeChartInstance?.resize()
  failBarChartInstance?.resize()
  cpkDistChartInstance?.resize()
  binBarChartInstance?.resize()
  siteYieldBarChartInstance?.resize()
}

function disposeAllCharts() {
  binChartInstance?.dispose(); binChartInstance = null
  yieldGaugeChartInstance?.dispose(); yieldGaugeChartInstance = null
  failBarChartInstance?.dispose(); failBarChartInstance = null
  cpkDistChartInstance?.dispose(); cpkDistChartInstance = null
  binBarChartInstance?.dispose(); binBarChartInstance = null
  siteYieldBarChartInstance?.dispose(); siteYieldBarChartInstance = null
}

window.addEventListener('resize', handleResize)
onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  disposeAllCharts()
})

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
  disposeAllCharts()
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
    // Wait for DOM to re-render chart containers (v-else activates after loading=false)
    await nextTick()
    renderAllCharts()
  }
}

onMounted(async () => {
  updateTime.value = new Date().toLocaleTimeString('zh-CN')
  await loadFiles()
  // Auto-select the latest file if nothing is already selected
  if (files.value.length > 0) {
    selectedFileId.value = files.value[0].id
    await onFileChange()
  } else {
    loading.value = false
  }
})
</script>

<style scoped>
/* ================================================================
   DataPhrase Dashboard — Industrial Data Terminal
   Rigorously gridded, consistent heights, high information density.
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
   KPI Cards — 4-column grid
   ================================================================ */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 20px;
}
@media (max-width: 992px) { .kpi-row { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 576px) { .kpi-row { grid-template-columns: 1fr; } }

.kpi-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 18px 16px 14px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  min-height: 112px;
  position: relative;
  overflow: hidden;
  transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
  box-shadow: 0 1px 3px rgba(0,0,0,.04);
}
@media (prefers-reduced-motion: reduce) {
  .kpi-card { transition: none; }
}
.kpi-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(0,0,0,.08);
}
/* Top accent bar — invisible until hover */
.kpi-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  border-radius: 10px 10px 0 0;
  transform: scaleX(0);
  transform-origin: left;
  transition: transform .25s ease;
}
.kpi-card:hover::before { transform: scaleX(1); }

.kpi-card--blue  { --kpi-accent: #2563eb; }
.kpi-card--green { --kpi-accent: #059669; }
.kpi-card--amber { --kpi-accent: #d97706; }
.kpi-card--slate { --kpi-accent: #4b5563; }
.kpi-card--blue::before  { background: linear-gradient(90deg, #1d4ed8, #3b82f6); }
.kpi-card--green::before { background: linear-gradient(90deg, #047857, #10b981); }
.kpi-card--amber::before { background: linear-gradient(90deg, #b45309, #f59e0b); }
.kpi-card--slate::before { background: linear-gradient(90deg, #374151, #6b7280); }

.kpi-card:hover { border-color: var(--kpi-accent, #2563eb); }

.kpi-icon   { font-size: 22px; line-height: 1; }
.kpi-label  { font-size: 12px; color: #6b7280; font-weight: 500; text-transform: uppercase; letter-spacing: .4px; }
.kpi-value  { font-size: 28px; font-weight: 700; color: #111827; line-height: 1.15; }
.kpi-unit   { font-size: 16px; font-weight: 600; color: #6b7280; margin-left: 1px; }
.kpi-sub    { font-size: 11px; color: #9ca3af; margin-top: 1px; }
.kpi-tag    { margin-top: 4px; }

/* ================================================================
   Alerts Bar
   ================================================================ */
.alerts-bar { margin-bottom: 20px; }
.alerts-bar-item { margin-bottom: 8px; }
.alerts-detail { font-size: 12px; margin-top: 4px; }

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
   Panel Row — two-column grid with explicit height tiers
   ================================================================ */
.panel-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 20px;
}
@media (max-width: 992px) { .panel-row { grid-template-columns: 1fr; } }

/* Width modifier: 14:10 split */
@media (min-width: 993px) {
  .panel-row--wider {
    grid-template-columns: 7fr 5fr;
  }
}

/* Height tiers — fixed on desktop, auto on mobile */
.panel-row--h420 .panel-card { height: 420px; }
.panel-row--h320 .panel-card { height: 320px; }
.panel-row--h400 .panel-card { height: 400px; }
.panel-row--h350 .panel-card { height: 350px; }
@media (max-width: 992px) {
  .panel-row--h420 .panel-card,
  .panel-row--h320 .panel-card,
  .panel-row--h400 .panel-card,
  .panel-row--h350 .panel-card { height: auto; min-height: 300px; }
}

/* ================================================================
   Panel Card
   ================================================================ */
.panel-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,.04);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel-card--col {
  padding: 14px;
  gap: 10px;
}
.panel-head {
  font-size: 14px;
  font-weight: 650;
  color: #374151;
  padding: 10px 16px;
  border-bottom: 1px solid #f3f4f6;
  background: #fafbfc;
  flex-shrink: 0;
}
.panel-body {
  flex: 1;
  min-height: 0;
  padding: 8px;
}
.panel-table {
  flex: 1;
  min-height: 0;
}
.chart-fill {
  width: 100%;
  height: 100%;
}

/* ================================================================
   Yield Stats (inside gauge card)
   ================================================================ */
.yield-stats {
  display: flex;
  gap: 12px;
  justify-content: space-around;
}
.yield-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.yield-stat-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 1px 8px;
  border-radius: 4px;
}
.yield-stat-label { font-size: 11px; color: #6b7280; }
.yield-stat-value { font-size: 18px; font-weight: 700; color: #1f2937; }

/* ================================================================
   Summary Cards (数据质量概览)
   ================================================================ */
.summary-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-bottom: 20px;
}
@media (max-width: 768px) { .summary-row { grid-template-columns: 1fr; } }

.summary-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 18px 20px;
  border-left: 3px solid #2563eb;
  transition: transform .2s ease, box-shadow .2s ease;
}
.summary-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0,0,0,.06);
}
.summary-card h4 {
  margin: 0 0 10px 0;
  font-size: 14px;
  font-weight: 650;
}
.summary-card p {
  margin: 6px 0;
  font-size: 13px;
  color: #4b5563;
}
.summary-card p b {
  color: #1f2937;
}
.summary-card--blue  { border-left-color: #2563eb; }
.summary-card--blue  h4 { color: #2563eb; }
.summary-card--red   { border-left-color: #dc2626; }
.summary-card--red   h4 { color: #dc2626; }
.summary-card--green { border-left-color: #059669; }
.summary-card--green h4 { color: #059669; }

/* ================================================================
   Fail total
   ================================================================ */
.fail-total {
  text-align: right;
  color: #dc2626;
  font-weight: 600;
  font-size: 13px;
  padding: 8px 12px;
  border-top: 1px solid #fee2e2;
  background: #fef2f2;
  margin-top: auto;
}

/* ================================================================
   Table cell helpers
   ================================================================ */
.cell-active   { font-weight: 650; color: #1a1f2e; }
.cell-inactive { font-weight: 400; color: #9ca3af; }
.cell-count    { font-size: 12px; color: #374151; white-space: nowrap; font-variant-numeric: tabular-nums; }
.cell-unit     { color: #9ca3af; font-size: 11px; }
.cell-spec     { font-size: 12px; color: #374151; }
.cell-na       { color: #9ca3af; }

/* ================================================================
   Footer
   ================================================================ */
.dash-footer {
  text-align: center;
  margin-top: 36px;
}
.dash-footer-note {
  margin: 16px 0 0;
  color: #9ca3af;
  font-size: 12px;
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

/* ----- KPI Cards ----- */
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
