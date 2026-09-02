/**
 * 相关性矩阵热力图 option 构建（从 CorrelationToolsTab.vue 外移）。
 *
 * 外移动机有二：
 * 1. CorrelationToolsTab.vue 已越过项目 600 行上限；
 * 2. r / p 的显示口径应集中一处 —— 之前 p-value 用 toFixed(6)，
 *    真实 p 小于 1e-6 时单元格 tooltip 会显示「p-value: 0.000000」，
 *    把最强的显著性显示成零。
 */

/** Pearson r：与散点视图、KPI 卡片同为 4 位小数 */
export function formatR(r: number): string {
  return r.toFixed(4)
}

/**
 * p-value：< 1e-4 时 toFixed 会退化成 0.000x / 0.000000，丢失数量级，
 * 改科学计数法保留 2 位有效尾数。
 */
export function formatPValue(p: number): string {
  if (p === 0) return '0'
  if (p < 1e-4) return p.toExponential(2)
  return p.toFixed(6)
}

/** 显著性星号 */
export function getSignificanceStars(p: number): string {
  if (p < 0.001) return '***'
  if (p < 0.01) return '**'
  if (p < 0.05) return '*'
  return ''
}

export interface MatrixOptionTheme {
  textColor: string
  isDark: boolean
}

export function buildCorrelationMatrixOption(
  data: any,
  { textColor, isDark }: MatrixOptionTheme,
) {
  const params: string[] = data.params || []
  const matrix: number[][] = data.matrix || []
  const pValues: number[][] = data.p_values || []

  const heatmapData: [number, number, number][] = []
  for (let i = 0; i < params.length; i++) {
    for (let j = 0; j < params.length; j++) {
      heatmapData.push([i, j, matrix[i]?.[j] ?? 0])
    }
  }

  const pOf = (i: number, j: number) => pValues[i]?.[j] ?? 1

  return {
    tooltip: {
      position: 'top',
      formatter: (p: any) => {
        const [pi, pj, r] = p.value as [number, number, number]
        const pv = pOf(pi, pj)
        return `${params[pi]} vs ${params[pj]}<br/>Pearson r: ${formatR(r)}${getSignificanceStars(pv)}<br/>p-value: ${formatPValue(pv)}`
      },
    },
    grid: { left: '15%', right: '10%', top: '10%', bottom: '15%' },
    xAxis: { type: 'category', data: params, splitArea: { show: true }, axisLabel: { rotate: 45, fontSize: 10, color: textColor } },
    yAxis: { type: 'category', data: params, splitArea: { show: true }, axisLabel: { fontSize: 10, color: textColor } },
    visualMap: {
      min: -1, max: 1, calculable: true, orient: 'horizontal', left: 'center', bottom: '0%',
      inRange: { color: isDark
        // RdYlBu 化：原 红→绿 发散带在红绿色盲下正负相关不可分（deutan ΔE 14.6）
        ? ['#ef5350', '#ff7043', '#ffa726', '#ffee58', '#f8fafc', '#93c5fd', '#3b82f6', '#1d4ed8']
        : ['#d73027', '#f46d43', '#fdae61', '#fee08b', '#e0f3f8', '#abd9e9', '#74add1', '#4575b4'] },
    },
    series: [{
      name: 'Pearson r', type: 'heatmap', data: heatmapData,
      label: {
        show: true, fontSize: 9,
        formatter: (p: any) => {
          const [pi, pj, r] = p.value as [number, number, number]
          // 格内空间只容得下 2 位小数，完整 4 位看 tooltip
          return `${r.toFixed(2)}${getSignificanceStars(pOf(pi, pj))}`
        },
      },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.5)' } },
    }],
  }
}
