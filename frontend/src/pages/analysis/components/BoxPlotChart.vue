<!-- frontend/src/pages/analysis/components/BoxPlotChart.vue -->
<template>
  <div ref="chartRef" class="chart-container" style="width: 100%; height: 500px" />
</template>

<script setup lang="ts">
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'

interface BoxPlotStats {
  min: number; q1: number; median: number; q3: number; max: number; outliers: number[]; count: number; raw_values?: number[]
}
interface BoxPlotData {
  param: string; overall?: BoxPlotStats; by_site?: Record<string, BoxPlotStats>; by_bin?: Record<string, BoxPlotStats>
}

const props = withDefaults(defineProps<{ data: BoxPlotData | null; title?: string; showJitter?: boolean }>(), {
  showJitter: false,
})
const { colors } = useEChartsTheme()

const BOX_COLOR = '#5470c6'
const JITTER_COLOR = '#73c0de'

function buildOption() {
  if (!props.data) return {}
  const tc = colors.value.textColor
  const { overall, by_site, by_bin } = props.data
  const hasGroupedData = (by_site && Object.keys(by_site).length > 0) || (by_bin && Object.keys(by_bin).length > 0)
  const groupedData = by_site || by_bin || {}

  let categories: string[] = []
  let boxData: number[][] = []
  let outlierData: number[][] = []
  let jitterSeries: any[] = []
  let yMin = Infinity, yMax = -Infinity

  if (hasGroupedData) {
    const sortedKeys = Object.keys(groupedData).sort((a, b) => {
      const numA = parseFloat(a); const numB = parseFloat(b)
      if (!isNaN(numA) && !isNaN(numB)) return numA - numB
      return a.localeCompare(b)
    })
    categories = sortedKeys.map(key =>
      /^\d+(\.\d+)?$/.test(key) ? `Site ${key}` : key
    )
    sortedKeys.forEach((group, idx) => {
      const s = groupedData[group]
      boxData.push([s.min, s.q1, s.median, s.q3, s.max])
      s.outliers.forEach(o => outlierData.push([idx, o]))
      yMin = Math.min(yMin, s.min)
      yMax = Math.max(yMax, s.max)

      if (props.showJitter && s.raw_values && s.raw_values.length > 0) {
        jitterSeries.push({
          name: `${categories[idx]} 数据点`,
          type: 'scatter',
          data: s.raw_values.map((v: number) => [idx + (Math.random() - 0.5) * 0.3, v]),
          symbolSize: 3,
          itemStyle: { color: JITTER_COLOR, opacity: 0.25 },
          silent: true,
        })
      }
    })
  } else if (overall) {
    categories = [props.data.param]
    boxData.push([overall.min, overall.q1, overall.median, overall.q3, overall.max])
    overall.outliers.forEach(o => outlierData.push([0, o]))
    yMin = overall.min
    yMax = overall.max

    if (props.showJitter && overall.raw_values && overall.raw_values.length > 0) {
      jitterSeries.push({
        name: '数据点',
        type: 'scatter',
        data: overall.raw_values.map((v: number) => [(Math.random() - 0.5) * 0.3, v]),
        symbolSize: 3,
        itemStyle: { color: JITTER_COLOR, opacity: 0.25 },
        silent: true,
      })
    }
  }

  // Y-axis: focus on non-outlier range with padding
  const yRange = yMax - yMin
  const yPad = yRange > 0 ? yRange * 0.1 : Math.abs(yMax) * 0.1 || 1

  // X-axis name
  const xAxisName = by_site ? 'Site' : by_bin ? 'Bin' : ''

  return {
    title: {
      text: props.title || `Box Plot - ${props.data.param}`,
      left: 'center',
      textStyle: { fontSize: 15, fontWeight: '600', color: tc },
    },
    tooltip: { trigger: 'item', axisPointer: { type: 'shadow' } },
    grid: { left: '8%', right: '8%', bottom: '12%', top: '12%', containLabel: true },
    xAxis: {
      type: 'category',
      data: categories,
      boundaryGap: true,
      name: xAxisName,
      nameLocation: 'center',
      nameGap: 35,
      nameTextStyle: { color: tc, fontSize: 13, fontWeight: 500 },
      axisLine: { lineStyle: { color: tc } },
      axisLabel: {
        rotate: categories.length > 10 ? 45 : 0,
        interval: 0,
        fontSize: 11,
        color: tc,
        fontWeight: 500,
        formatter: (val: string) => {
          // Show "Site X" label clearly
          if (val.length > 15) return val.substring(0, 12) + '...'
          return val
        },
      },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      name: 'Value',
      min: yMin - yPad,
      max: yMax + yPad,
      nameTextStyle: { color: tc, fontSize: 12, fontWeight: 500 },
      axisLabel: { color: tc, fontSize: 11 },
      splitLine: { lineStyle: { type: 'dashed', color: tc + '20' } },
      splitArea: { show: false },
    },
    series: [
      {
        name: 'Box Plot',
        type: 'boxplot',
        data: boxData,
        itemStyle: {
          color: BOX_COLOR + '30',
          borderColor: BOX_COLOR,
          borderWidth: 2,
        },
        emphasis: {
          itemStyle: {
            color: BOX_COLOR + '50',
            borderColor: BOX_COLOR,
            borderWidth: 3,
          },
        },
        tooltip: {
          formatter: (p: any) => {
            const d = p.data
            return `<strong>${p.name}</strong><br/>` +
              `Max: ${d[4].toFixed(4)}<br/>` +
              `Q3: ${d[3].toFixed(4)}<br/>` +
              `Median: ${d[2].toFixed(4)}<br/>` +
              `Q1: ${d[1].toFixed(4)}<br/>` +
              `Min: ${d[0].toFixed(4)}`
          },
        },
      },
      {
        name: 'Outliers',
        type: 'scatter',
        data: outlierData,
        itemStyle: { color: '#EE6666', opacity: 0.8 },
        symbolSize: 7,
        symbol: 'circle',
        tooltip: { formatter: (p: any) => `异常值: ${p.value[1].toFixed(4)}` },
      },
      ...jitterSeries,
    ],
  }
}

const { chartRef } = useChart(buildOption, [() => props.data, () => props.title, () => props.showJitter])
void chartRef // bound to <div ref="chartRef"> in template
</script>

<style scoped>
.chart-container { width: 100%; height: 100%; min-height: 400px; }
</style>
