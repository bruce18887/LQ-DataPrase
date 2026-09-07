/**
 * 相关性矩阵热力图 option 构建（从 CorrelationToolsTab.vue 外移）。
 *
 * 外移动机有二：
 * 1. CorrelationToolsTab.vue 已越过项目 600 行上限；
 * 2. r / p 的显示口径应集中一处 —— 之前 p-value 用 toFixed(6)，
 *    真实 p 小于 1e-6 时单元格 tooltip 会显示「p-value: 0.000000」，
 *    把最强的显著性显示成零。
 */

/** Pearson r：与散点视图、KPI 卡片同为 4 位小数。
 * null（常数列 Pearson 无定义，后端 NaN→JSON null）显示 'N/A'——旧写法
 * `?? 0` 把「无定义相关」伪装成实测零相关（2026-09-05 审查 5.3） */
export function formatR(r: number | null | undefined): string {
  if (r == null || !Number.isFinite(r)) return 'N/A'
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
  /** hover 描边色（原型 .cell:hover outline 同款）；缺省取两主题 brand 兜底 */
  brandColor?: string
}

export function buildCorrelationMatrixOption(
  data: any,
  { textColor, isDark, brandColor }: MatrixOptionTheme,
) {
  const params: string[] = data.params || []
  const matrix: number[][] = data.matrix || []
  const pValues: number[][] = data.p_values || []
  const brand = brandColor ?? (isDark ? '#f9a825' : '#2563eb')
  // Pearson r / Spearman ρ / Kendall τ：tooltip 与 series.name 不能硬编码
  // Pearson——切方法后文案就错了（method 由后端响应体回传）
  const SYMBOLS: Record<string, string> = { pearson: 'Pearson r', spearman: 'Spearman ρ', kendall: 'Kendall τ' }
  const rLabel = SYMBOLS[data.method] ?? 'r'

  // 色带方向对齐原型 .cell（2026-09-06）：正=红、负=蓝、0=中性底。
  // 旧 RdYlBu 是 -1=红 → +1=蓝，与原型相反；色相不变只换极性，CVD 安全性不变。
  // 中性停靠 dark 用石板灰 / light 用近面板色：|r|≈0 的格子视觉上「无话可说」。
  const ramp = isDark
    ? ['#1d4ed8', '#3b82f6', '#334155', '#f87171', '#ef5350']
    : ['#4575b4', '#abd9e9', '#f1f5f9', '#fca5a5', '#d73027']
  const neutral = ramp[2]

  const pOf = (i: number, j: number) => pValues[i]?.[j] ?? 1

  const heatmapData: { value: [number, number, number | null]; label: { color: string }; itemStyle?: { color: string } }[] = []
  for (let i = 0; i < params.length; i++) {
    for (let j = 0; j < params.length; j++) {
      // null 保留进数据元组（ECharts 对 null 值不渲染色块）：`?? 0` 会在
      // formatter 看到之前把 null 吞成实测零相关
      const r = matrix[i]?.[j] ?? null
      // 高 |r| 格内白字（原型 t>0.55 同款阈值），其余用主题文字色
      const strong = r != null && Number.isFinite(r) && Math.abs(r) > 0.55
      const item: (typeof heatmapData)[number] = {
        value: [i, j, r],
        label: { color: strong ? '#fff' : textColor },
      }
      if (i === j) {
        // 对角线恒为 1、无信息量：照原型置中性色，把色阶让给真实数据对
        item.itemStyle = { color: neutral }
      }
      heatmapData.push(item)
    }
  }

  return {
    tooltip: {
      position: 'top',
      formatter: (p: any) => {
        const [pi, pj, r] = p.value as [number, number, number]
        const pv = pOf(pi, pj)
        return `${params[pi]} vs ${params[pj]}<br/>${rLabel}: ${formatR(r)}${getSignificanceStars(pv)}<br/>p-value: ${formatPValue(pv)}`
      },
    },
    grid: { left: '15%', right: '10%', top: '10%', bottom: '15%' },
    xAxis: { type: 'category', data: params, splitArea: { show: true }, axisLabel: { rotate: 45, fontSize: 10, color: textColor } },
    yAxis: { type: 'category', data: params, splitArea: { show: true }, axisLabel: { fontSize: 10, color: textColor } },
    visualMap: {
      min: -1, max: 1, calculable: false, orient: 'horizontal', left: 'center', bottom: '0%',
      // 对齐原型紧凑卡形态：色阶滑块藏掉（show:false），映射与色带不变
      show: false,
      inRange: { color: ramp },
    },
    series: [{
      name: rLabel, type: 'heatmap', data: heatmapData,
      label: {
        show: true, fontSize: 9,
        formatter: (p: any) => {
          const [pi, pj, r] = p.value as [number, number, number]
          // 格内空间只容得下 2 位小数，完整 4 位看 tooltip；null → 'N/A'
          if (r == null || !Number.isFinite(r)) return 'N/A'
          return `${r.toFixed(2)}${getSignificanceStars(pOf(pi, pj))}`
        },
      },
      // hover 描边替代阴影（原型 :hover outline 同款）
      emphasis: { itemStyle: { borderColor: brand, borderWidth: 2 } },
    }],
  }
}
