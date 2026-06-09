<template>
  <div ref="chartRef" class="chart-container" style="width: 100%; height: 500px" />
</template>

<script setup lang="ts">
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'

interface BoxPlotStats {
  min: number; q1: number; median: number; q3: number; max: number; outliers: number[]; count: number
}
interface BoxPlotData {
  param: string; overall?: BoxPlotStats; by_site?: Record<string, BoxPlotStats>; by_bin?: Record<string, BoxPlotStats>
}

const props = defineProps<{ data: BoxPlotData | null; title?: string }>()
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
    })
  } else if (overall) {
    categories = [props.data.param]
    boxData.push([overall.min, overall.q1, overall.median, overall.q3, overall.max])
    overall.outliers.forEach(o => outlierData.push([0, o]))
  }

  const fmt = (v: number) => v.toFixed(4)
  return {
    title: { text: props.title || `Box Plot - ${props.data.param}`, left: 'center', textStyle: { fontSize: 16, fontWeight: 'bold' } },
    tooltip: {
      trigger: 'item', axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        if (params.seriesName === 'Outliers') return `Outlier: ${params.value[1].toFixed(4)}`
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
        tooltip: {
          formatter: (p: any) =>
            `<strong>${p.name}</strong><br/>Max: ${fmt(p.data[5])}<br/>Q3: ${fmt(p.data[4])}<br/>Median: ${fmt(p.data[3])}<br/>Q1: ${fmt(p.data[2])}<br/>Min: ${fmt(p.data[1])}`,
        },
      },
      { name: 'Outliers', type: 'scatter', data: outlierData, itemStyle: { color: '#EE6666' }, symbolSize: 6 },
    ],
  }
}

const { chartRef } = useChart(buildOption, [() => props.data, () => props.title])
void chartRef // bound to <div ref="chartRef"> in template
</script>

<style scoped>
.chart-container { width: 100%; height: 100%; min-height: 400px; }
</style>
