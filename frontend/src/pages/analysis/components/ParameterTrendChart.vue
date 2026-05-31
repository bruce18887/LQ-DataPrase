<template>
  <div ref="chartRef" class="chart-container" style="width: 100%; height: 500px" />
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'

interface TrendPoint {
  file_id: number
  mean: number
  std: number
  min: number
  max: number
  cpk: number
  count: number
}

interface FileInfo {
  file_id: number
  filename: string
  timestamp: string
}

interface ParamTrendData {
  param: string
  files: FileInfo[]
  trend_data: TrendPoint[]
  limits: {
    lsl: number | null
    usl: number | null
  }
}

const props = defineProps<{
  data: ParamTrendData | null
  title?: string
}>()

const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

function initChart() {
  if (!chartRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
  }
}

function renderChart() {
  if (!chartInstance || !props.data) return

  chartInstance.clear()

  const { files, trend_data, limits, param } = props.data

  if (!files || files.length === 0) return

  // X-axis categories (filenames or timestamps)
  const xAxisData = files.map((f, idx) => f.filename || `File ${idx + 1}`)

  // Extract data series
  const meanData = trend_data.map(d => d.mean)
  const cpkData = trend_data.map(d => d.cpk)

  // Calculate mean ± std bands
  const upperBand = trend_data.map(d => d.mean + d.std)
  const lowerBand = trend_data.map(d => d.mean - d.std)

  const series: any[] = [
    {
      name: 'Mean',
      type: 'line',
      data: meanData,
      itemStyle: { color: '#5470C6' },
      lineStyle: { width: 3 },
      symbol: 'circle',
      symbolSize: 8,
      yAxisIndex: 0
    },
    {
      name: 'Mean + Std',
      type: 'line',
      data: upperBand,
      itemStyle: { color: '#91CC75' },
      lineStyle: { type: 'dashed', width: 1 },
      symbol: 'none',
      yAxisIndex: 0
    },
    {
      name: 'Mean - Std',
      type: 'line',
      data: lowerBand,
      itemStyle: { color: '#91CC75' },
      lineStyle: { type: 'dashed', width: 1 },
      symbol: 'none',
      areaStyle: {
        color: 'rgba(145, 204, 117, 0.2)'
      },
      yAxisIndex: 0
    },
    {
      name: 'CPK',
      type: 'line',
      data: cpkData,
      itemStyle: { color: '#EE6666' },
      lineStyle: { width: 2 },
      symbol: 'diamond',
      symbolSize: 8,
      yAxisIndex: 1
    }
  ]

  // Add USL/LSL as markLines if available
  const markLines: any[] = []
  if (limits.usl !== null) {
    markLines.push({
      name: 'USL',
      yAxis: limits.usl,
      lineStyle: { color: '#F56C6C', type: 'solid', width: 2 },
      label: { formatter: 'USL', position: 'end' }
    })
  }
  if (limits.lsl !== null) {
    markLines.push({
      name: 'LSL',
      yAxis: limits.lsl,
      lineStyle: { color: '#F56C6C', type: 'solid', width: 2 },
      label: { formatter: 'LSL', position: 'end' }
    })
  }

  if (markLines.length > 0) {
    series[0].markLine = {
      silent: true,
      data: markLines
    }
  }

  const option: echarts.EChartsOption = {
    title: {
      text: props.title || `Parameter Trend - ${param}`,
      left: 'center',
      textStyle: {
        fontSize: 16,
        fontWeight: 'bold'
      }
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'cross'
      },
      formatter: (params: any) => {
        if (!Array.isArray(params)) return ''
        const idx = params[0].dataIndex
        const trendPoint = trend_data[idx]
        let result = `<strong>${xAxisData[idx]}</strong><br/>`
        result += `Mean: ${trendPoint.mean.toFixed(4)}<br/>`
        result += `Std: ${trendPoint.std.toFixed(4)}<br/>`
        result += `Min: ${trendPoint.min.toFixed(4)}<br/>`
        result += `Max: ${trendPoint.max.toFixed(4)}<br/>`
        result += `CPK: ${trendPoint.cpk.toFixed(4)}<br/>`
        result += `Count: ${trendPoint.count}`
        return result
      }
    },
    legend: {
      data: ['Mean', 'Mean + Std', 'Mean - Std', 'CPK'],
      top: 30
    },
    grid: {
      left: '3%',
      right: '5%',
      bottom: '15%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: xAxisData,
      axisLabel: {
        rotate: 45,
        interval: 0,
        fontSize: 10
      }
    },
    yAxis: [
      {
        type: 'value',
        name: 'Value',
        position: 'left',
        axisLabel: {
          formatter: '{value}'
        }
      },
      {
        type: 'value',
        name: 'CPK',
        position: 'right',
        min: 0,
        axisLabel: {
          formatter: '{value}'
        }
      }
    ],
    series: series
  }

  chartInstance.setOption(option)
}

function handleResize() {
  chartInstance?.resize()
}

onMounted(() => {
  initChart()
  renderChart()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})

watch(() => props.data, () => {
  renderChart()
}, { deep: true })

watch(() => props.title, () => {
  renderChart()
})
</script>

<style scoped>
.chart-container {
  width: 100%;
  height: 100%;
  min-height: 400px;
}
</style>
