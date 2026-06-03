<template>
  <div v-loading="loading" element-loading-text="加载良率趋势数据..." style="height: 400px">
    <div v-if="error" class="empty-state">
      <el-empty description="暂无良率趋势数据" />
    </div>
    <div v-else ref="chartRef" style="height: 400px" role="img" aria-label="良率趋势图" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import * as echarts from 'echarts'
import { getChartInitOpts } from '../../../utils/echarts-theme'
import { useThemeStore } from '../../../stores/theme'
import { analysisApi } from '../../../api/analysis'

// Theme-aware color helpers
const _tc = () => getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#ffffff'
const _ts = () => getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim() || 'rgba(255,255,255,0.8)'

const themeStore = useThemeStore()

interface YieldTrendData {
  files: string[]
  yields: number[]
  ucl: number | null
  cl: number | null
  lcl: number | null
  anomalies: { name: string; yield: number }[]
}

const props = defineProps<{
  fileId: number | null
}>()

const loading = ref(false)
const error = ref(false)
const chartData = ref<YieldTrendData | null>(null)
const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

async function fetchData() {
  if (!props.fileId) {
    error.value = true
    loading.value = false
    return
  }

  loading.value = true
  error.value = false

  try {
    const { data } = await analysisApi.getYieldTrend([props.fileId])
    if (!data || !data.files || !data.files.length) {
      error.value = true
      chartData.value = null
    } else {
      // Transform API response to chart format
      const files: string[] = data.files.map((f: any) => f.filename || `Lot ${f.file_id}`)
      const yields: number[] = data.trend_data.map((t: any) => t.yield)
      const spc = data.spc_limits || {}
      chartData.value = {
        files,
        yields,
        ucl: spc.ucl ?? null,
        cl: spc.cl ?? null,
        lcl: spc.lcl ?? null,
        anomalies: (data.anomalies || []).map((a: any) => ({
          name: files[a.file_index] || `Lot ${a.file_index}`,
          yield: a.yield,
        })),
      }
      error.value = false
    }
  } catch {
    error.value = true
    chartData.value = null
  } finally {
    loading.value = false
    nextTick(() => renderChart())
  }
}

function renderChart() {
  if (!chartRef.value || !chartData.value || error.value) return

  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value, undefined, getChartInitOpts())
  } else {
    chartInstance.clear()
  }

  const d = chartData.value
  const mainLineColor = themeStore.currentTheme === 'night' ? '#4fc3f7' : '#11998e'

  // Build markLine data for control limits
  const markLines: any[] = []
  if (d.ucl !== null) {
    markLines.push({
      yAxis: d.ucl,
      name: 'UCL',
      label: { formatter: 'UCL: {c}', color: '#f5576c' },
      lineStyle: { color: '#f5576c', type: 'dashed' as const, width: 2 },
    })
  }
  if (d.cl !== null) {
    markLines.push({
      yAxis: d.cl,
      name: 'CL',
      label: { formatter: 'CL: {c}', color: '#f9a825' },
      lineStyle: { color: '#f9a825', type: 'dashed' as const, width: 2 },
    })
  }
  if (d.lcl !== null) {
    markLines.push({
      yAxis: d.lcl,
      name: 'LCL',
      label: { formatter: 'LCL: {c}', color: '#f5576c' },
      lineStyle: { color: '#f5576c', type: 'dashed' as const, width: 2 },
    })
  }

  // Build markPoint data for anomalies
  const anomalyPoints = (d.anomalies || []).map((a) => ({
    name: a.name,
    coord: [a.name, a.yield] as [string, number],
    itemStyle: { color: '#f5576c' },
    symbol: 'pin',
    symbolSize: 40,
    label: { formatter: '{c}', fontSize: 10 },
  }))

  chartInstance.setOption({
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params
        let html = `<div>${p.name}</div><div>Yield: ${p.value.toFixed(2)}%</div>`
        if (d.ucl !== null) html += `<div style="color:#f5576c">UCL: ${d.ucl.toFixed(2)}%</div>`
        if (d.cl !== null) html += `<div style="color:#f9a825">CL: ${d.cl.toFixed(2)}%</div>`
        if (d.lcl !== null) html += `<div style="color:#f5576c">LCL: ${d.lcl.toFixed(2)}%</div>`
        return html
      },
    },
    grid: { left: '5%', right: '5%', bottom: '15%', top: '10%', containLabel: true },
    xAxis: {
      type: 'category',
      data: d.files,
      axisLabel: {
        color: _tc(),
        rotate: d.files.length > 6 ? 45 : 0,
        fontSize: 11,
      },
      axisLine: { lineStyle: { color: _ts() } },
    },
    yAxis: {
      type: 'value',
      min: d.lcl !== null ? Math.floor(d.lcl * 0.98) : undefined,
      max: d.ucl !== null ? Math.ceil(d.ucl * 1.02) : 100,
      axisLabel: { formatter: '{value}%', color: _tc() },
      splitLine: { lineStyle: { color: _ts(), type: 'dashed' } },
    },
    dataZoom: [
      {
        type: 'slider',
        show: true,
        start: 0,
        end: 100,
        height: 20,
        bottom: 5,
        borderColor: _ts(),
        textStyle: { color: _tc() },
        fillerColor: themeStore.currentTheme === 'night' ? 'rgba(79, 195, 247, 0.2)' : 'rgba(17, 153, 142, 0.2)',
      },
    ],
    series: [
      {
        type: 'line',
        data: d.yields,
        smooth: true,
        symbol: 'circle',
        symbolSize: 8,
        lineStyle: {
          color: mainLineColor,
          width: 3,
        },
        itemStyle: {
          color: mainLineColor,
        },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: themeStore.currentTheme === 'night' ? 'rgba(79, 195, 247, 0.3)' : 'rgba(17, 153, 142, 0.3)' },
              { offset: 1, color: 'rgba(17, 153, 142, 0.02)' },
            ],
          },
        },
        markLine: {
          silent: true,
          symbol: 'none',
          data: markLines,
        },
        markPoint: {
          silent: true,
          data: anomalyPoints,
        },
      },
    ],
  })
}

function handleResize() {
  chartInstance?.resize()
}

watch(() => props.fileId, () => {
  fetchData()
})

watch(() => themeStore.currentTheme, () => {
  if (!chartRef.value?.isConnected) return
  nextTick(() => renderChart())
})

onMounted(() => {
  fetchData()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<style scoped>
.empty-state {
  height: 400px;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
