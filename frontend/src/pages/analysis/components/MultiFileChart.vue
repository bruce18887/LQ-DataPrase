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

/** 智能格式化 X 轴刻度：整数不显示小数，非整数最多 2 位 */
function formatAxisValue(v: number): string {
  if (Number.isInteger(v)) return v.toString()
  const s = v.toFixed(2)
  return s.replace(/\.?0+$/, '')
}

function buildOption() {
  const r = props.lotData
  if (!r || !Array.isArray(r.lot_data) || r.lot_data.length === 0) return {}
  const tc = colors.value.textColor
  const lots: any[] = r.lot_data
  const showLimit = props.chartConfig.includes('limit')
  const binCenters: number[] = r.bin_centers || []

  const series: any[] = []
  const legendData: string[] = []

  for (const lot of lots) {
    const dn = displayName(lot)
    legendData.push(dn)
    series.push({
      name: dn,
      type: 'bar',
      data: lot.bar_data,
      itemStyle: { color: lot.color },
      barWidth: `${props.barWidthPercent}%`,
      barGap: '10%',
    })
  }

  // Limit 线：合并相同值，简化标注
  const mk: any[] = []
  if (showLimit) {
    // 按值合并 USL/LSL
    const uslMap = new Map<number, any[]>()
    const lslMap = new Map<number, any[]>()
    for (const lot of lots) {
      if (lot.upper_limit != null) {
        const key = Number(lot.upper_limit.toFixed(6))
        const arr = uslMap.get(key) || []
        arr.push(lot)
        uslMap.set(key, arr)
      }
      if (lot.lower_limit != null) {
        const key = Number(lot.lower_limit.toFixed(6))
        const arr = lslMap.get(key) || []
        arr.push(lot)
        lslMap.set(key, arr)
      }
    }
    for (const [value, limitLots] of uslMap) {
      const label = lots.length > 1
        ? `USL=${formatAxisValue(value)}`
        : `${displayName(limitLots[0])} USL=${formatAxisValue(value)}`
      mk.push({
        xAxis: value,
        lineStyle: { color: limitLots[0].color, width: 2, type: 'dashed' },
        label: { show: true, formatter: label, position: 'end', color: limitLots[0].color, fontSize: 10 },
      })
    }
    for (const [value, limitLots] of lslMap) {
      const label = lots.length > 1
        ? `LSL=${formatAxisValue(value)}`
        : `${displayName(limitLots[0])} LSL=${formatAxisValue(value)}`
      mk.push({
        xAxis: value,
        lineStyle: { color: limitLots[0].color, width: 2, type: 'dashed' },
        label: { show: true, formatter: label, position: 'end', color: limitLots[0].color, fontSize: 10 },
      })
    }
  }
  if (mk.length) {
    series.push({ name: '规格限', type: 'line', data: [], markLine: { symbol: 'none', precision: 4, data: mk } })
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
    grid: { top: 50, bottom: 50, left: 55, right: 40 },
    xAxis: {
      type: 'value',
      min: binCenters.length > 0 ? binCenters[0] : r.chart_min,
      max: binCenters.length > 0 ? binCenters[binCenters.length - 1] : r.chart_max,
      axisLabel: {
        rotate: 0,
        show: true,
        interval: 'auto',
        fontSize: 10,
        formatter: formatAxisValue,
        color: tc,
      },
      splitNumber: 10,
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
