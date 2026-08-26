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
import { clampBarValue, formatPercent, formatAxisValue, getBarGroupPad, getMaxBarWidthPercent, getSiteColors8 } from '../../../utils/chart-bar'
import OutlierHintBar from './OutlierHintBar.vue'

const props = withDefaults(defineProps<{
  result: any
  chartConfig: string[]
  rangeType: string
  barWidthPercent: number
  /** 柱体重合度 0-100（barGap 负值）：重合越高柱组越窄、柱宽上限越高 */
  barOverlapPercent?: number
  selectedParam: string
  outlierHandling?: 'clip' | 'exclude' | 'off'
}>(), {
  barOverlapPercent: 5,
})

const { colors, isDark } = useEChartsTheme()

/**
 * 柱数据 [x, 渲染值, 真实值, 计数]：非零小百分比（如 0.002%）钳制到最小
 * 可见柱高（clampBarValue），真实值存 data[2] 供 tooltip/标签显示，data[3]
 * 为可选计数（bin_counts，仅 数据分布/All Site 系列传入，与百分比同源）。
 */
function buildBarData(
  activeIndices: number[],
  binCenters: number[],
  values: number[],
  counts?: number[],
): number[][] {
  return activeIndices.map((i: number) => {
    const v = values[i] ?? 0
    return [binCenters[i], clampBarValue(v), v, counts?.[i] ?? 0]
  })
}

function buildOption() {
  const r = props.result
  if (!r) return {}
  const tc = colors.value.textColor
  // 轴/曲线辅助色（2026-08-26 夜晚可视度修复）：light 保持直方图基准常量，
  // night 用 Material 300 级提亮——#1E88E5/#7B1FA2 等 500/700 级在深底对比度不足
  const AXIS = isDark.value
    ? { left: '#64B5F6', allsite: '#90CAF9', normal: '#FFA726', kde: '#BA68C8' }
    : { left: '#1E88E5', allsite: '#42A5F5', normal: '#F57F17', kde: '#7B1FA2' }
  // σ 标记线：light 原常量；night 提亮（标签跟随线色，深蓝/深青在深底不可读）
  const s3c = isDark.value ? '#64B5F6' : '#1565C0'
  const s4c = isDark.value ? '#4DD0E1' : '#00838F'
  const s6c = isDark.value ? '#FFB74D' : '#E65100'
  const binCenters: number[] = r.bin_centers || []
  if (binCenters.length === 0) return {}

  const siteHists = r.site_histograms
  const siteKeys = siteHists ? Object.keys(siteHists) : []
  const hasSiteData = siteKeys.length >= 1
  // Outlier clipping: keep the X-axis range locked to the original bin_centers
  // span (driven by range_type) so bar widths and Limit lines stay stable.
  // Hide bins whose center falls outside the IQR bounds instead of zooming.
  const outlierInfo = r.outlier_info
  const handlingMode = props.outlierHandling || 'off'
  // 轴 min/max 向两端扩展多系列 bar 分组偏移量（getBarGroupPad）：8 个 Site 系列 +
  // All Site 在同一 value 轴上分组错位，最右系列（AllSite）最右 bin 柱体（x=
  // bin_centers[-1]）与最左系列（SITE1）underflow 柱体（x=bin_centers[0]）会被挤出
  // 绘图区整根裁剪（回归：edge-clip，tooltip 有值但柱体/label 消失）。扩展仅两端
  // 多出空边距，bar 宽度语义、markLine 与 outlier clip 过滤均不受影响。
  const binGap = binCenters.length >= 2 ? binCenters[1] - binCenters[0] : 0
  const seriesCount = hasSiteData ? siteKeys.length + 1 : 1
  // 柱宽上限：N 系列柱组总宽必须 ≤ bin 宽，否则柱组横跨 bin 边界、
  // 贴限 bin（右边界=USL）的 pass 柱会被画到 USL 右侧（回归：limit-line-cross）。
  // 重合度越高（barGap 负值）柱组越窄，柱宽上限越高。
  const effectiveBarWidth = Math.min(props.barWidthPercent, getMaxBarWidthPercent(seriesCount, props.barOverlapPercent))
  const axisPad = getBarGroupPad(seriesCount, binGap, effectiveBarWidth)
  const xAxisMin = binCenters[0] - axisPad
  const xAxisMax = binCenters[binCenters.length - 1] + axisPad

  const shouldClip = handlingMode === 'clip' && outlierInfo?.has_outliers
  // 统计口径启用：clip 与 exclude 都切到后端 filtered 统计（与统计卡 useHistogram
  // 的 useFiltered 同判断）——此前只认 clip，exclude 下卡片用 filtered 而 σ 线/
  // 正态曲线用全量，同界面口径矛盾
  const useFilteredStats = handlingMode !== 'off' && outlierInfo?.has_outliers
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
  const showNormal = props.chartConfig.includes('normal')
  // 正态曲线数据统一来自后端 result（normal_curve / filtered_normal_curve，
  // 公式单一来源在后端），与 KDE/标记线同源原则一致——前端不再本地实现高斯公式
  const normalCurve = useFilteredStats && r.filtered_normal_curve != null ? r.filtered_normal_curve : r.normal_curve
  const hasNormal = showNormal && Array.isArray(normalCurve) && normalCurve.length > 1
  // KDE curve data source: 「KDE含超限」开关全局生效、与异常值模式解耦——
  // on → full-data curve (out-of-spec values surface as their own bump);
  // off → IQR-filtered curve (main peak faithful); 无异常值时
  // filtered_kde_curve 为 None → 回退全量曲线。
  const includeFailKde = props.chartConfig.includes('kde_full')
  const kdeCurve = includeFailKde || r.filtered_kde_curve == null ? r.kde_curve : r.filtered_kde_curve
  const hasKde = props.chartConfig.includes('kde') && Array.isArray(kdeCurve) && kdeCurve.length > 1
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
        itemStyle: { color: getSiteColors8(isDark.value)[idx % 8] },
        barWidth: `${effectiveBarWidth}%`,
        barGap: `${-props.barOverlapPercent}%`,
      })
    }
    series.push({
      name: 'All Site', type: 'bar', yAxisIndex: 1,
      data: buildBarData(activeIndices, binCenters, r.bin_percentages || [], r.bin_counts),
      itemStyle: { color: '#90CAF9', opacity: 0.5 }, barWidth: `${effectiveBarWidth}%`, barGap: `${-props.barOverlapPercent}%`,
      // 柱顶百分比标签：night 必须白字——柱面是 50% 半透明 #90CAF9 叠在深底
      // ≈ 中蓝 rgb(83,117,155)，深蓝 #1565C0 贴中蓝面对比度≈1.3:1（8/26 用户反馈）
      label: { show: true, position: 'top', formatter: (p: any) => { const real = p.data[2] ?? p.data[1]; return real > 0 ? `${formatPercent(real)}%` : '' }, fontSize: 10, color: isDark.value ? '#ffffff' : '#1565C0', fontWeight: 'bold' },
    })
  } else {
    series.push({
      name: '数据分布', type: 'bar',
      data: buildBarData(activeIndices, binCenters, r.bin_percentages || [], r.bin_counts),
      itemStyle: { color: isDark.value ? '#42A5F5' : '#1E88E5' }, barWidth: `${effectiveBarWidth}%`,
    })
  }

  // 规格限/自定义限/σ 线按颜色组拆成独立系列——图例 marker 取 itemStyle.color
  //（不取 lineStyle.color），旧实现单系列无 itemStyle 时图例落主题色板，与
  // 实际线色（红/灰/蓝/青/橙）不对应（2026-08-20 修复）
  const mkGroups: { name: string; color: string; items: any[] }[] = []
  // 规格限/自定义限线色：红-绿对在红绿色盲下不可分（deutan ΔE 14.6），
  // 改为 红-灰（LSL/USL=红 语义不变，CL=灰 表示"次级/自定义"）
  const limitColor = isDark.value ? '#ef5350' : '#C62828'
  const clColor = isDark.value ? '#9ca3af' : '#757575'
  const showLimit = props.chartConfig.includes('limit')
  if (showLimit && r.lower_limit != null && r.upper_limit != null) {
    mkGroups.push({
      name: '规格限', color: limitColor, items: [
        { xAxis: r.lower_limit, lineStyle: { color: limitColor, width: 3, type: 'dashed' }, label: { show: true, formatter: 'LSL', position: 'end' } },
        { xAxis: r.upper_limit, lineStyle: { color: limitColor, width: 3, type: 'dashed' }, label: { show: true, formatter: 'USL', position: 'end' } },
      ],
    })
  }
  // CL 模式：画出用户自定义规格限线（数据来自后端 result，与 LSL/USL 一致）
  if (props.rangeType === 'CL' && r.custom_low != null && r.custom_high != null) {
    mkGroups.push({
      name: '自定义限', color: clColor, items: [
        { xAxis: r.custom_low, lineStyle: { color: clColor, width: 2, type: 'dashed' }, label: { show: true, formatter: 'CL Low', position: 'insideEndTop' } },
        { xAxis: r.custom_high, lineStyle: { color: clColor, width: 2, type: 'dashed' }, label: { show: true, formatter: 'CL High', position: 'insideEndTop' } },
      ],
    })
  }
  // σ 标记线与统计卡同一口径：裁剪时用后端 filtered_sigma*（与 filtered_mean/
  // std 同源），否则用全量 sigma*。此前卡片用裁剪值、线用全量值，界面矛盾
  const s3Min = useFilteredStats && r.filtered_sigma3_min != null ? r.filtered_sigma3_min : r.sigma3_min
  const s3Max = useFilteredStats && r.filtered_sigma3_max != null ? r.filtered_sigma3_max : r.sigma3_max
  const s4Min = useFilteredStats && r.filtered_sigma4_min != null ? r.filtered_sigma4_min : r.sigma4_min
  const s4Max = useFilteredStats && r.filtered_sigma4_max != null ? r.filtered_sigma4_max : r.sigma4_max
  const s6Min = useFilteredStats && r.filtered_sigma6_min != null ? r.filtered_sigma6_min : r.sigma6_min
  const s6Max = useFilteredStats && r.filtered_sigma6_max != null ? r.filtered_sigma6_max : r.sigma6_max
  if (props.chartConfig.includes('s3') && s3Min != null && s3Max != null) {
    mkGroups.push({
      name: '3σ线', color: s3c, items: [
        { xAxis: s3Min, lineStyle: { color: s3c, width: 3, type: 'dotted' }, label: { show: true, formatter: '3σ下限', position: 'insideEndTop' } },
        { xAxis: s3Max, lineStyle: { color: s3c, width: 3, type: 'dotted' }, label: { show: true, formatter: '3σ上限', position: 'insideEndTop' } },
      ],
    })
  }
  if (props.chartConfig.includes('s4') && s4Min != null && s4Max != null) {
    mkGroups.push({
      name: '4σ线', color: s4c, items: [
        { xAxis: s4Min, lineStyle: { color: s4c, width: 3, type: 'dotted' }, label: { show: true, formatter: '4σ下限', position: 'insideEndTop' } },
        { xAxis: s4Max, lineStyle: { color: s4c, width: 3, type: 'dotted' }, label: { show: true, formatter: '4σ上限', position: 'insideEndTop' } },
      ],
    })
  }
  if (props.chartConfig.includes('s6') && s6Min != null && s6Max != null) {
    mkGroups.push({
      name: '6σ线', color: s6c, items: [
        { xAxis: s6Min, lineStyle: { color: s6c, width: 3, type: 'dotted' }, label: { show: true, formatter: '6σ下限', position: 'insideEndTop' } },
        { xAxis: s6Max, lineStyle: { color: s6c, width: 3, type: 'dotted' }, label: { show: true, formatter: '6σ上限', position: 'insideEndTop' } },
      ],
    })
  }
  // markLine 系列显式 itemStyle.color（图例 marker 与线色严格对应）
  const markLineNames = new Set(mkGroups.map((g) => g.name))
  for (const g of mkGroups) {
    if (g.items.length) {
      series.push({
        name: g.name, type: 'line', data: [],
        itemStyle: { color: g.color },
        markLine: { symbol: 'none', precision: 4, data: g.items },
      })
    }
  }

  if (hasNormal) {
    series.push({ name: '正态分布', type: 'line', data: normalCurve as any[], smooth: true, itemStyle: { color: AXIS.normal }, lineStyle: { color: AXIS.normal, width: 3 }, symbol: 'none', yAxisIndex: normalAxisIdx, z: 10 })
  }

  if (hasKde) {
    series.push({ name: 'KDE曲线', type: 'line', data: kdeCurve, smooth: true, itemStyle: { color: AXIS.kde }, lineStyle: { color: AXIS.kde, width: 3 }, symbol: 'none', yAxisIndex: kdeAxisIdx, z: 10 })
  }

  // 左轴上限：有站点数据时按站点直方图最大百分比向上取整（留顶部空间）
  let leftYMax = 100
  if (hasSiteData) {
    let maxVal = 0
    for (const s of Object.keys(siteHists)) for (const v of siteHists[s]) if (v > maxVal) maxVal = v
    leftYMax = Math.ceil(maxVal / 5) * 5 + 5
  }
  const yAxes: any[] = [{ type: 'value', name: '百分比 (%)', nameTextStyle: { color: AXIS.left, fontWeight: 'bold' }, position: 'left', min: 0, max: leftYMax, axisLabel: { formatter: '{value}%', color: AXIS.left }, axisLine: { show: true, lineStyle: { color: AXIS.left } } }]
  if (hasSiteData) yAxes.push({ type: 'value', name: 'All Site (%)', nameTextStyle: { color: AXIS.allsite, fontWeight: 'bold' }, position: 'right', min: 0, axisLabel: { formatter: '{value}%', color: AXIS.allsite }, axisLine: { show: true, lineStyle: { color: AXIS.allsite } }, splitLine: { show: false } })
  if (hasKde) yAxes.push({ type: 'value', name: 'KDE密度', nameTextStyle: { color: AXIS.kde, fontWeight: 'bold' }, position: 'left', offset: 55, min: 0, axisLabel: { formatter: (v: number) => v.toExponential(2), color: AXIS.kde }, axisLine: { show: true, lineStyle: { color: AXIS.kde } }, splitLine: { show: false } })
  if (hasNormal) yAxes.push({ type: 'value', name: '概率密度', nameTextStyle: { color: AXIS.normal, fontWeight: 'bold' }, position: 'right', offset: hasSiteData ? 50 : 0, min: 0, axisLabel: { formatter: (v: number) => v.toExponential(2), color: AXIS.normal }, axisLine: { show: true, lineStyle: { color: AXIS.normal } }, splitLine: { show: false } })

  const unitStr = r.unit || ''
  const limitStr = (r.lower_limit != null && r.upper_limit != null) ? `Limit [${r.lower_limit.toFixed(4)}, ${r.upper_limit.toFixed(4)}]` : ''
  const titleText = `{name|${props.selectedParam}}  {unit|${unitStr ? `(${unitStr})` : ''}}  {limit|${limitStr || ''}}`

  return {
    title: { text: titleText, left: 'center', top: 6, textStyle: { rich: {
      name: { fontSize: 15, fontWeight: 'bold', color: tc },
      unit: { fontSize: 12, color: tc, fontWeight: 500 },
      limit: { fontSize: 12, color: isDark.value ? '#FFB74D' : '#E65100', fontWeight: 600, backgroundColor: isDark.value ? 'rgba(255, 183, 77, 0.15)' : '#FFF3E0', padding: [2, 6], borderRadius: 3 },
    } } },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: colors.value.tooltipBg,
      borderColor: colors.value.tooltipBorder,
      textStyle: { color: colors.value.tooltipText },
      formatter: (params: any) => {
        const items = Array.isArray(params) ? params : [params]
        const first = items[0]
        const firstX = Array.isArray(first.data) ? first.data[0] : first.data.value?.[0]
        let html = `值: ${Number(firstX).toFixed(4)}<br/>`
        for (const p of items) {
          if (markLineNames.has(p.seriesName) || p.seriesName === '正态分布' || p.seriesName === 'KDE曲线') continue
          // 柱系列 data[1] 是钳制后的渲染值，data[2] 才是真实百分比；
          // data[3] 为该 bin 计数（0 表示无计数数据）
          const raw = Array.isArray(p.data) ? p.data : p.data.value
          const y = raw?.[2] ?? raw?.[1]
          if (y != null) {
            const count = raw?.[3] ? `（n=${raw[3]}）` : ''
            html += `${p.seriesName}: ${formatPercent(Number(y))}%${count}<br/>`
          }
        }
        return html
      },
    },
    legend: { data: series.map((s: any) => s.name), top: 'bottom', type: 'scroll', textStyle: { color: tc } },
    toolbox: { feature: { saveAsImage: { name: `${props.selectedParam}_分析` } } },
    grid: { top: 55, bottom: 70, left: hasKde ? 110 : 55, right: (hasSiteData && hasNormal) ? 120 : (hasSiteData || hasNormal) ? 80 : 55 },
    xAxis: { type: 'value', name: '', nameLocation: 'middle', nameGap: 28, min: xAxisMin, max: xAxisMax, axisLabel: { rotate: 45, show: true, interval: 0, fontSize: 9, formatter: formatAxisValue, color: tc }, splitNumber: 24 },
    yAxis: yAxes,
    series,
  }
}

const { chartRef } = useChart(buildOption, [() => props.result, () => props.chartConfig, () => props.rangeType, () => props.barWidthPercent, () => props.barOverlapPercent, () => props.selectedParam, () => props.outlierHandling])
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
