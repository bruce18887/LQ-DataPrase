/**
 * 3D 站点柱阵（echarts-gl bar3D）的 option 纯构造
 * ────────────────────────────────────────────────
 * 与 dockGeometry.ts 同先例：纯模型放 composables/，判据能由 T2 直测
 * （test/unit/site3dOption.spec.ts 钉 spec §10 的 ①–⑧）。
 * 视觉常数（机位、箱体、柱截面比例、轴间距）取自 2026-11-04 原型实测
 * （`specs/2026-11-04-3d-site-barchart-proto.html`，§5/§6）；字号/字色取 token，不在此列。
 * `opacity` 是**有意的偏离**：原型关渐隐时是 0.92，本批按拍板做成不透明 1（见 series 内注释）。
 * 改动上面任何一项都要连原型一起回归，别按「看着更顺眼」调。
 */
import { chartFontSize } from '../../../theme/typography'
import { formatAxisValue, formatPercent, getSiteColors8 } from '../../../utils/chart-bar'
import type { EChartsColors, Grid3DStyle } from '../../../utils/echarts-tokens'
import { activeBinIndices, type OutlierBounds, type OutlierMode } from './histogramBins'

/** 箱体（世界单位）。barSize 的两个 fill 只有和这组尺寸绑在一起才等价，换尺寸要同步重算（§6.3）。 */
export const SITE3D_BOX = { width: 132, height: 74, depth: 120 }
/**
 * 默认机位：alpha 低于 25 时后排被前排整根挡住；beta 取负会把值轴甩到左后方。
 * 初始 option 与面板头「回到默认视角」共用这一份（§10 判据 ⑧）。
 */
export const SITE3D_VIEW = { alpha: 28, beta: 30, distance: 245, zoom: 1 }
/**
 * 柱截面占格比例。宽度一度取过 0.85：正机位没问题，转到 alpha 35 / beta −25 时
 * 相邻 bin 沿 x 粘成一条斜脊（§6.6），0.62 才在任意角度保持单根可辨；
 * 纵深 0.30 是为了不把每根柱摊成斜板（§6.3）。
 */
export const SITE3D_BAR_FILL = { width: 0.62, depth: 0.3 }
/**
 * 平涂下 light 色板第 7 格 `#BBBBBB` 在白底几乎不可辨（§6.4，用户 2026-11-04 拍板）：
 * **只在这里**换成深灰，`SITE_COLORS_8_LIGHT` 本体不动——它还服务 2D 直方图、序列图、
 * 晶圆图、多文件图，以及相关性页的两处（`CorrelationToolsTab.vue` 与 `scatter-option.ts`）：
 * `grep -rln "getSiteColors8\|SITE_COLORS_8_LIGHT" src` 实测 6 个消费文件（其余命中是
 * chart-bar.ts / echarts-tokens.ts 的定义与注释），箱线图与站点表零引用。
 * 动本体等于同时改这六处的视觉。取 #6b7280 是复用 textColor 那把灰。
 */
export const SITE3D_LIGHT_SLOT7 = '#6b7280'

export interface Site3DTheme {
  isDark: boolean
  colors: EChartsColors
  /** utils/echarts-tokens.ts 的 grid3DStyle(colors)：颜色/字号/字族单一来源 */
  grid3D: Grid3DStyle
}

export interface Site3DBuildOptions {
  /** 与 2D 同一把异常值档位（§8）；取值 'clip' | 'exclude' | 'off' */
  mode: OutlierMode
  /** 只有 'RDL' 会放宽裁剪边界，与 2D 同规则（档位见 ChartConfigPanel.vue 的 el-option value） */
  rangeType: string
  /** 当前参数名，进 x 轴名 */
  param: string
}

/** 后端 histogram 响应里本图消费的那几项 */
interface Site3DResult {
  bin_centers?: number[]
  bin_counts?: number[]
  site_histograms?: Record<string, number[]> | null
  outlier_info?: OutlierBounds | null
  lower_limit?: number | null
  upper_limit?: number | null
  unit?: string | null
}

export function site3dPalette(isDark: boolean): readonly string[] {
  const pal = getSiteColors8(isDark)
  if (isDark) return pal
  return pal.map((c, i) => (i === 6 ? SITE3D_LIGHT_SLOT7 : c))
}

/** 柱截面绝对世界尺寸：[x 方向宽, y 方向厚]，两个分量各管一个方向（§6.3） */
export function site3dBarSize(binCount: number, siteCount: number): [number, number] {
  const bandX = binCount > 0 ? SITE3D_BOX.width / binCount : 0
  const bandY = siteCount > 0 ? SITE3D_BOX.depth / siteCount : 0
  return [bandX * SITE3D_BAR_FILL.width, bandY * SITE3D_BAR_FILL.depth]
}

/** 正交 + 实测机位：初始 option 与复位按钮的共同来源 */
export function defaultViewControl(): Record<string, unknown> {
  return {
    projection: 'orthographic',
    alpha: SITE3D_VIEW.alpha,
    beta: SITE3D_VIEW.beta,
    distance: SITE3D_VIEW.distance,
    zoom: SITE3D_VIEW.zoom,
    rotateSensitivity: 0.8,
    zoomSensitivity: 0.7,
  }
}

/** 复位：合并写 viewControl（原型 :256 的同形写法；notMerge 会把柱数据一起换掉） */
export function applyDefaultView(
  chart: { setOption: (...args: any[]) => unknown } | null | undefined,
): void {
  if (!chart) return
  chart.setOption({ grid3D: { viewControl: defaultViewControl() } })
}

/**
 * 构建 option；无 Site 列 / 无网格时返回 **null**（不返回空 option——空 option
 * 会让 useChart 建出一张没有轴的空 canvas，用户看到的是「图坏了的空白框」而不是提示）。
 */
export function buildSite3DOption(
  result: Site3DResult | null | undefined,
  theme: Site3DTheme,
  opts: Site3DBuildOptions,
): Record<string, any> | null {
  const siteHists = result?.site_histograms
  const binCenters: number[] = result?.bin_centers ?? []
  if (!result || !siteHists || binCenters.length === 0) return null

  // 站点序号升序：Site 名的数字序就是 y 轴的排布序，字符串序会把 Site10 排到 Site2 前面
  const sites = Object.keys(siteHists).sort((a, b) => Number(a) - Number(b))
  if (sites.length === 0) return null

  // 与 2D 同一把尺子（§8）：clip 边界外的 bin 既不进 x 轴标签，也不生成柱。
  // 口径单一来源是 histogramBins.activeBinIndices，这里不许再写一遍边界比较。
  const active = activeBinIndices({
    binCenters,
    handlingMode: opts.mode,
    outlierInfo: result.outlier_info,
    rangeType: opts.rangeType,
    lowerLimit: result.lower_limit,
    upperLimit: result.upper_limit,
  })
  const binLabels = active.map((i) => formatAxisValue(binCenters[i]))
  const siteLabels = sites.map((s) => `Site${s}`)
  const counts: number[] = result.bin_counts ?? []
  const pal = site3dPalette(theme.isDark)
  const c = theme.colors

  const rows: { value: [number, number, number] }[] = []
  sites.forEach((site, s) => {
    const hists: number[] = siteHists[site] ?? []
    active.forEach((bi, x) => {
      const v = hists[bi] ?? 0
      // 零占比不生成柱体：满矩阵是 8 Site × 26 bin = 208 格，全画会让 GL 侧的拾取射线
      // 命中零高柱、tooltip 弹出一堆 0%。空格占比随数据变（仓内无可重跑的实测口径），
      // 所以这里不写「多少成是空的」，只由「零占比不生成」那条判据钉行为。
      if (!(v > 0)) return
      rows.push({ value: [x, s, v] })
    })
  })

  const [barW, barD] = site3dBarSize(binLabels.length, sites.length)
  const unit = result.unit ?? ''
  const nameStyle = theme.grid3D.nameTextStyle

  return {
    // GL 图层本身以 transparent 创建（Grid3DView.js:35）⇒ 场景不铺底，ChartPanel 的
    // CSS 背景直接透出，双主题不必为 3D 单开背景处理
    backgroundColor: 'transparent',
    tooltip: {
      backgroundColor: c.tooltipBg,
      borderColor: c.tooltipBorder,
      borderWidth: 1,
      textStyle: { color: c.tooltipText, fontSize: chartFontSize.dense },
      // value = [bin 位次, site 位次, 占比]；n= 来自 bin_counts，那是**该 bin 的全站点
      // 计数**（后端只下发占比，逐 Site 原始计数没有），文案不许缩成像 Site 级计数。
      // 分母口径：`histogram.py:119` 先 filter_finite，所以 Σ bin_counts ≡ total_count
      // （都是有限非空值数）；但 **clip 档位下可见柱是子集**，那时「各 bin 相加 = N」就不成立，
      // 所以界面上不写这句承诺（spec §3 表格 bin_counts 行）。
      formatter: (p: any) => {
        const [x, s, v] = p.value
        const n = counts[active[x]] ?? 0
        return `<b>${siteLabels[s]}</b> · ${binLabels[x]}<br/>占比 ${formatPercent(v)}%（全站点该 bin n=${n}）`
      },
    },
    visualMap: {
      show: true,
      type: 'piecewise',
      dimension: 1,
      orient: 'vertical',
      right: 6,
      top: 'middle',
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 6,
      // 实测：`categories` + `inRange.color` 时 192 根柱一根都不画，必须 pieces。
      // 副作用正好：gl 系列不进 ECharts legend，所以这份 piecewise 就是本图唯一色键，
      // label 直接把色块标成 Site 名（§6.1）
      // `% 8` 与 2D 直方图同规则（站点数超过 8 就循环取色）。代价写在明处：站数 >8 时
      // 第 8 个之后的格子会复现前 8 格的色（含 light 那个深灰覆盖格），色键因此只能按
      // 序号区分、不能按颜色区分——2D 也是这样，别把这里改成「扩展色板」而不改那边。
      pieces: siteLabels.map((label, i) => ({ value: i, label, color: pal[i % 8] })),
      textStyle: { color: c.axisLabelColor, fontSize: chartFontSize.dense },
    },
    grid3D: {
      ...theme.grid3D,
      boxWidth: SITE3D_BOX.width,
      boxHeight: SITE3D_BOX.height,
      boxDepth: SITE3D_BOX.depth,
      viewControl: defaultViewControl(),
    },
    // x 用 category（官方两个结构型 bar3D 示例都是 category，柱宽由 category 轴等分）
    // ⇒ 规格限只能吸附到最近的 bin，画出来是误导性的精确，本图不画 LSL/USL（§7）。
    // 2D 直方图的轴范围恒按**全量** binCenters，3D 是 category 轴、被裁的档不进标签——
    // 两边轴行为有意不同，钉的是可见柱集合一致（§8），别来「统一」它。
    xAxis3D: {
      type: 'category',
      data: binLabels,
      name: `${opts.param}${unit ? ` (${unit})` : ''}`,
      nameLocation: 'middle',
      nameGap: 30,
      nameTextStyle: nameStyle,
    },
    yAxis3D: { type: 'category', data: siteLabels, name: 'Site', nameTextStyle: nameStyle },
    zAxis3D: { type: 'value', name: '占比 %', min: 0, nameTextStyle: nameStyle },
    // 刻意不放 toolbox：gl 画在第二张 canvas 上，saveAsImage 只会存出没有柱体的图。
    // 也不写 axisPointer：bar3D tooltip 走默认 item 触发，写了是无人消费的死配置（§5 末条）。
    series: [
      {
        type: 'bar3D',
        data: rows,
        // 平涂不吃光。这与 utils/echarts-tokens.ts 的 grid3DStyle() `light` 字段（main 0/
        // ambient 1、不写 shadow）是**跨模块耦合**：那两条强度成立的前提就是这一行
        // 'color'，改成 lambert/normal 会立刻打光、两边要一起改（那边的注释已点名这里）。
        // gl 默认即 'color'，是官方示例改成了 lambert（§5 表第一行）。
        shading: 'color',
        bevelSize: 0.22,
        bevelSmoothness: 2,
        barSize: [barW, barD],
        // 纵深渐隐默认关（§6.5）：平涂 + 降 opacity 会把 Site 色饱和吃掉，
        // 而 Site 身份在这张图里就靠颜色。原型**关掉渐隐时仍留着 0.92**（proto:219），
        // 本批按拍板取满不透明的 1——这是与原型唯一有意的数值偏离，别照原型「对齐」回 0.92。
        itemStyle: { opacity: 1 },
        label: { show: false },
        emphasis: {
          label: {
            show: true,
            formatter: (p: any) => `${formatPercent(p.value[2])}%`,
            textStyle: { color: c.textColor, fontSize: chartFontSize.micro, backgroundColor: 'transparent' },
          },
        },
      },
    ],
  }
}
