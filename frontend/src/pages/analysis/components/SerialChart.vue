<template>
  <div class="serial-chart-wrapper">
    <div ref="chartRef" style="height: 450px" />
    <OutlierHintBar
      :mode="outlierHandling || 'off'"
      :outlier-info="data?.outlier_info ?? null"
    />
  </div>
</template>

<script setup lang="ts">
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import OutlierHintBar from './OutlierHintBar.vue'

const props = defineProps<{
  data: any
  outlierHandling?: 'clip' | 'exclude' | 'off'
}>()
const { colors } = useEChartsTheme()

const SITE_COLORS = [
  '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
  '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#5383e0',
]

function buildOption() {
  if (!props.data) return {}
  const tc = colors.value.textColor
  const d = props.data
  const param = d.param || ''
  const unit = d.unit || ''
  const serialCol = d.serial_col || 'Serial'
  const continuousSerials = d.continuous_serials || []

  const series: any[] = (d.series_data || []).map(
    (sd: { name: string; data: number[][]; type?: string; symbolSize?: number }, idx: number) => ({
      name: sd.name, type: sd.type || 'scatter', data: sd.data,
      symbolSize: sd.symbolSize || 6, itemStyle: { color: SITE_COLORS[idx % SITE_COLORS.length] },
    }),
  )

  for (const mark of d.marks || []) {
    series.push({ name: mark.name, type: mark.type || 'scatter', data: mark.data || [], markLine: mark.markLine, silent: true })
  }

  let subtext = unit ? `Unit: ${unit}` : ''
  if (d.lower_limit != null && d.upper_limit != null) {
    subtext += ` [${d.lower_limit.toFixed(4)}, ${d.upper_limit.toFixed(4)}]`
  }

  // Apply outlier clipping to y-axis
  const outlierInfo = d.outlier_info
  const handlingMode = props.outlierHandling || 'off'
  let yAxisMin = d.y_min
  let yAxisMax = d.y_max

  if (handlingMode === 'clip' && outlierInfo?.has_outliers) {
    yAxisMin = outlierInfo.lower_bound
    yAxisMax = outlierInfo.upper_bound
    const pad = (yAxisMax - yAxisMin) * 0.1
    yAxisMin -= pad
    yAxisMax += pad
  }

  return {
    title: { text: `${param} Serial分布`, subtext, left: 'center', subtextStyle: { fontSize: 12 } },
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => `${p.seriesName}<br/>${serialCol}: ${p.value[0]}<br/>Value: ${Number(p.value[1]).toFixed(4)}`,
    },
    legend: { data: series.map((s: any) => s.name), top: 'bottom', type: 'scroll', textStyle: { color: tc } },
    toolbox: { feature: { saveAsImage: { name: `${param}_Serial分布` } } },
    xAxis: {
      type: 'category', data: continuousSerials, name: serialCol,
      nameTextStyle: { color: tc }, nameLocation: 'middle', nameGap: 30,
      axisLabel: { rotate: 45, interval: 'auto', color: tc },
    },
    yAxis: {
      type: 'value', name: unit ? `${param} (${unit})` : param,
      nameTextStyle: { color: tc }, nameLocation: 'middle', nameGap: 40,
      min: yAxisMin, max: yAxisMax, axisLabel: { formatter: (v: number) => v.toFixed(4), color: tc },
    },
    dataZoom: [
      { type: 'slider', xAxisIndex: 0, start: 0, end: 100 },
      { type: 'inside', xAxisIndex: 0 },
    ],
    series,
  }
}

const { chartRef } = useChart(buildOption, [() => props.data, () => props.outlierHandling])
void chartRef // bound to <div ref="chartRef"> in template
</script>
