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

const BOX_COLORS = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#5383e0']

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
  // Track non-outlier range for Y-axis
  let yMin = Infinity, yMax = -Infinity

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
      yMin = Math.min(yMin, stats.min)
      yMax = Math.max(yMax, stats.max)

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
          itemStyle: { color: BOX_COLORS[idx % BOX_COLORS.length], opacity: 0.25 },
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
      const jittered = overall.raw_values.map((v: number) => [
        (Math.random() - 0.5) * 0.3,
        v,
      ])
      jitterSeries.push({
        name: '数据点',
        type: 'scatter',
        data: jittered,
        symbolSize: 3,
        itemStyle: { color: '#5470c6', opacity: 0.25 },
        silent: true,
      })
    }
  }

  // Y-axis padding: 10% margin on each side of non-outlier range
  const yRange = yMax - yMin
  const yPad = yRange > 0 ? yRange * 0.1 : Math.abs(yMax) * 0.1 || 1
  const yAxisMin = yMin - yPad
  const yAxisMax = yMax + yPad

  const fmt = (v: number) => v.toFixed(4)

  // Boxplot series per category (colored individually)
  const boxSeries = categories.map((cat, idx) => ({
    name: cat,
    type: 'boxplot',
    data: [boxData[idx]],
    itemStyle: {
      color: BOX_COLORS[idx % BOX_COLORS.length] + '30',
      borderColor: BOX_COLORS[idx % BOX_COLORS.length],
      borderWidth: 2,
    },
    emphasis: {
      itemStyle: {
        color: BOX_COLORS[idx % BOX_COLORS.length] + '50',
        borderColor: BOX_COLORS[idx % BOX_COLORS.length],
        borderWidth: 3,
      },
    },
    tooltip: {
      formatter: (p: any) => {
        const d = p.data
        return `<strong>${p.name}</strong><br/>` +
          `<span style="color:${BOX_COLORS[idx % BOX_COLORS.length]}">■</span> Max: ${fmt(d[4])}<br/>` +
          `<span style="color:${BOX_COLORS[idx % BOX_COLORS.length]}">■</span> Q3: ${fmt(d[3])}<br/>` +
          `<span style="color:${BOX_COLORS[idx % BOX_COLORS.length]}">■</span> Median: ${fmt(d[2])}<br/>` +
          `<span style="color:${BOX_COLORS[idx % BOX_COLORS.length]}">■</span> Q1: ${fmt(d[1])}<br/>` +
          `<span style="color:${BOX_COLORS[idx % BOX_COLORS.length]}">■</span> Min: ${fmt(d[0])}`
      },
    },
  }))

  return {
    title: {
      text: props.title || `Box Plot - ${props.data.param}`,
      left: 'center',
      textStyle: { fontSize: 15, fontWeight: '600', color: tc },
    },
    tooltip: { trigger: 'item', axisPointer: { type: 'shadow' } },
    grid: { left: '8%', right: '8%', bottom: '12%', top: '12%', containLabel: true },
    xAxis: {
      type: 'category', data: categories, boundaryGap: true, nameGap: 30,
      splitArea: { show: false },
      axisLine: { lineStyle: { color: tc } },
      axisLabel: { rotate: categories.length > 10 ? 45 : 0, interval: 0, fontSize: 11, color: tc, fontWeight: 500 },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value', name: 'Value',
      min: yAxisMin, max: yAxisMax,
      nameTextStyle: { color: tc, fontSize: 12, fontWeight: 500 },
      axisLabel: { color: tc, fontSize: 11 },
      splitLine: { lineStyle: { type: 'dashed', color: tc + '20' } },
      splitArea: { show: false },
    },
    series: [
      ...boxSeries,
      {
        name: 'Outliers', type: 'scatter', data: outlierData,
        itemStyle: { color: '#EE6666', borderColor: '#EE6666', opacity: 0.8 },
        symbolSize: 7, symbol: 'circle',
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
