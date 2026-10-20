/**
 * 多文件对比图（/analysis/multi_lot/ 带 param 响应）的 ECharts option 构造 —— 纯函数。
 *
 * 从 `components/MultiFileChart.vue` 的 `buildOption()` 搬出来，是为了让 option 层判据
 * 有 T2 可写（`docs/reference/testing-gates.md` §2 的分诊把「ECharts option 层断言」列为
 * 无处可落的一档；先例是 `src/pages/weight/weightChartOption.ts`）。本模块**不许** import
 * vue / pinia / `utils/echarts-theme`：主题由调用方作为普通对象传进来，否则 T2 的
 * `environment: 'node'` 起不来。
 *
 * 与后端的分工：单文件直方图的正态曲线由后端 `normal_pdf_curve` 单源下发；
 * 多文件对比里每个 lot 的 `mean/std` 也在响应中，但曲线是在这里按轴范围现采样的
 * （`sampleNormalCurve`）—— 公式必须与后端那份逐字一致，`multiFileChartOption.spec.ts`
 * 用后端实测黄金值钉住这一点。
 */
import { chartFontSize } from '../../theme/typography'
import {
  buildChartToolbox,
  clampBarValue,
  formatAxisValue,
  formatPercent,
  getBarGroupPad,
  getMaxBarWidthPercent,
  mapLotColorToTheme,
} from '../../utils/chart-bar'

/** 调用方从 `useEChartsTheme()` 取出的那组色值 + 当前主题（原样传，不在这里读 store）。 */
export interface MultiLotTheme {
  textColor: string
  axisLineColor: string
  tooltipBg: string
  tooltipBorder: string
  tooltipText: string
  isDark: boolean
}

export interface MultiFileLot {
  file_id: number
  name?: string
  /** 后端固定浅色板色（`multi_lot.py:282` 每个 lot 都发），进主题前由 `mapLotColorToTheme` 换算 */
  color: string
  mean: number
  std: number
  /** `[binCenter, percent]`，渲染时钳成 `[x, 显示值, 真实值]` 三元组 */
  bar_data: number[][]
  upper_limit?: number | null
  lower_limit?: number | null
  display_upper?: number | null
  display_lower?: number | null
  kde_curve?: number[][] | null
}

export interface MultiLotResponse {
  lot_data?: MultiFileLot[]
  bin_centers?: number[]
  global_mean?: number | null
  chart_min?: number
  chart_max?: number
}

export interface MultiFileOptionInput {
  lotData: MultiLotResponse
  chartConfig: string[]
  barWidthPercent: number
  /** file_id → 自定义图例名 */
  fileNames: Record<number, string>
  selectedParam: string
  theme: MultiLotTheme
}

/**
 * 轴辅助色（2026-08-26 夜晚可视度修复）：light 保持直方图基准常量，
 * night 提亮 —— #1E88E5 在深底对比度不足。
 */
export function axisColors(isDark: boolean): { left: string; normal: string } {
  return isDark
    ? { left: '#64B5F6', normal: '#FFA726' }
    : { left: '#1E88E5', normal: '#F57F17' }
}

/** 高斯 PDF；`std === 0` 返回 0（退化数据不画曲线，由 `sampleNormalCurve` 的上层守卫兜住）。 */
export function normalPDFAt(x: number, mean: number, std: number): number {
  if (std === 0) return 0
  return (1 / (std * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * ((x - mean) / std) ** 2)
}

/**
 * 在 `[xMin, xMax]` 上按 `steps` 段均匀采样正态曲线（含两端，共 steps+1 点）。
 * `std <= 0` 或零宽区间返回空数组 —— 调用方据此跳过系列与概率密度轴。
 *
 * 按 `i` 求 x（不是 `x += step` 累加）：累加会把末点推到 `xMax` 之外一个 epsilon，
 * 于是点数从 steps+1 掉到 steps，曲线停在轴边缘内侧（旧写法实测 100 点而非 101）。
 */
export function sampleNormalCurve(
  mean: number,
  std: number,
  xMin: number,
  xMax: number,
  steps = 100,
): [number, number][] {
  if (!(std > 0) || !(xMax > xMin) || steps <= 0) return []
  const step = (xMax - xMin) / steps
  const points: [number, number][] = []
  for (let i = 0; i <= steps; i++) {
    const x = i === steps ? xMax : xMin + i * step
    points.push([x, normalPDFAt(x, mean, std)])
  }
  return points
}

/** 图例名：账号自定义文件名 → 后端 lot.name → `File <id>`。 */
export function lotDisplayName(lot: MultiFileLot, fileNames: Record<number, string>): string {
  return fileNames[lot.file_id] || lot.name || `File ${lot.file_id}`
}

/**
 * 多系列 bar 分组后的边缘 pad（无 `bin_centers` 时从 bar_data 前两点推 binGap，
 * 推不出来给 0）。两端各扩一段，否则最左/最右系列的第 0 根柱被整根裁掉
 * （回归：edge-clip，与 HistogramChart 同构）。
 */
export function deriveBinGap(lots: MultiFileLot[], binCenters: number[]): number {
  if (binCenters.length >= 2) return binCenters[1] - binCenters[0]
  const first = lots[0]?.bar_data?.[0]?.[0]
  const second = lots[0]?.bar_data?.[1]?.[0]
  return second != null && first != null ? second - first : 0
}

/** 单个 lot 的规格限 markLine（`display_*` 优先于 `*_limit`；单边限值只画一条）。 */
export function buildLimitMarkLines(
  lot: MultiFileLot,
  name: string,
  color: string,
): { mk: any[]; upper: number | null | undefined; lower: number | null | undefined } {
  const upper = lot.display_upper ?? lot.upper_limit
  const lower = lot.display_lower ?? lot.lower_limit
  const mk: any[] = []
  const label = (text: string) => ({
    show: true,
    formatter: text,
    position: 'end',
    color,
    fontSize: chartFontSize.micro,
    fontWeight: 'bold',
  })
  if (upper != null) {
    mk.push({ xAxis: upper, lineStyle: { color, width: 3, type: 'dashed' }, label: label(`${name} USL`) })
  }
  if (lower != null) {
    mk.push({ xAxis: lower, lineStyle: { color, width: 3, type: 'dashed' }, label: label(`${name} LSL`) })
  }
  return { mk, upper, lower }
}

/** tooltip 文本：轴上多点场景取第一个的 x 作表头，只有 bar 系列参与，显示 `data[2]` 的真实百分比。 */
export function multiLotTooltipHtml(params: any): string {
  const items = Array.isArray(params) ? params : [params]
  if (!items.length) return ''
  let html = `值: ${Number(items[0].data?.[0]).toFixed(4)}<br/>`
  for (const p of items) {
    if (p.data && p.data[1] != null && p.seriesType === 'bar') {
      // data[1] 是钳制后的渲染值，data[2] 才是真实百分比
      const real = p.data[2] ?? p.data[1]
      html += `${p.seriesName}: ${formatPercent(Number(real))}%<br/>`
    }
  }
  return html
}

/** 构建多文件对比图的完整 option；无数据时返回空对象（`useChart` 据此不 setOption）。 */
export function buildMultiFileOption(input: MultiFileOptionInput): any {
  const { lotData: r, chartConfig, fileNames, selectedParam, theme } = input
  if (!r || !Array.isArray(r.lot_data) || r.lot_data.length === 0) return {}

  const lots = r.lot_data
  const tc = theme.textColor
  const AXIS = axisColors(theme.isDark)
  const showLimit = chartConfig.includes('limit')
  const showNormal = chartConfig.includes('normal')
  const showKde = chartConfig.includes('kde')
  const binCenters: number[] = r.bin_centers || []

  const series: any[] = []
  const legendData: string[] = []
  // 柱宽上限：N 系列并排柱组总宽必须 ≤ bin 宽，否则柱组横跨 bin 边界、
  // 贴限 bin（右边界=USL）的 pass 柱会被画到 USL 右侧（回归：limit-line-cross）
  const effectiveBarWidth = Math.min(input.barWidthPercent, getMaxBarWidthPercent(lots.length))

  for (const lot of lots) {
    const dn = lotDisplayName(lot, fileNames)
    const lc = mapLotColorToTheme(lot.color, theme.isDark)
    legendData.push(dn)
    series.push({
      name: dn,
      type: 'bar',
      // 小百分比（如 0.002%）钳制到最小可见柱高，真实值存 data[2] 供 tooltip/标签
      data: lot.bar_data.map((d: number[]) => [d[0], clampBarValue(d[1]), d[1]]),
      itemStyle: { color: lc },
      barWidth: `${effectiveBarWidth}%`,
      barGap: '10%',
      label: {
        show: true,
        position: 'top',
        formatter: (params: any) => {
          const real = params.data?.[2] ?? params.data?.[1]
          return real > 0 ? `${formatPercent(real)}%` : ''
        },
        fontSize: chartFontSize.micro,
        color: lc,
        fontWeight: 'bold',
      },
    })
  }

  // Limit 线：每个文件独立图例
  if (showLimit) {
    for (const lot of lots) {
      const dn = lotDisplayName(lot, fileNames)
      const lc = mapLotColorToTheme(lot.color, theme.isDark)
      const { mk, upper, lower } = buildLimitMarkLines(lot, dn, lc)
      if (mk.length) {
        const limitX = upper ?? lower ?? binCenters[0]
        series.push({
          name: `${dn} 规格限`,
          type: 'scatter',
          data: [[limitX, 0]],
          symbol: 'circle',
          symbolSize: 0,
          itemStyle: { color: lc },
          markLine: { symbol: 'none', precision: 4, data: mk },
        })
        legendData.push(`${dn} 规格限`)
      }
    }
  }

  // 正态分布曲线：每个文件独立颜色
  if (showNormal) {
    for (const lot of lots) {
      if (!(lot.std > 0) || binCenters.length === 0) continue
      const dn = lotDisplayName(lot, fileNames)
      const lc = mapLotColorToTheme(lot.color, theme.isDark)
      const normalData = sampleNormalCurve(lot.mean, lot.std, binCenters[0], binCenters[binCenters.length - 1])
      if (!normalData.length) continue
      series.push({
        name: `${dn} 正态分布`,
        type: 'line',
        data: normalData,
        smooth: true,
        lineStyle: { color: lc, width: 3, type: 'dotted' },
        itemStyle: { color: lc },
        symbol: 'none',
        yAxisIndex: 1, // 使用独立的概率密度Y轴
        z: 10,
      })
      legendData.push(`${dn} 正态分布`)
    }
  }

  // KDE 曲线：每个文件独立颜色
  if (showKde) {
    for (const lot of lots) {
      if (!lot.kde_curve || lot.kde_curve.length === 0) continue
      const dn = lotDisplayName(lot, fileNames)
      const lc = mapLotColorToTheme(lot.color, theme.isDark)
      series.push({
        name: `${dn} KDE`,
        type: 'line',
        data: lot.kde_curve,
        smooth: true,
        lineStyle: { color: lc, width: 2.5 },
        itemStyle: { color: lc },
        symbol: 'none',
        yAxisIndex: 1,
        z: 10,
      })
      legendData.push(`${dn} KDE`)
    }
  }

  const titleText = `${selectedParam}  ${r.global_mean != null ? `(μ=${r.global_mean})` : ''}`

  const binGap = deriveBinGap(lots, binCenters)
  const axisPad = getBarGroupPad(lots.length, binGap, effectiveBarWidth)

  // 轴 min/max 向两端扩展多系列 bar 分组偏移量：扩展只在两端多出空边距，
  // 正态曲线仍按未扩展的 span 生成。
  const xAxisMin = binCenters.length > 0 ? binCenters[0] - axisPad : r.chart_min
  const xAxisMax = binCenters.length > 0 ? binCenters[binCenters.length - 1] + axisPad : r.chart_max

  const yAxisConfig: any[] = [
    {
      type: 'value',
      name: '百分比 (%)',
      nameTextStyle: { color: AXIS.left, fontWeight: 'bold' },
      position: 'left',
      min: 0,
      axisLabel: { formatter: '{value}%', color: AXIS.left },
      axisLine: { show: true, lineStyle: { color: AXIS.left } },
    },
  ]

  // 如果显示正态分布曲线或 KDE 曲线，添加概率密度Y轴
  if (showNormal || showKde) {
    yAxisConfig.push({
      type: 'value',
      name: '概率密度',
      nameTextStyle: { color: AXIS.normal, fontWeight: 'bold' },
      position: 'right',
      min: 0,
      axisLabel: { formatter: (v: number) => v.toExponential(2), color: AXIS.normal },
      axisLine: { show: true, lineStyle: { color: AXIS.normal } },
      splitLine: { show: false },
    })
  }

  return {
    title: {
      text: titleText,
      left: 'center',
      top: 6,
      textStyle: { fontSize: chartFontSize.base, fontWeight: 'bold', color: tc },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: theme.tooltipBg,
      borderColor: theme.tooltipBorder,
      textStyle: { color: theme.tooltipText },
      formatter: multiLotTooltipHtml,
    },
    legend: { data: legendData, top: 'bottom', type: 'scroll', textStyle: { color: tc } },
    toolbox: buildChartToolbox({ name: `${selectedParam}_多文件对比` }),
    grid: { top: 55, bottom: 70, left: 55, right: showNormal || showKde ? 80 : 55 },
    xAxis: {
      type: 'value',
      min: xAxisMin,
      max: xAxisMax,
      axisLine: { lineStyle: { color: theme.axisLineColor } },
      axisLabel: {
        rotate: 45,
        show: true,
        interval: 0,
        fontSize: chartFontSize.micro,
        formatter: formatAxisValue,
        color: tc,
      },
      splitNumber: 24,
    },
    yAxis: yAxisConfig,
    series,
  }
}
