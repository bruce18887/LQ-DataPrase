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

  if (hasGroupedData) {
    categories = Object.keys(groupedData).sort((a, b) => {
      const numA = parseFloat(a); const numB = parseFloat(b)
      if (!isNaN(numA) && !isNaN(numB)) return numA - numB
      return a.localeCompare(b)
    })
    categories.forEach((group, idx) => {
      const stats = groupedData[group]
      boxData.push([stats.min, stats.q1, stats.median, stats.q3, stats.max])
      stats.outliers.forEach(o => outlierData.push([idx, o]))

      // Jitter overlay
      if (props.showJitter && stats.raw_values && stats.raw_values.length > 0) {
        const jittered = stats.raw_values.map((v: number) => [
          idx + (Math.random() - 0.5) * 0.3,
          v,
        ])
        jitterSeries.push({
          name: `${group} 数据点`,
          type: 'scatter',
          data: jittered,
          symbolSize: 3,
          itemStyle: { color: '#73c0de', opacity: 0.35 },
          silent: true,
        })
      }
    })
  } else if (overall) {
    categories = [props.data.param]
    boxData.push([overall.min, overall.q1, overall.median, overall.q3, overall.max])
    overall.outliers.forEach(o => outlierData.push([0, o]))

    // Jitter overlay for single category
    if (props.showJitter && overall.raw_values && overall.raw_values.length > 0) {
      const jittered = overall.raw_values.map((v: number) => [
        (Math.random() - 0.5) * 0.3,
        v,
      ])
      jitterSeries.push({
        name: '数据点',
        type: 'scatter',
        data: jittered,
        symbolSize: 3,
        itemStyle: { color: '#73c0de', opacity: 0.35 },
        silent: true,
      })
    }
  }

  // Q1/Q3 markPoint annotations
  const markPointData: any[] = []
  boxData.forEach((d, idx) => {
    markPointData.push(
      { coord: [idx, d[1]], value: `Q1:${d[1].toFixed(4)}`, symbol: 'none', label: { show: true, position: 'left', fontSize: 10, color: tc } },
      { coord: [idx, d[3]], value: `Q3:${d[3].toFixed(4)}`, symbol: 'none', label: { show: true, position: 'left', fontSize: 10, color: tc } },
    )
  })

  const fmt = (v: number) => v.toFixed(4)
  return {
    title: { text: props.title || `Box Plot - ${props.data.param}`, left: 'center', textStyle: { fontSize: 16, fontWeight: 'bold', color: tc } },
    tooltip: {
      trigger: 'item', axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        if (params.seriesName === 'Outliers' || params.seriesName.includes('数据点')) return `数值: ${params.value[1].toFixed(4)}`
        const d = params.value
        return `<strong>${params.name}</strong><br/>Max: ${fmt(d[5])}<br/>Q3: ${fmt(d[4])}<br/>Median: ${fmt(d[3])}<br/>Q1: ${fmt(d[2])}<br/>Min: ${fmt(d[1])}`
      },
    },
    grid: { left: '10%', right: '10%', bottom: '15%', containLabel: true },
    xAxis: {
      type: 'category', data: categories, boundaryGap: true, nameGap: 30, splitArea: { show: false },
      axisLabel: { rotate: categories.length > 10 ? 45 : 0, interval: 0, fontSize: 10, color: tc },
      splitLine: { show: false },
    },
    yAxis: { type: 'value', name: 'Value', nameTextStyle: { color: tc }, axisLabel: { color: tc }, splitArea: { show: true } },
    series: [
      {
        name: 'Box Plot', type: 'boxplot', data: boxData,
        itemStyle: { color: '#5470C6', borderColor: tc },
        markPoint: { data: markPointData, animation: false },
        tooltip: {
          formatter: (p: any) =>
            `<strong>${p.name}</strong><br/>Max: ${fmt(p.data[4])}<br/>Q3: ${fmt(p.data[3])}<br/>Median: ${fmt(p.data[2])}<br/>Q1: ${fmt(p.data[1])}<br/>Min: ${fmt(p.data[0])}`,
        },
      },
      { name: 'Outliers', type: 'scatter', data: outlierData, itemStyle: { color: '#EE6666' }, symbolSize: 6 },
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
