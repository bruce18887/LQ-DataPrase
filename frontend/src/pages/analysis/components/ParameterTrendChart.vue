<template>
  <div ref="chartRef" class="chart-container" style="width: 100%; height: 500px" />
</template>

<script setup lang="ts">
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'

interface TrendPoint { file_id: number; mean: number; std: number; min: number; max: number; cpk: number; count: number }
interface FileInfo { file_id: number; filename: string; timestamp: string }
interface ParamTrendData { param: string; files: FileInfo[]; trend_data: TrendPoint[]; limits: { lsl: number | null; usl: number | null } }

const props = defineProps<{ data: ParamTrendData | null; title?: string }>()
const { colors } = useEChartsTheme()

function buildOption() {
  if (!props.data) return {}
  const tc = colors.value.textColor
  const { files, trend_data, limits, param } = props.data
  if (!files || files.length === 0) return {}

  const xAxisData = files.map((f, idx) => f.filename || `File ${idx + 1}`)
  const meanData = trend_data.map(d => d.mean)
  const cpkData = trend_data.map(d => d.cpk)
  const upperBand = trend_data.map(d => d.mean + d.std)
  const lowerBand = trend_data.map(d => d.mean - d.std)

  const series: any[] = [
    { name: 'Mean', type: 'line', data: meanData, itemStyle: { color: '#5470C6' }, lineStyle: { width: 3 }, symbol: 'circle', symbolSize: 8, yAxisIndex: 0 },
    { name: 'Mean + Std', type: 'line', data: upperBand, itemStyle: { color: '#91CC75' }, lineStyle: { type: 'dashed', width: 1 }, symbol: 'none', yAxisIndex: 0 },
    { name: 'Mean - Std', type: 'line', data: lowerBand, itemStyle: { color: '#91CC75' }, lineStyle: { type: 'dashed', width: 1 }, symbol: 'none', areaStyle: { color: 'rgba(145, 204, 117, 0.2)' }, yAxisIndex: 0 },
    { name: 'CPK', type: 'line', data: cpkData, itemStyle: { color: '#EE6666' }, lineStyle: { width: 2 }, symbol: 'diamond', symbolSize: 8, yAxisIndex: 1 },
  ]

  const markLines: any[] = []
  if (limits.usl !== null) markLines.push({ name: 'USL', yAxis: limits.usl, lineStyle: { color: '#F56C6C', type: 'solid', width: 2 }, label: { formatter: 'USL', position: 'end' } })
  if (limits.lsl !== null) markLines.push({ name: 'LSL', yAxis: limits.lsl, lineStyle: { color: '#F56C6C', type: 'solid', width: 2 }, label: { formatter: 'LSL', position: 'end' } })
  if (markLines.length > 0) series[0].markLine = { silent: true, data: markLines }

  return {
    title: { text: props.title || `Parameter Trend - ${param}`, left: 'center', textStyle: { fontSize: 16, fontWeight: 'bold' } },
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        if (!Array.isArray(params)) return ''
        const idx = params[0].dataIndex
        const tp = trend_data[idx]
        return `<strong>${xAxisData[idx]}</strong><br/>Mean: ${tp.mean.toFixed(4)}<br/>Std: ${tp.std.toFixed(4)}<br/>Min: ${tp.min.toFixed(4)}<br/>Max: ${tp.max.toFixed(4)}<br/>CPK: ${tp.cpk.toFixed(4)}<br/>Count: ${tp.count}`
      },
    },
    legend: { data: ['Mean', 'Mean + Std', 'Mean - Std', 'CPK'], top: 30, textStyle: { color: tc } },
    grid: { left: '3%', right: '5%', bottom: '15%', containLabel: true },
    xAxis: { type: 'category', data: xAxisData, axisLabel: { rotate: 45, interval: 0, fontSize: 10, color: tc } },
    yAxis: [
      { type: 'value', name: 'Value', nameTextStyle: { color: tc }, position: 'left', axisLabel: { formatter: '{value}', color: tc } },
      { type: 'value', name: 'CPK', nameTextStyle: { color: tc }, position: 'right', min: 0, axisLabel: { formatter: '{value}', color: tc } },
    ],
    series,
  }
}

const { chartRef } = useChart(buildOption, [() => props.data, () => props.title])
void chartRef // bound to <div ref="chartRef"> in template
</script>

<style scoped>
.chart-container { width: 100%; height: 100%; min-height: 400px; }
</style>
