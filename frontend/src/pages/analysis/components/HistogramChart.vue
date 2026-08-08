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

function buildBarData(
  activeIndices: number[],
  binCenters: number[],
  values: number[],
): number[][] {
  return activeIndices.map((i: number) => [binCenters[i], values[i] ?? 0])
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
  // 将裁剪边界扩展到规格限，保证 LSL/USL 内部的 bin 始终可见，
  // 同时让 X 轴范围保持与未裁剪时一致。
  if (shouldClip && props.rangeType === 'RDL' && r.lower_limit != null && r.upper_limit != null) {
    clipMin = Math.min(clipMin, r.lower_limit)
    clipMax = Math.max(clipMax, r.upper_limit)
  }

  let activeIndices = binCenters
    .map((c: number, i: number) => (c >= clipMin && c <= clipMax ? i : -1))
    .filter((i: number) => i >= 0)

  // Guard against pathological bounds that exclude every bin.
  if (activeIndices.length === 0) {
    activeIndices = binCenters.map((_: number, i: number) => i)
  }

  const series: any[] = []
  const siteHists = r.site_histograms
  const siteKeys = siteHists ? Object.keys(siteHists) : []
  const hasSiteData = siteKeys.length >= 1
  const showNormal = props.chartConfig.includes('normal')
  // 正态曲线数据统一来自后端 result（normal_curve / filtered_normal_curve，
  // 公式单一来源在后端），与 KDE/标记线同源原则一致——前端不再本地实现高斯公式
  const normalCurve = shouldClip && r.filtered_normal_curve != null ? r.filtered_normal_curve : r.normal_curve
  const hasNormal = showNormal && Array.isArray(normalCurve) && normalCurve.length > 1
  const hasKde = props.chartConfig.includes('kde') && Array.isArray(r.kde_curve) && r.kde_curve.length > 1
  // Density axes are independent: KDE gets its own purple axis on the far
  // left, the normal curve keeps the original orange axis on the right.
  // Base axes are the percent axis plus the optional All Site axis; axis
  // indexes are assigned in build order (KDE first) so each series binds
  // to its own axis and each axis only exists while its toggle is on.
  const baseAxisCount = 1 + (hasSiteData ? 1 : 0)
  const kdeAxisIdx = hasKde ? baseAxisCount : -1
  const normalAxisIdx = hasNormal ? baseAxisCount + (hasKde ? 1 : 0) : -1

  if (hasSiteData) {
    const sites = siteKeys.sort((a, b) => Number(a) - Number(b))
    for (let idx = 0; idx < sites.length; idx++) {
      const site = sites[idx]
      const hists: number[] = siteHists[site] || []
      series.push({
        name: `Site${site}`, type: 'bar',
        data: buildBarData(activeIndices, binCenters, hists),
        itemStyle: { color: COLORS_SITE_8[idx % COLORS_SITE_8.length] },
        barWidth: `${props.barWidthPercent}%`,
      })
    }
    series.push({
      name: 'All Site', type: 'bar', yAxisIndex: 1,
      data: buildBarData(activeIndices, binCenters, r.bin_percentages || []),
      itemStyle: { color: '#90CAF9', opacity: 0.5 }, barWidth: `${props.barWidthPercent}%`,
      label: { show: true, position: 'top', formatter: (p: any) => p.data[1] > 0 ? `${p.data[1].toFixed(2)}%` : '', fontSize: 10, color: '#1565C0', fontWeight: 'bold' },
    })
  } else {
    series.push({
      name: '数据分布', type: 'bar',
      data: buildBarData(activeIndices, binCenters, r.bin_percentages || []),
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
  // CL 模式：画出用户自定义规格限线（数据来自后端 result，与 LSL/USL 一致）
  if (props.rangeType === 'CL' && r.custom_low != null && r.custom_high != null) {
    mk.push(
      { xAxis: r.custom_low, lineStyle: { color: '#43A047', width: 2, type: 'dashed' }, label: { show: true, formatter: 'CL Low', position: 'insideEndTop' } },
      { xAxis: r.custom_high, lineStyle: { color: '#43A047', width: 2, type: 'dashed' }, label: { show: true, formatter: 'CL High', position: 'insideEndTop' } },
    )
  }
  // σ 标记线与统计卡同一口径：裁剪时用后端 filtered_sigma*（与 filtered_mean/
  // std 同源），否则用全量 sigma*。此前卡片用裁剪值、线用全量值，界面矛盾
  const s3Min = shouldClip && r.filtered_sigma3_min != null ? r.filtered_sigma3_min : r.sigma3_min
  const s3Max = shouldClip && r.filtered_sigma3_max != null ? r.filtered_sigma3_max : r.sigma3_max
  const s4Min = shouldClip && r.filtered_sigma4_min != null ? r.filtered_sigma4_min : r.sigma4_min
  const s4Max = shouldClip && r.filtered_sigma4_max != null ? r.filtered_sigma4_max : r.sigma4_max
  const s6Min = shouldClip && r.filtered_sigma6_min != null ? r.filtered_sigma6_min : r.sigma6_min
  const s6Max = shouldClip && r.filtered_sigma6_max != null ? r.filtered_sigma6_max : r.sigma6_max
  if (props.chartConfig.includes('s3') && s3Min != null && s3Max != null) {
    mk.push(
      { xAxis: s3Min, lineStyle: { color: '#1565C0', width: 3, type: 'dotted' }, label: { show: true, formatter: '3σ下限', position: 'insideEndTop' } },
      { xAxis: s3Max, lineStyle: { color: '#1565C0', width: 3, type: 'dotted' }, label: { show: true, formatter: '3σ上限', position: 'insideEndTop' } },
    )
  }
  if (props.chartConfig.includes('s4') && s4Min != null && s4Max != null) {
    mk.push(
      { xAxis: s4Min, lineStyle: { color: '#00838F', width: 3, type: 'dotted' }, label: { show: true, formatter: '4σ下限', position: 'insideEndTop' } },
      { xAxis: s4Max, lineStyle: { color: '#00838F', width: 3, type: 'dotted' }, label: { show: true, formatter: '4σ上限', position: 'insideEndTop' } },
    )
  }
  if (props.chartConfig.includes('s6') && s6Min != null && s6Max != null) {
    mk.push(
      { xAxis: s6Min, lineStyle: { color: '#E65100', width: 3, type: 'dotted' }, label: { show: true, formatter: '6σ下限', position: 'insideEndTop' } },
      { xAxis: s6Max, lineStyle: { color: '#E65100', width: 3, type: 'dotted' }, label: { show: true, formatter: '6σ上限', position: 'insideEndTop' } },
    )
  }
  if (mk.length) series.push({ name: '规格限', type: 'line', data: [], markLine: { symbol: 'none', precision: 4, data: mk } })

  if (hasNormal) {
    series.push({ name: '正态分布', type: 'line', data: normalCurve as any[], smooth: true, lineStyle: { color: '#F57F17', width: 3 }, symbol: 'none', yAxisIndex: normalAxisIdx, z: 10 })
  }

  if (hasKde) {
    series.push({ name: 'KDE曲线', type: 'line', data: r.kde_curve, smooth: true, lineStyle: { color: '#7B1FA2', width: 3 }, symbol: 'none', yAxisIndex: kdeAxisIdx, z: 10 })
  }

  const AXIS_COLOR_LEFT = '#1E88E5'; const AXIS_COLOR_ALLSITE = '#42A5F5'; const AXIS_COLOR_NORMAL = '#F57F17'; const AXIS_COLOR_KDE = '#7B1FA2'
  let leftYMax = 100
  if (hasSiteData) {
    let maxVal = 0
    for (const s of Object.keys(siteHists)) for (const v of siteHists[s]) if (v > maxVal) maxVal = v
    leftYMax = Math.ceil(maxVal / 5) * 5 + 5
  }
  const yAxes: any[] = [{ type: 'value', name: '百分比 (%)', nameTextStyle: { color: AXIS_COLOR_LEFT, fontWeight: 'bold' }, position: 'left', min: 0, max: leftYMax, axisLabel: { formatter: '{value}%', color: AXIS_COLOR_LEFT }, axisLine: { show: true, lineStyle: { color: AXIS_COLOR_LEFT } } }]
  if (hasSiteData) yAxes.push({ type: 'value', name: 'All Site (%)', nameTextStyle: { color: AXIS_COLOR_ALLSITE, fontWeight: 'bold' }, position: 'right', min: 0, axisLabel: { formatter: '{value}%', color: AXIS_COLOR_ALLSITE }, axisLine: { show: true, lineStyle: { color: AXIS_COLOR_ALLSITE } }, splitLine: { show: false } })
  if (hasKde) yAxes.push({ type: 'value', name: 'KDE密度', nameTextStyle: { color: AXIS_COLOR_KDE, fontWeight: 'bold' }, position: 'left', offset: 55, min: 0, axisLabel: { formatter: (v: number) => v.toExponential(2), color: AXIS_COLOR_KDE }, axisLine: { show: true, lineStyle: { color: AXIS_COLOR_KDE } }, splitLine: { show: false } })
  if (hasNormal) yAxes.push({ type: 'value', name: '概率密度', nameTextStyle: { color: AXIS_COLOR_NORMAL, fontWeight: 'bold' }, position: 'right', offset: hasSiteData ? 50 : 0, min: 0, axisLabel: { formatter: (v: number) => v.toExponential(2), color: AXIS_COLOR_NORMAL }, axisLine: { show: true, lineStyle: { color: AXIS_COLOR_NORMAL } }, splitLine: { show: false } })

  const unitStr = r.unit || ''
  const limitStr = (r.lower_limit != null && r.upper_limit != null) ? `Limit [${r.lower_limit.toFixed(4)}, ${r.upper_limit.toFixed(4)}]` : ''
  const titleText = `{name|${props.selectedParam}}  {unit|${unitStr ? `(${unitStr})` : ''}}  {limit|${limitStr || ''}}`

  return {
    title: { text: titleText, left: 'center', top: 6, textStyle: { rich: { name: { fontSize: 15, fontWeight: 'bold', color: tc }, unit: { fontSize: 12, color: tc, fontWeight: 500 }, limit: { fontSize: 12, color: '#E65100', fontWeight: 600, backgroundColor: '#FFF3E0', padding: [2, 6], borderRadius: 3 } } } },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const items = Array.isArray(params) ? params : [params]
        const first = items[0]
        const firstX = Array.isArray(first.data) ? first.data[0] : first.data.value?.[0]
        let html = `值: ${Number(firstX).toFixed(4)}<br/>`
        for (const p of items) {
          if (p.seriesName === '规格限' || p.seriesName === '正态分布' || p.seriesName === 'KDE曲线') continue
          const y = Array.isArray(p.data) ? p.data[1] : p.data.value?.[1]
          if (y != null) html += `${p.seriesName}: ${Number(y).toFixed(2)}%<br/>`
        }
        return html
      },
    },
    legend: { data: series.map((s: any) => s.name), top: 'bottom', type: 'scroll', textStyle: { color: tc } },
    toolbox: { feature: { saveAsImage: { name: `${props.selectedParam}_分析` } } },
    grid: { top: 55, bottom: 70, left: hasKde ? 110 : 55, right: (hasSiteData && hasNormal) ? 120 : (hasSiteData || hasNormal) ? 80 : 55 },
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
