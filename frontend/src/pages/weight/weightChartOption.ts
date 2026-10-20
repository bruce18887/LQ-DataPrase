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
  /** 当前主题的 8 色板，即 `echarts-theme.ts` 的 `colors.seriesColors`。 */
  colors: string[]
  /** 均值线色，由调用方给（Task 8 传 `colors.textColor`）。 */
  meanColor: string
  textColor: string
  axisLineColor: string
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
  textColor?: string
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
      color: extra.textColor,
      fontSize: chartFontSize.micro,
      formatter: (p: { value?: (number | null)[] }) =>
        p.value?.[1] == null ? '' : String(p.value[1]),
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
    }, { symbolSize: 0, labels: true, textColor: o.textColor }))
  }

  const axis = (name: string) => ({
    type: 'value' as const,
    name,
    axisLine: { lineStyle: { color: o.axisLineColor } },
    splitLine: { lineStyle: { color: o.axisLineColor } },
    axisLabel: { color: o.textColor, fontSize: chartFontSize.micro },
    nameTextStyle: { color: o.textColor },
  })

  return {
    backgroundColor: 'transparent',
    animation: false,
    title: { text: o.titleText, textStyle: { color: o.textColor, fontSize: chartFontSize.dense } },
    // 分组后图例只剩本组 4/5 条：它成了「组内线型」的对照载体（导出侧同口径）。
    legend: {
      show: true,
      bottom: 0,
      type: 'scroll',
      textStyle: { color: o.textColor, fontSize: chartFontSize.micro },
      itemWidth: 24,
      itemHeight: 10,
    },
    tooltip: {
      trigger: 'item',
      // 点到哪条报哪条：系列名 + code + 值（只显示组名会丢「是组内哪一条」）。
      formatter: (p: { seriesName?: string; value?: (number | null)[] }) =>
        `${p.seriesName ?? ''}<br/>code ${p.value?.[0] ?? '-'} · ${p.value?.[1] ?? '-'}`,
    },
    grid: { left: 56, right: 20, top: 34, bottom: 48, containLabel: false },
    // x 只到本组最长系列：每个测试项独立缩放，短组不会被最长组拖成一根竖线。
    xAxis: [{ ...axis('Code'), min: 0, max: groupCodeMax(group) }],
    yAxis: [{ ...axis('Weight'), scale: true }],
    series,
  } as EChartsOption
}
