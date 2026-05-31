<template>
  <div ref="chartRef" style="height: 450px" />
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'

const props = defineProps<{
  data: any
}>()

const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

const SITE_COLORS = [
  '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
  '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#5383e0',
]

function initChart() {
  if (!chartRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
  }
}

function renderChart() {
  if (!chartInstance || !props.data) return
  chartInstance.clear()

  const data = props.data
  const param = data.param || ''
  const unit = data.unit || ''
  const serialCol = data.serial_col || 'Serial'
  const continuousSerials = data.continuous_serials || []

  // Main series_data
  const series: any[] = (data.series_data || []).map(
    (sd: { name: string; data: number[][]; type?: string; symbolSize?: number }, idx: number) => ({
      name: sd.name,
      type: sd.type || 'scatter',
      data: sd.data,
      symbolSize: sd.symbolSize || 6,
      itemStyle: { color: SITE_COLORS[idx % SITE_COLORS.length] },
    })
  )

  // Add marks from backend (same format as old _build_mark_series)
  const marks = data.marks || []
  for (const mark of marks) {
    series.push({
      name: mark.name,
      type: mark.type || 'scatter',
      data: mark.data || [],
      markLine: mark.markLine,
      silent: true,
    })
  }

  // Build subtitle with limit info
  let subtext = unit ? `Unit: ${unit}` : ''
  if (data.lower_limit != null && data.upper_limit != null) {
    subtext += ` [${data.lower_limit.toFixed(4)}, ${data.upper_limit.toFixed(4)}]`
  }

  chartInstance.setOption({
    title: {
      text: `${param} Serial分布`,
      subtext,
      left: 'center',
      subtextStyle: { fontSize: 12 },
    },
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        return `${p.seriesName}<br/>${serialCol}: ${p.value[0]}<br/>Value: ${Number(p.value[1]).toFixed(4)}`
      },
    },
    legend: {
      data: series.map((s: any) => s.name),
      top: 'bottom',
      type: 'scroll',
    },
    toolbox: {
      feature: {
        saveAsImage: { name: `${param}_Serial分布` },
      },
    },
    xAxis: {
      type: 'category',
      data: continuousSerials,
      name: serialCol,
      nameLocation: 'middle',
      nameGap: 30,
      axisLabel: { rotate: 45, interval: 'auto' },
    },
    yAxis: {
      type: 'value',
      name: unit ? `${param} (${unit})` : param,
      nameLocation: 'middle',
      nameGap: 40,
      min: data.y_min,
      max: data.y_max,
      axisLabel: { formatter: (v: number) => v.toFixed(4) },
    },
    dataZoom: [
      { type: 'slider', xAxisIndex: 0, start: 0, end: 100 },
      { type: 'inside', xAxisIndex: 0 },
    ],
    series,
  })
}

function resize() {
  chartInstance?.resize()
}

watch(() => props.data, () => {
  nextTick(() => renderChart())
})

onMounted(() => {
  initChart()
  if (props.data) {
    renderChart()
  }
  window.addEventListener('resize', resize)
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>
