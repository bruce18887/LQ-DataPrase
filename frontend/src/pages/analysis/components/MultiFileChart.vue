<template>
  <div ref="chartRef" class="chart-container" />
</template>

<script setup lang="ts">
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'

const props = defineProps<{
  /** /analysis/multi_lot/ 带 param 的响应 */
  lotData: any
  chartConfig: string[]
  barWidthPercent: number
  /** file_id → 自定义图例名 */
  fileNames: Record<number, string>
  selectedParam: string
}>()

const { colors } = useEChartsTheme()

function displayName(lot: any): string {
  return props.fileNames[lot.file_id] || lot.name || `File ${lot.file_id}`
}

function buildOption() {
  const r = props.lotData
  if (!r || !Array.isArray(r.lot_data) || r.lot_data.length === 0) return {}
  const tc = colors.value.textColor
  const lots: any[] = r.lot_data
  const showLimit = props.chartConfig.includes('limit')

  const series: any[] = []
  const legendData: string[] = []

  for (const lot of lots) {
    const dn = displayName(lot)
    legendData.push(dn)
    // 每个文件一组柱：不拆 SITE，独立颜色 + 自定义图例名
    series.push({
      name: dn,
      type: 'bar',
      data: lot.bar_data,
      itemStyle: { color: lot.color },
      barWidth: `${props.barWidthPercent}%`,
      barGap: '10%',
    })

    // 每个文件的 limit 线作为独立图例项（同色虚线），可单独开关
    if (showLimit && lot.lower_limit != null && lot.upper_limit != null) {
      const limitName = `${dn} Limit`
      legendData.push(limitName)
      series.push({
        name: limitName,
        type: 'line',
        data: [],
        color: lot.color,
        markLine: {
          symbol: 'none',
          precision: 4,
          lineStyle: { color: lot.color, type: 'dashed', width: 2 },
          label: {
            show: true,
            color: lot.color,
            fontSize: 10,
            formatter: (p: any) => (p.dataIndex === 0 ? 'L' : 'U'),
          },
          data: [{ xAxis: lot.lower_limit }, { xAxis: lot.upper_limit }],
        },
      })
    }
  }

  const titleText = `${props.selectedParam}  ${r.global_mean != null ? `(μ=${r.global_mean})` : ''}`

  return {
    title: {
      text: titleText,
      left: 'center',
      top: 6,
      textStyle: { fontSize: 15, fontWeight: 'bold', color: tc },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const items = Array.isArray(params) ? params : [params]
        if (!items.length) return ''
        let html = `值: ${Number(items[0].data?.[0]).toFixed(4)}<br/>`
        for (const p of items) {
          if (p.data && p.data[1] != null && p.seriesType === 'bar') {
            html += `${p.seriesName}: ${Number(p.data[1]).toFixed(2)}%<br/>`
          }
        }
        return html
      },
    },
    legend: { data: legendData, top: 'bottom', type: 'scroll', textStyle: { color: tc } },
    toolbox: { feature: { saveAsImage: { name: `${props.selectedParam}_多文件对比` } } },
    grid: { top: 50, bottom: 60, left: 55, right: 40 },
    xAxis: {
      type: 'value',
      min: r.chart_min,
      max: r.chart_max,
      axisLabel: { rotate: 45, fontSize: 9, formatter: (v: number) => v.toFixed(4), color: tc },
      splitNumber: 20,
    },
    yAxis: {
      type: 'value',
      name: '百分比 (%)',
      min: 0,
      nameTextStyle: { color: tc },
      axisLabel: { formatter: '{value}%', color: tc },
    },
    series,
  }
}

const { chartRef } = useChart(buildOption, [
  () => props.lotData,
  () => props.chartConfig,
  () => props.barWidthPercent,
  () => props.fileNames,
  () => props.selectedParam,
])
void chartRef // bound to <div ref="chartRef"> in template
</script>

<style scoped>
.chart-container {
  width: 100%;
  height: 100%;
  min-height: 480px;
}
</style>
