/** 权重画图的 option 构建：每个测试项一张图、纯函数、零 DOM，才能落 T2（testing-gates §2）。
 *
 *  「14 组叠一张图」的旧版会被 WT0004 那种大值把 y 轴压扁、其余组全成平线（用户实测反馈）。
 *  改版后调用方**按组分别调用**：每张图只含本组 4 条（+均值），x 轴取本组最长系列 - 1，
 *  y 轴各自 auto。页面用 `visible` 决定渲染哪几张图（多图列表），本模块不处理可见性。
 *
 *  「系列名不是唯一键」是 spec §3.2 的已接受行为（Task 2 评审实测）：后缀按名称出现次数生成，
 *  所以 `A`×2 加字面 `A_1` 会得到 `['A_1','A_2','A_1']`，字面 `A_Avg` 还会与该组均值线撞名，
 *  而解析器**不去重也不报错**。⇒ 本模块只按 `(group.index, 组内下标)` 取色/取线型，
 *  绝不按 `series.name` 查表；`name` 只用于显示（tooltip、图例与 Task 8 的表格）。
 *
 *  颜色一律由调用方给（Task 8 传 `useEChartsTheme().colors.value.seriesColors`）：ECharts 不解析
 *  `var(--x)`（lessons R7②），色板真源也只有前端那一份（spec §6 第 1 条，Python 侧不存色板）。
 *  组色 = `colors[group.index % 8]` ⇒ 9..14 组复用 1..6 色，这是现行 8 色 CVD 色板的能力上限
 *  （spec §6 第 4 条：想要 14 色得先过 `tasks/cvd_verify.mjs` 的成环相邻 ΔE≥15）。
 *
 *  线型/宽度与导出侧 `apps/weight/xlsx.py` 逐位对位（那边是 Excel 的
 *  `solid/dash/dot/dashDot`，这边是 ECharts 的 `solid/dashed/dotted/[6,3,1,3]`），
 *  两处各按自己语言的拼写各存一份，页面上看到的线与 xlsx 里那条线是同一套语义。
 */
import type { EChartsOption } from 'echarts'
import { chartFontSize } from '../../theme/typography'

export interface WeightSeriesDto {
  name: string
  source_index: number
  declared_length: number
  decimals: number
  /** 缺失点是 null（后端把空位原样交出来），不许在这里填 0 或删点。 */
  values: (number | null)[]
}

export interface WeightGroupDto {
  index: number
  name: string
  first_row: number
  series: WeightSeriesDto[]
  /** 后端一次算完的逐点均值；前端只决定显不显示（spec §5.2 末条）。 */
  mean: WeightSeriesDto
}

export interface WeightDocDto {
  filename: string
  code_max: number
  group_count: number
  series_count: number
  groups: WeightGroupDto[]
}

export interface BuildOptions {
  showMean: boolean
  /** 图例总开关（页面级）：只决定底部那行 `1/2/3/4/均值` 画不画，不影响任何曲线。
   *  可选且缺省为显示 —— 关掉时把图例占的底部留白一并让给画布，所以缺省值不能翻成隐藏。 */
  showLegend?: boolean
  /** 当前主题的 8 色板，即 `echarts-theme.ts` 的 `colors.seriesColors`。 */
  colors: string[]
  /** 均值线色，由调用方给（Task 8 传 `colors.textColor`）。 */
  meanColor: string
  textColor: string
  axisLineColor: string
  /** 横向网格线色；缺省回退 axisLineColor（T2 的既有调用方不必补字段）。 */
  splitLineColor?: string
  /** 均值数值标签色；缺省回退 textColor。页面传 titleColor 以拉开与轴标签的层级。 */
  labelColor?: string
  /** 图标题：页面与导出都用测试项名（不是文件名）。 */
  titleText: string
}

/** 组内 4 个槽位用线型区分、同组同基色（spec §6 第 2 条）。按**组内序**取、每组边界重置。 */
export const DASH_BY_WITHIN_GROUP: (string | number[])[] = ['solid', 'dashed', 'dotted', [6, 3, 1, 3]]
/** 均值只能是实线：4 个成员槽已用掉 dashed/dotted/点划，虚线均值会与组内某条撞型（spec §6 第 3 条）。 */
/** 均值线用细虚线：它画在最上层，若是粗实线会把贴得很近的 4 条原始线整条盖住（用户实测）。 */
export const MEAN_DASH = 'dashed'
export const MEAN_WIDTH = 1.5
export const LINE_WIDTH = 1.25
export const MARKER_SIZE = 4
/** 页面显示上限（2026-10-20 用户点定）：最多 5 位小数；xlsx 导出的均值格式也统一为 5 位（parser.MEAN_DECIMALS=5）。 */
export const PAGE_MAX_DECIMALS = 5

/** 图上数值标签 / tooltip：最多 5 位、去掉尾零；null 留空。 */
export function formatWeightLabel(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return ''
  return String(Number(value.toFixed(PAGE_MAX_DECIMALS)))
}

/** 明细表单元格：按源小数位与 5 位取小；把 `-0.00000` 归一成 `0.00000`。 */
export function formatWeightCell(value: number | null | undefined, decimals: number): string {
  if (value == null || !Number.isFinite(value)) return ''
  const fixed = value.toFixed(Math.min(Math.max(decimals, 0), PAGE_MAX_DECIMALS))
  return /^-0(\.0+)?$/.test(fixed) ? fixed.slice(1) : fixed
}

/** 图例只显示组内序号：组名已在卡头，5 条长名会把图例挤成两页。 */
export function legendLabel(name: string, groupName: string): string {
  if (name === `${groupName}_Avg`) return '均值'
  if (name === groupName) return '原始'
  if (name.startsWith(`${groupName}_`)) return name.slice(groupName.length + 1)
  return name.length > 16 ? `${name.slice(0, 15)}…` : name
}

export function groupColor(colors: string[], groupIndex: number): string {
  return colors[groupIndex % colors.length]
}

/** 该组 x 轴上界：最长系列长度 - 1（组内独立缩放）。空组钳到 0，轴不出现负上界。 */
export function groupCodeMax(group: WeightGroupDto): number {
  const longest = Math.max(0, ...group.series.map((s) => s.values.length))
  return Math.max(longest - 1, 0)
}

/** `[code, value]`：code 就是点上标，长度只到该系列自己的长度（绝不补到组最长）。 */
function toPairs(values: (number | null)[]): [number, number | null][] {
  return values.map((v, i) => [i, v] as [number, number | null])
}

interface LineStyle {
  type: string | number[]
  width: number
  color: string
}

interface SeriesExtras {
  symbolSize?: number
  /** 均值线才开：每个点的数值标签（截图口径）。 */
  labels?: boolean
  /** 数值标签色；缺省回退 textColor。 */
  labelColor?: string
}

function lineSeries(
  name: string,
  values: (number | null)[],
  style: LineStyle,
  extra: SeriesExtras = {},
) {
  const base = {
    name,
    type: 'line',
    symbol: 'circle',
    symbolSize: extra.symbolSize ?? MARKER_SIZE,
    showSymbol: true,
    showAllSymbol: true,
    sampling: 'lttb',
    connectNulls: false,
    lineStyle: style,
    // 图例与圆点都按 itemStyle 取色：与线同色，图例里不会冒出色不对的块。
    itemStyle: { color: style.color },
    data: toPairs(values),
  }
  if (!extra.labels) return base
  return {
    ...base,
    label: {
      show: true,
      position: 'top',
      color: extra.labelColor ?? style.color,
      fontSize: chartFontSize.micro,
      formatter: (p: { value?: (number | null)[] }) => formatWeightLabel(p.value?.[1]),
    },
    // 64 点的组标签会互相压住；页面上隐藏重叠标签，Excel 导出侧仍全量写。
    labelLayout: { hideOverlap: true },
  }
}

export function buildWeightOption(group: WeightGroupDto, o: BuildOptions): EChartsOption {
  const color = groupColor(o.colors, group.index)
  const series = group.series.map((s, within) => lineSeries(s.name, s.values, {
    type: DASH_BY_WITHIN_GROUP[within % DASH_BY_WITHIN_GROUP.length],
    width: LINE_WIDTH,
    color,
  }))
  // 关掉均值就是不加这一条（不是「加了再藏」）：spec §5.2「按可见组重建 series」。
  if (o.showMean) {
    series.push(lineSeries(group.mean.name, group.mean.values, {
      type: MEAN_DASH, width: MEAN_WIDTH, color: o.meanColor,
    }, { symbolSize: 0, labels: true, labelColor: o.labelColor ?? o.textColor }))
  }

  // 轴名不画：卡头已有测试项名与 Code 数，画布里的 Weight/Code 名在 609px 卡宽下会被
  // 卡头或右缘裁掉（2026-10-20 实机截图实证），也让图更干净。
  const axis = () => ({
    type: 'value' as const,
    axisLine: { lineStyle: { color: o.axisLineColor } },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: o.splitLineColor ?? o.axisLineColor } },
    axisLabel: { color: o.textColor, fontSize: chartFontSize.micro },
  })

  const showLegend = o.showLegend !== false

  return {
    backgroundColor: 'transparent',
    animation: false,
    // 可见标题由图表卡头承载；保留 text 供 T2/导出语义对照，但不再在画布内重复渲染。
    title: { show: false, text: o.titleText, textStyle: { color: o.textColor, fontSize: chartFontSize.dense } },
    // 分组后图例只剩本组 4/5 条：它成了「组内线型」的对照载体（导出侧同口径）。
    legend: {
      show: showLegend,
      bottom: 0,
      type: 'scroll',
      textStyle: { color: o.textColor, fontSize: chartFontSize.micro },
      formatter: (name: string) => legendLabel(name, group.name),
      itemWidth: 24,
      itemHeight: 10,
    },
    tooltip: {
      trigger: 'item',
      // 点到哪条报哪条：系列名 + code + 值（只显示组名会丢「是组内哪一条」）。
      formatter: (p: { seriesName?: string; value?: (number | null)[] }) =>
        `${p.seriesName ?? ''}<br/>code ${p.value?.[0] ?? '-'} · ${formatWeightLabel(p.value?.[1])}`,
    },
    // 右侧 34 给最右点的均值标签留位（14 在 609px 卡宽下会把末位标签裁掉）。
    // bottom 40 是给底部图例行留的（containLabel 已把轴标签算进网格），图例隐藏就收回到 16。
    grid: { left: 8, right: 34, top: 20, bottom: showLegend ? 40 : 16, containLabel: true },
    // x 只到本组最长系列：每个测试项独立缩放，短组不会被最长组拖成一根竖线。
    xAxis: [{ ...axis(), min: 0, max: groupCodeMax(group), splitLine: { show: false } }],
    yAxis: [{ ...axis(), scale: true, axisLine: { show: false } }],
    series,
  } as EChartsOption
}
