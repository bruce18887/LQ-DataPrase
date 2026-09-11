<template>
  <div ref="chartRef" class="chart-container" />
</template>

<script setup lang="ts">
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import { mapLotColorToTheme, buildChartToolbox } from '../../../utils/chart-bar'

const props = defineProps<{
  lotData: any
  fileNames: Record<number, string>
  param?: string
}>()

const { colors, isDark } = useEChartsTheme()

function lotThemeColor(lot: any): string {
  return mapLotColorToTheme(lot.color, isDark.value)
}

function displayName(lot: any): string {
  return props.fileNames[lot.file_id] || lot.name || `File ${lot.file_id}`
}

function buildOption() {
  const r = props.lotData
  if (!r || !Array.isArray(r.lot_data) || r.lot_data.length === 0) return {}
  const tc = colors.value.textColor
  const lots: any[] = r.lot_data

  // boxplot data: [min, Q1, median, Q3, max] per file
  const boxData = lots.map((lot: any) => [
    lot.min_v ?? 0, lot.q1 ?? 0, lot.median ?? 0, lot.q3 ?? 0, lot.max_v ?? 0,
  ])
  const categories = lots.map((lot: any) => displayName(lot))

  return {
    tooltip: {
      trigger: 'item',
      backgroundColor: colors.value.tooltipBg,
      borderColor: colors.value.tooltipBorder,
      textStyle: { color: colors.value.tooltipText },
      formatter: (params: any) => {
        const d = params.data
        if (!d || !d.value) return ''
        const [min, q1, med, q3, max] = d.value
        return `<b>${params.name}</b><br/>Max: ${max}<br/>Q3: ${q3}<br/>Median: ${med}<br/>Q1: ${q1}<br/>Min: ${min}`
      },
    },
    toolbox: buildChartToolbox({ name: `${props.param ?? '多文件'}_箱线图对比` }),
    grid: { top: 20, bottom: 40, left: 100, right: 30 },
    xAxis: {
      type: 'value',
      axisLabel: { color: tc, fontSize: 10 },
      axisLine: { lineStyle: { color: colors.value.axisLineColor } },
      splitLine: { lineStyle: { color: colors.value.axisLineColor, opacity: 0.15 } },
    },
    yAxis: {
      type: 'category',
      data: categories,
      axisLabel: { color: tc, fontSize: 11 },
      axisLine: { lineStyle: { color: colors.value.axisLineColor } },
    },
    series: [{
      type: 'boxplot',
      data: boxData.map((d: number[], i: number) => ({
        value: d,
        itemStyle: {
          color: lotThemeColor(lots[i]) + '33',  // 20% opacity fill
          borderColor: lotThemeColor(lots[i]),
          borderWidth: 2,
        },
      })),
      boxWidth: [12, 24],
    }],
  }
}

const { chartRef } = useChart(buildOption, [
  () => props.lotData,
  () => props.fileNames,
])
void chartRef
</script>

<style scoped>
.chart-container { width: 100%; height: 100%; min-height: 200px; }
</style>
