<template>
  <div class="dashboard-page">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1 class="page-title"><span aria-hidden="true">📊</span> 数据分析仪表板</h1>
      <p class="page-subtitle">
        数据文件: <b>{{ data?.filename || '未选择' }}</b>
        <span v-if="data?.program_name"> | 程序: <b>{{ data.program_name }}</b></span>
        | 更新时间: {{ updateTime }}
      </p>
    </div>

    <div v-if="loading" v-loading="loading" element-loading-text="加载仪表板数据..." style="min-height: 200px" />

    <template v-else-if="error">
      <el-empty description="暂无数据，请先在数据管理页面上传 ATE 数据文件" />
    </template>

    <template v-else>
      <!-- ===== 核心指标卡片 ===== -->
      <el-row :gutter="16">
        <el-col :xs="24" :sm="12" :md="6">
          <div class="metric-card metric-card-blue">
            <div class="metric-label">📋 总记录数</div>
            <div class="metric-value">{{ metrics.total_rows?.toLocaleString() }}</div>
          </div>
        </el-col>
        <el-col :xs="24" :sm="12" :md="6">
          <div class="metric-card metric-card-green">
            <div class="metric-label">✅ Pass数量</div>
            <div class="metric-value">{{ metrics.pass_count?.toLocaleString() }}</div>
          </div>
        </el-col>
        <el-col :xs="24" :sm="12" :md="6">
          <div class="metric-card metric-card-orange">
            <div class="metric-label">📈 Yield</div>
            <div class="metric-value">{{ metrics.yield_pct?.toFixed(2) }}%</div>
            <div class="metric-sub">❌ Fail: {{ metrics.fail_count }}</div>
          </div>
        </el-col>
        <el-col :xs="24" :sm="12" :md="6">
          <div class="metric-card metric-card-purple">
            <div class="metric-label">🔧 数据格式</div>
            <div class="metric-value" style="font-size: 20px">{{ metrics.format }}</div>
          </div>
        </el-col>
      </el-row>

      <!-- ===== 质量警报面板 ===== -->
      <div v-if="qualityAlerts.length > 0" style="margin-bottom: 16px">
        <el-alert
          v-for="alert in qualityAlerts"
          :key="alert.type"
          :type="alert.level"
          :title="alert.message"
          :closable="false"
          show-icon
          style="margin-bottom: 10px"
        >
          <template v-if="alert.params">
            <div style="font-size: 12px; margin-top: 5px">
              问题参数: {{ alert.params.join(', ') }}
            </div>
          </template>
          <template v-if="alert.max_site">
            <div style="font-size: 12px; margin-top: 5px">
              最高: {{ alert.max_site }} | 最低: {{ alert.min_site }}
            </div>
          </template>
        </el-alert>
      </div>

      <!-- ===== Bin 分布饼图 ===== -->
      <h2 class="section-title"><span aria-hidden="true">📋</span> Bin 分布</h2>
      <el-row :gutter="16">
        <el-col :xs="24" :lg="12">
          <el-card shadow="hover" header="🔴 Bin 分布饼图">
            <div ref="binChart" style="height: 420px" role="img" aria-label="Bin分布饼图" />
          </el-card>
        </el-col>
        <el-col :xs="24" :lg="12">
          <el-card shadow="hover">
            <div ref="yieldGaugeChart" style="height: 200px" role="img" aria-label="整体Yield仪表盘" />
            <el-row :gutter="12" style="margin-top: 8px">
              <el-col :span="8">
                <el-statistic title="最高" :value="siteYieldStats.max" suffix="%">
                  <template #prefix>
                    <el-tag size="small" type="success">{{ siteYieldStats.maxSite }}</el-tag>
                  </template>
                </el-statistic>
              </el-col>
              <el-col :span="8">
                <el-statistic title="最低" :value="siteYieldStats.min" suffix="%">
                  <template #prefix>
                    <el-tag size="small" type="danger">{{ siteYieldStats.minSite }}</el-tag>
                  </template>
                </el-statistic>
              </el-col>
              <el-col :span="8">
                <el-statistic title="差异" :value="siteYieldStats.diff" suffix="%" />
              </el-col>
            </el-row>
          </el-card>
        </el-col>
      </el-row>

      <!-- ===== Bin &times; Site 交叉表 ===== -->
      <h2 class="section-title"><span aria-hidden="true">&#x1F4CA;</span> Bin &times; Site 交叉表</h2>
      <el-row :gutter="16">
        <el-col :xs="24" :lg="24">
          <el-card shadow="hover">
            <el-table
              :data="binTableData"
              stripe
              size="small"
              max-height="400"
              :border="true"
            >
              <el-table-column prop="bin" label="Bin" width="80" align="center" fixed="left">
                <template #default="{ row }">
                  <el-tag :type="row.bin.includes('1') ? 'success' : row.bin === 'Total' ? 'info' : 'danger'" size="small">
                    {{ row.bin }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column
                v-for="col in binSiteColumns"
                :key="col"
                :prop="col"
                :label="`Site ${col}`"
                align="center"
                min-width="100"
              >
                <template #default="{ row }">
                  <span :class="row[col] > 0 ? 'cell-active' : 'cell-inactive'">
                    {{ row[col] || 0 }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="all_site" label="ALL Site" align="center" min-width="130" fixed="right">
                <template #default="{ row }">
                  <el-tag type="info" size="small">{{ row.all_site || 0 }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
      </el-row>

      <!-- ===== 参数质量分析 ===== -->
      <h2 v-if="paramStats.length > 0" class="section-title"><span aria-hidden="true">📊</span> 参数质量分析 (Top 10 CPK)</h2>
      <el-row v-if="paramStats.length > 0" :gutter="16">
        <el-col :xs="24" :lg="14">
          <el-card shadow="hover">
            <el-table :data="paramStats" stripe size="small" max-height="350" :border="true">
              <el-table-column prop="param" label="参数名称" min-width="150" show-overflow-tooltip />
              <el-table-column prop="cpk" label="CPK" width="80" align="center">
                <template #default="{ row }">
                  <el-tag :type="getCpkTagType(row.cpk)" size="small">
                    {{ row.cpk.toFixed(2) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="cpk_level" label="等级" width="100" align="center">
                <template #default="{ row }">
                  <span :style="{ color: row.cpk_color, fontWeight: 'bold' }">
                    {{ row.cpk_level }}
                  </span>
                </template>
              </el-table-column>
              <el-table-column prop="mean" label="均值" width="120" align="right">
                <template #default="{ row }">
                  {{ row.mean.toFixed(4) }} <span style="color: var(--text-tertiary)">{{ row.unit }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="std" label="标准差" width="100" align="right">
                <template #default="{ row }">
                  {{ row.std.toFixed(4) }}
                </template>
              </el-table-column>
              <el-table-column label="规格限" width="180" align="center">
                <template #default="{ row }">
                  <span v-if="row.lsl !== null && row.usl !== null" style="font-size: 12px">
                    {{ row.lsl.toFixed(4) }} ~ {{ row.usl.toFixed(4) }}
                  </span>
                  <span v-else style="color: var(--text-tertiary)">未设置</span>
                </template>
              </el-table-column>
            </el-table>
          </el-card>
        </el-col>
        <el-col :xs="24" :lg="10">
          <el-card shadow="hover" header="CPK分布统计">
            <div ref="cpkDistChart" style="height: 350px" role="img" aria-label="CPK分布统计饼图" />
          </el-card>
        </el-col>
      </el-row>

      <!-- ===== 数据质量概览 ===== -->
      <h2 class="section-title"><span aria-hidden="true">📉</span> Fail 测试项分析</h2>
      <el-row :gutter="16">
        <el-col :xs="24" :lg="12">
          <el-card shadow="hover">
            <el-table
              :data="failTestItems"
              stripe
              size="small"
              max-height="320"
              :border="true"
            >
              <el-table-column prop="name" label="测试项名称" show-overflow-tooltip min-width="200" />
              <el-table-column prop="fail_count" label="Fail数量" width="100" align="center" />
              <el-table-column prop="percentage" label="占比(%)" width="100" align="center">
                <template #default="{ row }">{{ row.percentage }}%</template>
              </el-table-column>
            </el-table>
            <div class="fail-total">总Fail次数: {{ totalFailCount }}</div>
          </el-card>
        </el-col>
        <el-col :xs="24" :lg="12">
          <el-card shadow="hover" header="Top 10 Fail测试项">
            <div ref="failBarChart" style="height: 350px" role="img" aria-label="Top 10 Fail测试项柱状图" />
          </el-card>
        </el-col>
      </el-row>

      <!-- ===== UPH 效率分析 ===== -->
      <h2 class="section-title"><span aria-hidden="true">⚡</span> UPH 效率分析</h2>
      <el-row :gutter="16" style="margin-bottom: 16px">
        <el-col :span="24">
          <UphCard :file-id="data?.file_id || null" />
        </el-col>
      </el-row>

      <!-- ===== 数据质量概览 ===== -->
      <h2 class="section-title"><span aria-hidden="true">🔍</span> 数据质量概览</h2>
      <el-row :gutter="16">
        <el-col :xs="24" :sm="8">
          <div class="info-card">
            <h4 class="info-card-title" style="color: #667eea;">📊 测试项统计</h4>
            <p class="info-card-item">数值测试项: <b>{{ quality.numeric_items }}</b></p>
            <p class="info-card-item">有Limit测试项: <b>{{ quality.items_with_limits }}</b></p>
            <p class="info-card-item">Site数量: <b>{{ quality.site_count }}</b></p>
          </div>
        </el-col>
        <el-col :xs="24" :sm="8">
          <div class="info-card" style="border-left-color: #f5576c;">
            <h4 class="info-card-title" style="color: #f5576c;">🎯 Bin 分布</h4>
            <p class="info-card-item">Bin种类: <b>{{ quality.bin_types }}</b></p>
            <p class="info-card-item">Fail Bin: <b>{{ quality.fail_bin_count }}</b></p>
            <p class="info-card-item">Pass率: <b>{{ metrics.yield_pct?.toFixed(2) }}%</b></p>
          </div>
        </el-col>
        <el-col :xs="24" :sm="8">
          <div class="info-card" style="border-left-color: #11998e;">
            <h4 class="info-card-title" style="color: #11998e;">⚠️ 关键问题</h4>
            <p class="info-card-item">Top Fail项: <b>{{ topFailItem }}</b></p>
            <p class="info-card-item">Fail次数: <b>{{ topFailCount }}</b></p>
            <p class="info-card-item">总Fail项: <b>{{ failTestItems.length }}</b></p>
          </div>
        </el-col>
      </el-row>

      <!-- 导出按钮 -->
      <div class="export-actions">
        <el-button type="primary" size="large" :loading="exporting" @click="exportHtml">
          <span aria-hidden="true">📥</span> 保存 HTML 报表
        </el-button>
      </div>

      <!-- 底部版权 -->
      <p class="footer-text">
        <span aria-hidden="true">📅</span> 最后更新: {{ updateTime }} | LiqunData ATE数据分析软件
      </p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, watch, computed } from 'vue'
import * as echarts from 'echarts'
import { useThemeStore } from '../../stores/theme'
import api from '../../api'
import UphCard from './components/UphCard.vue'

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

const loading = ref(true)
const error = ref(false)
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
const siteYieldChart = ref<HTMLElement>()
const yieldGaugeChart = ref<HTMLElement>()
const failBarChart = ref<HTMLElement>()
const cpkDistChart = ref<HTMLElement>()

// Chart instances
let binChartInstance: echarts.ECharts | null = null
let siteYieldChartInstance: echarts.ECharts | null = null
let yieldGaugeChartInstance: echarts.ECharts | null = null
let failBarChartInstance: echarts.ECharts | null = null
let cpkDistChartInstance: echarts.ECharts | null = null

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

const totalFailCount = computed(() => failTestItems.value.reduce((sum, item) => sum + item.fail_count, 0))

const topFailItem = computed(() => {
  if (!failTestItems.value.length) return '无'
  const name = failTestItems.value[0].name
  return name.length > 20 ? name.slice(0, 20) + '...' : name
})

const topFailCount = computed(() => failTestItems.value[0]?.fail_count ?? 0)

function getCpkTagType(cpk: number): string {
  if (cpk >= 1.67) return 'success'
  if (cpk >= 1.33) return 'warning'
  return 'danger'
}

function getSiteYieldColor(yieldVal: number): string {
  if (yieldVal >= 95) return '#11998e'  // 绿色
  if (yieldVal >= 90) return '#f9a825'  // 橙色
  return '#f5576c'                       // 红色
}

function renderSiteYieldChart() {
  if (!siteYieldChart.value || !data.value?.site_yield_data?.length) return
  if (!siteYieldChartInstance) {
    siteYieldChartInstance = echarts.init(siteYieldChart.value)
  } else {
    siteYieldChartInstance.clear()
  }

  const sites = data.value.site_yield_data.map((d) => d.Site)
  const yields = data.value.site_yield_data.map((d) => {
    const yieldValue = typeof d.Yield === 'string' ? parseFloat(d.Yield) : d.Yield
    return isNaN(yieldValue) ? 0 : yieldValue
  })
  const colors = yields.map((y) => getSiteYieldColor(y))

  siteYieldChartInstance.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params
        return `Site ${p.name}<br/>Yield: ${p.value.toFixed(2)}%`
      },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true },
    xAxis: {
      type: 'category',
      data: sites,
      axisLabel: { fontSize: 12, color: _tc() },
    },
    yAxis: {
      type: 'value',
      max: 100,
      axisLabel: { formatter: '{value}%', color: _tc() },
    },
    series: [{
      type: 'bar',
      data: yields.map((y, i) => ({
        value: y,
        itemStyle: { color: colors[i] },
      })),
      barWidth: '50%',
      label: { show: true, position: 'top', formatter: '{c}%', fontSize: 12, fontWeight: 'bold' },
    }],
  })
}

function renderYieldGaugeChart() {
  if (!yieldGaugeChart.value) return
  if (!yieldGaugeChartInstance) {
    yieldGaugeChartInstance = echarts.init(yieldGaugeChart.value)
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
            [0.90, '#f5576c'],  // 0-90%: 红色
            [0.95, '#f9a825'],  // 90-95%: 橙色
            [1, '#11998e'],     // 95-100%: 绿色
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
    binChartInstance = echarts.init(binChart.value)
  } else {
    binChartInstance.clear()
  }

  const allBinColors = ['#11998e', '#f5576c', '#f9a825', '#4facfe', '#a8edea', '#ff6b6b', '#74b9ff', '#fd79a8', '#e17055', '#00b894']

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
    failBarChartInstance = echarts.init(failBarChart.value)
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
          colorStops: [{ offset: 0, color: '#f093fb' }, { offset: 1, color: '#f5576c' }],
        },
      },
      label: { show: true, position: 'right', fontSize: 10 },
    }],
  })
}

function renderCpkDistChart() {
  if (!cpkDistChart.value || !paramStats.value.length) return

  if (!cpkDistChartInstance) {
    cpkDistChartInstance = echarts.init(cpkDistChart.value)
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
    if (levelName.startsWith('A级')) return '#11998e'  // 绿色 - 优秀
    if (levelName.startsWith('B级')) return '#f9a825'  // 黄色 - 良好
    if (levelName.startsWith('C级')) return '#f5576c'  // 橙色 - 一般
    if (levelName.startsWith('D级')) return '#999'     // 灰色 - 不足
    return '#ccc'
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

function renderAllCharts() {
  nextTick(() => {
    renderSiteYieldChart()
    renderYieldGaugeChart()
    renderBinChart()
    renderFailBarChart()
    renderCpkDistChart()
  })
}

watch(data, async () => {
  renderAllCharts()
})

watch(() => themeStore.currentTheme, () => {
  renderAllCharts()
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

onMounted(async () => {
  updateTime.value = new Date().toLocaleTimeString('zh-CN')
  try {
    const res = await api.get('/summary/')
    if (res.data.error) { error.value = true; loading.value = false; return }
    const d = res.data as DashboardData
    data.value = d
    metrics.value = d.metrics
    failTestItems.value = d.fail_test_items
    quality.value = { ...d.quality_overview, fail_bin_count: d.quality_overview.fail_bin_count || 0 }
    binTableData.value = d.bin_table_data || []
    binSiteColumns.value = d.bin_site_columns || []
    paramStats.value = d.param_stats || []
    qualityAlerts.value = d.quality_alerts || []
    renderAllCharts()
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }

  // 窗口 resize 处理
  const handleResize = () => {
    binChartInstance?.resize()
    siteYieldChartInstance?.resize()
    yieldGaugeChartInstance?.resize()
    failBarChartInstance?.resize()
    cpkDistChartInstance?.resize()
  }

  window.addEventListener('resize', handleResize)

  // 清理监听器
  onUnmounted(() => {
    window.removeEventListener('resize', handleResize)
  })
})
</script>

<style scoped>
.dashboard-page {
  padding-bottom: 30px;
}

.page-header {
  text-align: center;
  margin-bottom: 25px;
}

.page-title {
  color: var(--text-primary);
  margin-bottom: 5px;
  font-size: 24px;
}

.page-subtitle {
  color: var(--text-secondary);
  margin-bottom: 25px;
  font-size: 14px;
}

.metric-card {
  padding: 20px;
  border-radius: 8px;
  color: var(--text-inverse);
  text-align: center;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.06);
  margin-bottom: 10px;
  height: 120px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.metric-card-blue {
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
}

.metric-card-green {
  background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
}

.metric-card-orange {
  background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
}

.metric-card-purple {
  background: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%);
  color: var(--text-primary);
}

.metric-value {
  font-size: 28px;
  font-weight: bold;
  margin: 8px 0;
}

.metric-label {
  font-size: 14px;
  opacity: 0.9;
}

.metric-sub {
  font-size: 12px;
  margin-top: 5px;
}

.section-title {
  font-size: 20px;
  font-weight: bold;
  color: var(--text-primary);
  margin: 25px 0 15px 0;
  padding-left: 12px;
  border-left: 4px solid var(--brand-primary);
}

.info-card {
  background: var(--bg-secondary);
  border-radius: 8px;
  padding: 15px;
  border-left: 4px solid var(--brand-primary);
  margin-bottom: 10px;
}

.info-card-title {
  margin: 0 0 10px 0;
}

.info-card-item {
  margin: 5px 0;
}

.fail-total {
  text-align: right;
  color: var(--color-error);
  font-weight: bold;
  margin-top: 8px;
}

.export-actions {
  text-align: center;
  margin-top: 30px;
}

.footer-text {
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12px;
  margin-top: 30px;
  padding-bottom: 10px;
}

.cell-active {
  font-weight: bold;
  color: var(--text-primary);
}

.cell-inactive {
  font-weight: normal;
  color: var(--text-tertiary);
}
</style>
