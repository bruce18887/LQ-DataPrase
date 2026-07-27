<template>
  <div class="histogram-chart-wrapper">
    <div ref="chartRef" class="chart-container" />
    <OutlierHintBar
      :mode="outlierHandling || 'off'"
      :outlier-info="result?.outlier_info ?? null"
    />
  </div>
</template>

<script setup lang="ts">
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import OutlierHintBar from './OutlierHintBar.vue'

const props = defineProps<{
  result: any
  chartConfig: string[]
  rangeType: string
  barWidthPercent: number
  selectedParam: string
  outlierHandling?: 'clip' | 'exclude' | 'off'
}>()

const { colors } = useEChartsTheme()
const COLORS_SITE_8 = ['#E53935', '#1E88E5', '#43A047', '#F9A825', '#8E24AA', '#00ACC1', '#F57C00', '#D81B60']
const FAIL_BIN_COLOR = '#E53935'

function isFailBin(center: number, lowerLimit: number | null, upperLimit: number | null): boolean {
  if (lowerLimit != null && center < lowerLimit) return true
  if (upperLimit != null && center > upperLimit) return true
  return false
}

function buildBarData(
  activeIndices: number[],
  binCenters: number[],
  values: number[],
  lowerLimit: number | null,
  upperLimit: number | null,
): (number[] | { value: number[]; itemStyle: { color: string } })[] {
  return activeIndices.map((i: number) => {
    const center = binCenters[i]
    const val = values[i] ?? 0
    if (isFailBin(center, lowerLimit, upperLimit)) {
      return { value: [center, val], itemStyle: { color: FAIL_BIN_COLOR } }
    }
    return [center, val]
  })
}

function buildOption() {
  const r = props.result
  if (!r) return {}
  const tc = colors.value.textColor
  const binCenters: number[] = r.bin_centers || []
  if (binCenters.length === 0) return {}

  // Outlier clipping: keep the X-axis range locked to the original bin_centers
  // span (driven by range_type) so bar widths and Limit lines stay stable.
  // Hide bins whose center falls outside the IQR bounds instead of zooming.
  const outlierInfo = r.outlier_info
  const handlingMode = props.outlierHandling || 'off'
  const xAxisMin = binCenters[0]
  const xAxisMax = binCenters[binCenters.length - 1]

  const shouldClip = handlingMode === 'clip' && outlierInfo?.has_outliers
  let clipMin = shouldClip ? outlierInfo.lower_bound : -Infinity
  let clipMax = shouldClip ? outlierInfo.upper_bound : Infinity

  // RDL 模式下，原始 Limit 线内的数据不应被当作异常值隐藏。
  // 将裁剪边界扩展到规格限，保证 LSL/USL 内部的 bin 始终可见。
  if (shouldClip && props.rangeType === 'RDL' && r.lower_limit != null && r.upper_limit != null) {
    clipMin = Math.min(clipMin, r.lower_limit)
    clipMax = Math.max(clipMax, r.upper_limit)
  }

  // limit 外的 fail bin 必须始终可见（用户需要看到 fail 百分比）。
  // 将裁剪边界扩展到包含 limit 外的所有 bin。
  if (shouldClip && r.lower_limit != null) {
    const minFailBin = binCenters.find((c: number) => c < r.lower_limit)
    if (minFailBin != null) clipMin = Math.min(clipMin, minFailBin)
  }
  if (shouldClip && r.upper_limit != null) {
    for (let i = binCenters.length - 1; i >= 0; i--) {
      if (binCenters[i] > r.upper_limit) { clipMax = Math.max(clipMax, binCenters[i]); break }
    }
  }

  let activeIndices = binCenters
    .map((c: number, i: number) => (c >= clipMin && c <= clipMax ? i : -1))
    .filter((i: number) => i >= 0)

  // Guard against pathological bounds that exclude every bin.
  if (activeIndices.length === 0) {
    activeIndices = binCenters.map((_: number, i: number) => i)
  }
  const filteredBinCenters = activeIndices.map((i: number) => binCenters[i])

  const series: any[] = []
  const siteHists = r.site_histograms
  const siteKeys = siteHists ? Object.keys(siteHists) : []
  const hasSiteData = siteKeys.length >= 1
  const showNormal = props.chartConfig.includes('normal')
  const hasNormal = showNormal && r.std > 0

  if (hasSiteData) {
    const sites = siteKeys.sort((a, b) => Number(a) - Number(b))
    for (let idx = 0; idx < sites.length; idx++) {
      const site = sites[idx]
      const hists: number[] = siteHists[site] || []
      series.push({
        name: `Site${site}`, type: 'bar',
        data: buildBarData(activeIndices, binCenters, hists, r.lower_limit, r.upper_limit),
        itemStyle: { color: COLORS_SITE_8[idx % COLORS_SITE_8.length] },
        barWidth: `${props.barWidthPercent}%`,
      })
    }
    series.push({
      name: 'All Site', type: 'bar', yAxisIndex: 1,
      data: buildBarData(activeIndices, binCenters, r.bin_percentages || [], r.lower_limit, r.upper_limit),
      itemStyle: { color: '#90CAF9', opacity: 0.5 }, barWidth: `${props.barWidthPercent}%`,
      label: { show: true, position: 'top', formatter: (p: any) => p.data[1] > 0 ? `${p.data[1].toFixed(2)}%` : '', fontSize: 10, color: '#1565C0', fontWeight: 'bold' },
    })
  } else {
    series.push({
      name: '数据分布', type: 'bar',
      data: buildBarData(activeIndices, binCenters, r.bin_percentages || [], r.lower_limit, r.upper_limit),
      itemStyle: { color: '#1E88E5' }, barWidth: `${props.barWidthPercent}%`,
    })
  }

  const mk: any[] = []
  const showLimit = props.chartConfig.includes('limit')
  if (showLimit && r.lower_limit != null && r.upper_limit != null) {
    mk.push(
      { xAxis: r.lower_limit, lineStyle: { color: '#C62828', width: 3, type: 'dashed' }, label: { show: true, formatter: 'LSL', position: 'end' } },
      { xAxis: r.upper_limit, lineStyle: { color: '#C62828', width: 3, type: 'dashed' }, label: { show: true, formatter: 'USL', position: 'end' } },
    )
  }
  if (props.chartConfig.includes('s3') && r.sigma3_min != null && r.sigma3_max != null) {
    mk.push(
      { xAxis: r.sigma3_min, lineStyle: { color: '#1565C0', width: 3, type: 'dotted' }, label: { show: true, formatter: '3σ下限', position: 'insideEndTop' } },
      { xAxis: r.sigma3_max, lineStyle: { color: '#1565C0', width: 3, type: 'dotted' }, label: { show: true, formatter: '3σ上限', position: 'insideEndTop' } },
    )
  }
  if (props.chartConfig.includes('s4') && r.std > 0) {
    mk.push(
      { xAxis: r.mean - 4 * r.std, lineStyle: { color: '#00838F', width: 3, type: 'dotted' }, label: { show: true, formatter: '4σ下限', position: 'insideEndTop' } },
      { xAxis: r.mean + 4 * r.std, lineStyle: { color: '#00838F', width: 3, type: 'dotted' }, label: { show: true, formatter: '4σ上限', position: 'insideEndTop' } },
    )
  }
  if (props.chartConfig.includes('s6') && r.sigma6_min != null && r.sigma6_max != null) {
    mk.push(
      { xAxis: r.sigma6_min, lineStyle: { color: '#E65100', width: 3, type: 'dotted' }, label: { show: true, formatter: '6σ下限', position: 'insideEndTop' } },
      { xAxis: r.sigma6_max, lineStyle: { color: '#E65100', width: 3, type: 'dotted' }, label: { show: true, formatter: '6σ上限', position: 'insideEndTop' } },
    )
  }
  if (mk.length) series.push({ name: '规格限', type: 'line', data: [], markLine: { symbol: 'none', precision: 4, data: mk } })

  if (hasNormal) {
    const binGap = filteredBinCenters.length > 1 ? Math.abs(filteredBinCenters[1] - filteredBinCenters[0]) : 1
    const pdfFn = (x: number) => (1 / (r.std * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * ((x - r.mean) / r.std) ** 2)
    let xVals: number[]
    if (r.std < binGap) {
      const extra: number[] = [r.mean]
      for (let k = 1; k <= 6; k++) extra.push(r.mean - k * r.std, r.mean + k * r.std)
      xVals = [...filteredBinCenters, ...extra].sort((a, b) => a - b)
    } else { xVals = filteredBinCenters }
    series.push({ name: '正态分布', type: 'line', data: xVals.map((x: number) => [x, pdfFn(x)]), smooth: true, lineStyle: { color: '#F57F17', width: 3 }, symbol: 'none', yAxisIndex: hasSiteData ? 2 : 1, z: 10 })
  }

  const AXIS_COLOR_LEFT = '#1E88E5'; const AXIS_COLOR_ALLSITE = '#42A5F5'; const AXIS_COLOR_NORMAL = '#F57F17'
  let leftYMax = 100
  if (hasSiteData) {
    let maxVal = 0
    for (const s of Object.keys(siteHists)) for (const v of siteHists[s]) if (v > maxVal) maxVal = v
    leftYMax = Math.ceil(maxVal / 5) * 5 + 5
  }
  const yAxes: any[] = [{ type: 'value', name: '百分比 (%)', nameTextStyle: { color: AXIS_COLOR_LEFT, fontWeight: 'bold' }, position: 'left', min: 0, max: leftYMax, axisLabel: { formatter: '{value}%', color: AXIS_COLOR_LEFT }, axisLine: { show: true, lineStyle: { color: AXIS_COLOR_LEFT } } }]
  if (hasSiteData) yAxes.push({ type: 'value', name: 'All Site (%)', nameTextStyle: { color: AXIS_COLOR_ALLSITE, fontWeight: 'bold' }, position: 'right', min: 0, axisLabel: { formatter: '{value}%', color: AXIS_COLOR_ALLSITE }, axisLine: { show: true, lineStyle: { color: AXIS_COLOR_ALLSITE } }, splitLine: { show: false } })
  if (hasNormal) yAxes.push({ type: 'value', name: '概率密度', nameTextStyle: { color: AXIS_COLOR_NORMAL, fontWeight: 'bold' }, position: 'right', offset: hasSiteData ? 50 : 0, min: 0, axisLabel: { formatter: (v: number) => v.toExponential(2), color: AXIS_COLOR_NORMAL }, axisLine: { show: true, lineStyle: { color: AXIS_COLOR_NORMAL } }, splitLine: { show: false } })

  const unitStr = r.unit || ''
  const limitStr = (r.lower_limit != null && r.upper_limit != null) ? `Limit [${r.lower_limit.toFixed(4)}, ${r.upper_limit.toFixed(4)}]` : ''
  const titleText = `{name|${props.selectedParam}}  {unit|${unitStr ? `(${unitStr})` : ''}}  {limit|${limitStr || ''}}`

  return {
    title: { text: titleText, left: 'center', top: 6, textStyle: { rich: { name: { fontSize: 15, fontWeight: 'bold', color: tc }, unit: { fontSize: 12, color: tc, fontWeight: 500 }, limit: { fontSize: 12, color: '#E65100', fontWeight: 600, backgroundColor: '#FFF3E0', padding: [2, 6], borderRadius: 3 } } } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (params: any) => { const items = Array.isArray(params) ? params : [params]; let html = `值: ${Number(items[0].data[0]).toFixed(4)}<br/>`; for (const p of items) if (p.seriesName !== '规格限' && p.seriesName !== '正态分布' && p.data[1] != null) html += `${p.seriesName}: ${Number(p.data[1]).toFixed(2)}%<br/>`; return html } },
    legend: { data: series.map((s: any) => s.name), top: 'bottom', type: 'scroll', textStyle: { color: tc } },
    toolbox: { feature: { saveAsImage: { name: `${props.selectedParam}_分析` } } },
    grid: { top: 55, bottom: 70, left: 55, right: (hasSiteData && hasNormal) ? 120 : (hasSiteData || hasNormal) ? 80 : 55 },
    xAxis: { type: 'value', name: '', nameLocation: 'middle', nameGap: 28, min: xAxisMin, max: xAxisMax, axisLabel: { rotate: 45, show: true, interval: 0, fontSize: 9, formatter: (v: number) => v.toFixed(4), color: tc }, splitNumber: 24 },
    yAxis: yAxes,
    series,
  }
}

const { chartRef } = useChart(buildOption, [() => props.result, () => props.chartConfig, () => props.rangeType, () => props.barWidthPercent, () => props.selectedParam, () => props.outlierHandling])
void chartRef // bound to <div ref="chartRef"> in template
</script>

<style scoped>
.histogram-chart-wrapper {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.chart-container {
  flex: 1;
  min-height: 0;
  width: 100%;
}

.outlier-hint-bar {
  flex-shrink: 0;
}
</style>
