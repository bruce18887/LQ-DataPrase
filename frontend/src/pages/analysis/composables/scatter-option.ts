/**
 * 相关性散点图 option 构建（从 CorrelationToolsTab.vue 外移，2026-09-06）。
 *
 * 外移动机：组件撞项目 600 行上限（矩阵联动/meta 行/p 值卡加入后越界），
 * 与 matrix-option.ts 同款处理——r/p 与 option 的显示口径集中一处。
 */
import { minMax } from '../../../utils/minmax'
import { formatAxisValue } from '../../../utils/chart-bar'

export interface ScatterOptionTheme {
  textColor: string
  axisLineColor: string
  tooltipBg: string
  tooltipBorder: string
  tooltipText: string
  /** 回归线颜色（调用方传 colors.seriesColors[3]，图例 marker 同源） */
  regressionColor: string
  /** getSiteColors8(isDark) 结果 */
  siteColors: readonly string[]
}

export interface ScatterAxisState {
  axisModeX: 'data' | 'sigma' | 'custom'
  axisModeY: 'data' | 'sigma' | 'custom'
  sigmaX: number
  sigmaY: number
  customMinX: number
  customMaxX: number
  customMinY: number
  customMaxY: number
  outlierHandling: string
}

export interface ScatterOptionInput {
  /** /analysis/correlation/ 响应（useCorrelation 的 corrResult） */
  result: any
  theme: ScatterOptionTheme
  isLarge: boolean
  showRegression: boolean
  axis: ScatterAxisState
}

/** 线性回归计算 */
export function linearRegression(points: number[][]): { slope: number; intercept: number } {
  const n = points.length
  if (n < 2) return { slope: 0, intercept: 0 }
  let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0
  for (const [x, y] of points) {
    sumX += x; sumY += y; sumXY += x * y; sumX2 += x * x
  }
  const denom = n * sumX2 - sumX * sumX
  if (Math.abs(denom) < 1e-12) return { slope: 0, intercept: sumY / n }
  const slope = (n * sumXY - sumX * sumY) / denom
  const intercept = (sumY - slope * sumX) / n
  return { slope, intercept }
}

/** 轴范围：custom 直用 / sigma 按均值±倍数σ / data 外扩半程 */
export function computeRange(mode: string, sigma: number, cMin: number, cMax: number, vals: number[]) {
  if (mode === 'custom') return { min: cMin, max: cMax }
  if (mode === 'sigma') {
    const m = vals.reduce((a, b) => a + b, 0) / vals.length
    const s = Math.sqrt(vals.reduce((sum, v) => sum + (v - m) ** 2, 0) / vals.length)
    return { min: m - sigma * s, max: m + sigma * s }
  }
  const [dMin, dMax] = minMax(vals)
  const rng = dMax > dMin ? dMax - dMin : 1
  return { min: dMin - rng / 2, max: dMax + rng / 2 }
}

export function buildCorrelationScatterOption(
  { result, theme, isLarge, showRegression, axis }: ScatterOptionInput,
) {
  if (!result) return {}
  const tc = theme.textColor
  const d = result
  const series: any[] = (d.series_data || []).map(
    (sd: { name: string; data: number[][] }, idx: number) => ({
      name: sd.name, type: 'scatter', data: sd.data, symbolSize: 6,
      itemStyle: { color: theme.siteColors[idx % 8], opacity: 0.6 },
      ...(isLarge ? { large: true } : {}),
    }),
  )
  const allX: number[] = [], allY: number[] = []
  for (const sd of d.series_data || []) for (const pt of sd.data || []) { allX.push(pt[0]); allY.push(pt[1]) }
  const xR = allX.length > 0 ? computeRange(axis.axisModeX, axis.sigmaX, axis.customMinX, axis.customMaxX, allX) : { min: undefined, max: undefined }
  const yR = allY.length > 0 ? computeRange(axis.axisModeY, axis.sigmaY, axis.customMinY, axis.customMaxY, allY) : { min: undefined, max: undefined }

  // Apply outlier clipping to axis ranges
  if (axis.outlierHandling === 'clip') {
    if (d.x_outlier_info?.has_outliers) {
      if (axis.axisModeX === 'data') {
        xR.min = d.x_outlier_info.lower_bound
        xR.max = d.x_outlier_info.upper_bound
      }
    }
    if (d.y_outlier_info?.has_outliers) {
      if (axis.axisModeY === 'data') {
        yR.min = d.y_outlier_info.lower_bound
        yR.max = d.y_outlier_info.upper_bound
      }
    }
  }

  // Regression line
  if (showRegression && allX.length >= 2) {
    const { slope, intercept } = linearRegression(allX.map((x, i) => [x, allY[i]]))
    const [xAllMin, xAllMax] = minMax(allX)
    const xMin = xR.min ?? xAllMin
    const xMax = xR.max ?? xAllMax
    const r2 = (d.pearson_r ?? 0) ** 2
    series.push({
      name: '回归线',
      type: 'line',
      data: [[xMin, slope * xMin + intercept], [xMax, slope * xMax + intercept]],
      // itemStyle.color 与 lineStyle 同源——图例 marker 只取 itemStyle（2026-08-20）
      itemStyle: { color: theme.regressionColor },
      lineStyle: { type: 'dashed', color: theme.regressionColor, width: 2 },
      symbol: 'none',
      tooltip: {
        formatter: () => `回归方程: y = ${slope.toFixed(4)}x + ${intercept.toFixed(4)}<br/>R² = ${r2.toFixed(4)}`,
      },
    })
  }

  return {
    // large 模式下上万 symbol 的入场/更新动画是纯开销，直接关闭
    animation: !isLarge,
    title: { text: `${d.param_x} vs ${d.param_y}`, subtext: `Pearson r = ${d.pearson_r?.toFixed(4) ?? '-'}`, left: 'center', textStyle: { color: tc, fontSize: 15 }, subtextStyle: { color: tc, fontSize: 12 } },
    toolbox: { feature: { saveAsImage: { title: '保存图片' }, restore: { title: '还原' } }, right: 10 },
    tooltip: { trigger: 'item', backgroundColor: theme.tooltipBg, borderColor: theme.tooltipBorder, textStyle: { color: theme.tooltipText }, formatter: (p: any) => `${p.seriesName}<br/>${d.param_x}: ${Number(p.value[0]).toFixed(4)}<br/>${d.param_y}: ${Number(p.value[1]).toFixed(4)}` },
    legend: { data: series.map((s: any) => s.name), bottom: 5, type: 'scroll', textStyle: { color: tc } },
    xAxis: { type: 'value', name: d.param_x, nameLocation: 'center', nameGap: 30, min: xR.min, max: xR.max, axisLine: { lineStyle: { color: theme.axisLineColor } }, axisLabel: { fontSize: 9, formatter: formatAxisValue, color: tc }, nameTextStyle: { color: tc } },
    yAxis: { type: 'value', name: d.param_y, nameLocation: 'center', nameGap: 40, min: yR.min, max: yR.max, axisLine: { lineStyle: { color: theme.axisLineColor } }, axisLabel: { fontSize: 9, formatter: formatAxisValue, color: tc }, nameTextStyle: { color: tc } },
    dataZoom: [
      { type: 'slider', xAxisIndex: 0, start: 0, end: 100 },
      { type: 'slider', yAxisIndex: 0, start: 0, end: 100 },
      { type: 'inside', xAxisIndex: 0 },
      { type: 'inside', yAxisIndex: 0 },
    ],
    series,
  }
}
