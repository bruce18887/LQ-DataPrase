/**
 * T2：3D 站点柱阵 option 构造（specs/2026-11-04 §10 判据 ①–⑧）。
 *
 * 这批断言里每一条都挡着一个**已经真踩过**的形状，不是装饰：
 * ① 轴型与 bin 对齐——x 必须是 category（bar3D 的柱宽由 category 轴等分，value 轴会退化成一根）；
 * ② shading/projection——lambert 会把 #0077BB 渲成别的色，色盲校验白做；perspective 的近大远小让柱高跨 Site 不可比；
 * ③ 色键走 pieces 且第 7 格换深灰——`categories` + `inRange.color` 实测一根柱都不画；#BBBBBB 在白底几乎不可辨；
 * ④ 主题对称由 echartsTokens.spec.ts 量，这里只验 option 里的颜色确实来自传入 colors；
 * ⑤ barSize 两个分量各管一个方向且**不相等**——写成单一 fill 同乘两方向就退回「3.85 宽 × 10.5 厚」的板状，
 *    用户在斜方位角看到的「歪」会复现（§6.3）；
 * ⑥ 无 Site 列返回 null 而不是空 option（组件据此走提示分支）；
 * ⑦ 3D 用的 bin 集合 === histogramBins 给 2D 的 activeIndices（§8 两图同口径）；
 * ⑧ 初始机位与「回到默认视角」读同一份导出值（§4，防两处各写一份漂移）。
 */
import { describe, expect, it } from 'vitest'

import {
  SITE3D_BAR_FILL,
  SITE3D_BOX,
  SITE3D_LIGHT_SLOT7,
  SITE3D_VIEW,
  applyDefaultView,
  applyView,
  buildSite3DOption,
  defaultSite3DView,
  defaultViewControl,
  site3dBarSize,
  site3dPalette,
  viewControlFromView,
  type Site3DTheme,
} from '../../src/pages/analysis/composables/site3dOption'
import type { Site3DView } from '../../src/pages/analysis/composables/site3dView'
import { activeBinIndices } from '../../src/pages/analysis/composables/histogramBins'
import { formatAxisValue } from '../../src/utils/chart-bar'
import {
  ECHARTS_COLORS_LIGHT,
  ECHARTS_COLORS_NIGHT,
  echartsColorsFor,
  grid3DStyle,
} from '../../src/utils/echarts-tokens'
import { SITE_COLORS_8_LIGHT, SITE_COLORS_8_NIGHT } from '../../src/utils/chart-bar'

const NB = 26          // 后端 binning.build_bin_grid：1 underflow + 24 正常 + 1 overflow
const NS = 8

/**
 * theme() 的选板必须走 echartsColorsFor（纯函数，单一来源）——计划正文这行原样写的是
 * `isDark ? ECHARTS_COLORS_NIGHT : ECHARTS_COLORS_LIGHT`，那是 Task 4（M10b）刚从
 * echarts-theme.ts 清掉的「第二份事实来源」形状，测试助手自己再抄一遍就是把它种回来。
 */
function theme(isDark = false): Site3DTheme {
  const colors = echartsColorsFor(isDark)
  return { isDark, colors, grid3D: grid3DStyle(colors) }
}

/** 8 Site × 26 bin：Site 数越大峰越往右移（造一个「不旋转也能一眼辨出偏移」的形状） */
function mkResult(over: Record<string, unknown> = {}): any {
  const binCenters = Array.from({ length: NB }, (_, i) => -1 + i * 0.1)
  const site = (shift: number) => binCenters.map((c) => Math.max(0, 8 - Math.abs(c - shift) * 10))
  const site_histograms: Record<string, number[]> = {}
  for (let s = 1; s <= NS; s++) site_histograms[String(s)] = site(0.2 + s * 0.05)
  return {
    bin_centers: binCenters,
    bin_percentages: binCenters.map((_, i) => 4 - Math.abs(i - 12) * 0.1),
    bin_counts: binCenters.map((_, i) => 100 + i),
    total_count: 10000,
    unit: 'nA',
    lower_limit: -0.5,
    upper_limit: 1.0,
    // 夹具形状说明：后端无异常值时通常发数字（`outliers.py:45-51` 的 empty_result 给 0.0），
    // 但 NaN/±Inf 的 bound 经 `clean_data` 会变成 JSON null，而**此时 `has_outliers` 仍可能是
    // false**（复审用 `[-1e308, 0, 1e308, 1e308]` 实测：has_outliers=False、bounds=±inf）——
    // 所以 null 与 has_outliers 不互斥。本行取 null 是为 `finiteOr` 那道闸兜底，
    // 与 histogramBins.spec.ts 的 null 用例同一契约。
    outlier_info: { has_outliers: false, lower_bound: null, upper_bound: null, outlier_count: 0, normal_count: 10000 },
    site_histograms,
    ...over,
  }
}

const build = (r: any, over: Partial<{ mode: 'clip' | 'exclude' | 'off'; rangeType: string; param: string; view: Site3DView }> = {}, isDark = false) =>
  buildSite3DOption(r, theme(isDark), { mode: 'off', rangeType: 'RDL', param: 'Kelvin_VIN', ...over })

describe('① 轴型与 bin 网格', () => {
  it('x/y 是 category、z 是 value，且 x 逐格等于 bin_centers', () => {
    const o = build(mkResult())
    expect(o!.xAxis3D.type).toBe('category')
    expect(o!.yAxis3D.type).toBe('category')
    expect(o!.zAxis3D.type).toBe('value')
    expect(o!.xAxis3D.data).toHaveLength(NB)
    expect(o!.xAxis3D.data[0]).toBe('-1')
    expect(o!.xAxis3D.data[1]).toBe('-0.9')
    expect(o!.yAxis3D.data).toEqual(Array.from({ length: NS }, (_, i) => `Site${i + 1}`))
  })

  it('轴名带参数与单位，与 2D 直方图标题同族信息', () => {
    const o = build(mkResult(), { param: 'Vth' })
    expect(o!.xAxis3D.name).toBe('Vth (nA)')
    expect(o!.yAxis3D.name).toBe('Site')
    expect(o!.zAxis3D.name).toBe('占比 %')
  })

  it('柱体三元组 = [bin 位次, site 位次, 占比]，零占比不生成', () => {
    const r = mkResult()
    r.site_histograms['1'] = r.site_histograms['1'].map((v: number, i: number) => (i % 2 ? 0 : v))
    const o = build(r)
    const data = o!.series[0].data
    // 满矩阵是 NS×NB = 208 格；把 Site1 的一档占比清零之后必须**恰好**少生成那么多根。
    // 用独立 oracle（逐 Site 数 >0 的格）比值，而不是只断言「少于 208」——后者放过
    // 「少生成得多/少生成得少」两类写错的实现。
    const expectBars = Object.values(r.site_histograms as Record<string, number[]>)
      .reduce((n, arr) => n + arr.filter((v: number) => v > 0).length, 0)
    expect(data.length).toBe(expectBars)
    expect(expectBars).toBeLessThan(NS * NB)
    for (const d of data.slice(0, 5)) {
      expect(d.value).toHaveLength(3)
      expect(d.value[2]).toBeGreaterThan(0)
    }
  })

  it('逐根柱体 = [bin 位次, site 位次, 该 Site 在该 bin 的占比]（独立 oracle 全量比值）', () => {
    // 只比长度与「x 值域在范围内」会同时放过两类真错误（质量复审实测 B/D 存活）：
    // ① 高度取错口径（把 counts[active[x]] 的计数当占比）；② 三元组换序（[s, x, v]）。
    // 后者尤其阴：clip 下 active.length=16 > 8 个 Site，`max(xs) < active.length` 照样成立。
    const r = mkResult()
    const o = build(r)
    const sites = Object.keys(r.site_histograms).sort((a, b) => Number(a) - Number(b))
    const rows: number[][] = []
    sites.forEach((site, s) => {
      r.site_histograms[site].forEach((v: number, bi: number) => {
        if (v > 0) rows.push([bi, s, v])
      })
    })
    expect(o!.series[0].data.map((d: any) => d.value)).toEqual(rows)
  })
})

describe('② 平涂与正交投影（§5）', () => {
  it('shading=color、projection=orthographic', () => {
    const o = build(mkResult())
    expect(o!.series[0].shading).toBe('color')
    expect(o!.grid3D.viewControl.projection).toBe('orthographic')
  })

  it('opacity 不动（默认 1）：纵深渐隐会吃掉 Site 之间唯一的身份通道', () => {
    expect(build(mkResult())!.series[0].itemStyle.opacity).toBe(1)
  })
})

describe('③ 色键：pieces + 第 7 格覆盖', () => {
  it('用 pieces:[{value,label,color}]，不是 categories + inRange.color', () => {
    const o = build(mkResult())
    expect(o!.visualMap.type).toBe('piecewise')
    expect(o!.visualMap.dimension).toBe(1)
    expect(o!.visualMap.pieces).toHaveLength(NS)
    // 逐项比值（不是只看 pieces[0]）：只 matchObject 第一项的话，把 label 全改成 'Site1'
    // 或把 color 写成 pal[0] 都 31/31 绿——图例就成了假的（质量复审实测 C 存活）。
    expect(o!.visualMap.pieces).toEqual(
      Object.keys(mkResult().site_histograms).map((site, i) => ({
        value: i,
        label: `Site${site}`,
        color: site3dPalette(false)[i % 8],
      })),
    )
    expect(o!.visualMap.inRange).toBeUndefined()
  })

  it('light 第 7 格换成深灰，其余 7 格与 SITE_COLORS_8_LIGHT 逐字相等', () => {
    const pal = site3dPalette(false)
    expect(pal[6]).toBe(SITE3D_LIGHT_SLOT7)
    expect(pal[6]).not.toBe(SITE_COLORS_8_LIGHT[6])
    expect(pal.map((c, i) => (i === 6 ? null : c))).toEqual(
      SITE_COLORS_8_LIGHT.map((c, i) => (i === 6 ? null : c)),
    )
  })

  it('night 整套与 SITE_COLORS_8_NIGHT 逐字相等（只治浅底那格，别顺手改深底）', () => {
    expect(site3dPalette(true)).toEqual([...SITE_COLORS_8_NIGHT])
  })

  it('pieces 的色 = 3D 专用色板（不是 2D 色板，也不是 seriesColors 主题色）', () => {
    const o = build(mkResult(), {}, false)
    expect(o!.visualMap.pieces.map((p: any) => p.color)).toEqual([...site3dPalette(false)])
    expect(o!.visualMap.pieces.map((p: any) => p.color)).not.toEqual([...ECHARTS_COLORS_LIGHT.seriesColors])
  })

  it('Site 数 > 8 时按 % 8 循环取色（与 2D 直方图同规则）', () => {
    const r = mkResult()
    r.site_histograms = { ...r.site_histograms }
    for (let s = 9; s <= 10; s++) r.site_histograms[String(s)] = r.site_histograms['1']
    const o = build(r)
    expect(o!.visualMap.pieces).toHaveLength(10)
    expect(o!.visualMap.pieces[8].color).toBe(o!.visualMap.pieces[0].color)
    expect(o!.visualMap.pieces[9].color).toBe(o!.visualMap.pieces[1].color)
  })
})

describe('④ 颜色来自传入 theme，不写死', () => {
  it('night 分支下 tooltip 与轴标签取 night token', () => {
    const o = build(mkResult(), {}, true)
    expect(o!.tooltip.backgroundColor).toBe(ECHARTS_COLORS_NIGHT.tooltipBg)
    expect(o!.tooltip.textStyle.color).toBe(ECHARTS_COLORS_NIGHT.tooltipText)
    expect(o!.visualMap.textStyle.color).toBe(ECHARTS_COLORS_NIGHT.axisLabelColor)
    expect(o!.grid3D.axisLine.lineStyle.color).toBe(ECHARTS_COLORS_NIGHT.splitLineColor)
  })

  it('option 里没有 CSS 变量混进 setOption（R7②）', () => {
    expect(JSON.stringify(build(mkResult()))).not.toMatch(/var\(--/)
  })

  it('背景 transparent：面板 CSS 底色透出，GL 图层不铺自己的底', () => {
    expect(build(mkResult())!.backgroundColor).toBe('transparent')
  })

  it('不放 ECharts toolbox：gl 画在第二张 canvas 上，saveAsImage 只会存出没有柱体的图', () => {
    // 用 not.toHaveProperty 而不是 toBeUndefined：后者放过 `toolbox: undefined` 这种写法，
    // 一旦有人改回显式 undefined 再顺手加字段，判据就变成装饰
    expect(build(mkResult())).not.toHaveProperty('toolbox')
  })
})

describe('⑤ barSize 是两个方向各自的绝对世界单位', () => {
  it('宽 = boxWidth/NB × 0.62、厚 = boxDepth/NS × 0.30，且两者不相等', () => {
    const o = build(mkResult())
    const [w, d] = o!.series[0].barSize
    expect(w).toBeCloseTo(SITE3D_BOX.width / NB * SITE3D_BAR_FILL.width, 10)
    expect(d).toBeCloseTo(SITE3D_BOX.depth / NS * SITE3D_BAR_FILL.depth, 10)
    // 这一条挡的是「写成单一 fill 同乘两个方向」：那样会退回板状截面（§6.3）
    expect(w).not.toBeCloseTo(d, 6)
  })

  it('bin 数变少（clip 之后）时宽跟着 band 重算，不是沿用满格值', () => {
    const full = site3dBarSize(NB, NS)[0]
    const clipped = site3dBarSize(NB - 6, NS)[0]
    expect(clipped).toBeGreaterThan(full)
  })

  it('箱体与机位是实测那一组数（改了要连原型一起回归）', () => {
    const g = build(mkResult())!.grid3D
    expect([g.boxWidth, g.boxHeight, g.boxDepth]).toEqual([SITE3D_BOX.width, SITE3D_BOX.height, SITE3D_BOX.depth])
    expect(SITE3D_BOX).toEqual({ width: 132, height: 74, depth: 120 })
    expect(SITE3D_BAR_FILL).toEqual({ width: 0.62, depth: 0.3 })
  })
})

describe('⑥ 无 Site 列 / 空数据 → null', () => {
  it('site_histograms 为 null 时返回 null（组件走 el-alert 分支）', () => {
    expect(build(mkResult({ site_histograms: null }))).toBeNull()
  })

  it('site_histograms 为空对象时返回 null', () => {
    expect(build(mkResult({ site_histograms: {} }))).toBeNull()
  })

  it('result 为 null/undefined 时返回 null，不抛', () => {
    expect(build(null)).toBeNull()
    expect(build(undefined)).toBeNull()
  })

  it('bin_centers 缺失时返回 null（没网格就没轴）', () => {
    // 防御性形状：后端只要有 result 就发 26 个中心（binning.build_bin_grid），空数组线上拿不到。
    // 留着是因为组件那侧（Task 7）会把 result 原样喂进来，空网格走到这儿必须是「不建图」而不是空白 canvas。
    expect(build(mkResult({ bin_centers: [] }))).toBeNull()
  })

  it('单 Site 文件照常出图（后端单站点也会填 site_histograms）', () => {
    const o = build(mkResult({ site_histograms: { '4': mkResult().site_histograms['4'] } }))
    expect(o!.yAxis3D.data).toEqual(['Site4'])
    expect(o!.visualMap.pieces).toHaveLength(1)
  })
})

describe('⑦ 与 2D 同一套 bin 口径（§8）', () => {
  // 夹具是「只含 IQR 的窄边界」（lower/upper_bound 0.1/0.6）配更宽的规格限（-0.5/1.0）。
  // 这是**纯函数契约**用例：验 clipBounds 里 RDL 放宽那一支的形状。线上载荷拿不到这个形状——
  // 后端 outliers.py:78-83 对每个档位都已用同一对 rdl 把 bound 展过界，展完即响应里的
  // lower_limit/upper_limit，所以真实数据下放宽支是恒等（histogramBins.ts:49-53 注释）。
  const clipped = mkResult({
    outlier_info: { has_outliers: true, lower_bound: 0.1, upper_bound: 0.6, outlier_count: 90, normal_count: 9910 },
  })

  it('clip 下 x 轴标签集合 === histogramBins 给 2D 的 activeIndices 对应标签', () => {
    const o = build(clipped, { mode: 'clip' })
    const active = activeBinIndices({
      binCenters: clipped.bin_centers,
      handlingMode: 'clip',
      outlierInfo: clipped.outlier_info,
      rangeType: 'RDL',
      lowerLimit: clipped.lower_limit,
      upperLimit: clipped.upper_limit,
    })
    expect(o!.xAxis3D.data).toHaveLength(active.length)
    // 逐元素等值：只断言长度与 x 值域的话，`binCenters[x]`（按位次取而不是按原 bin 下标取）
    // 这种整体错位一条都不红——它长度对、值域也对，但每根柱顶的刻度值全是隔壁 bin 的。
    expect(o!.xAxis3D.data).toEqual(active.map((i: number) => formatAxisValue(clipped.bin_centers[i])))
    expect(active.length).toBeLessThan(NB)
    // 柱体的 x 位次必须落在 0..active.length-1（越界即两图各数各的）。
    // 显式标 Set<number>：`data` 是 any[]，不标就成 Set<unknown>，`Math.max(...xs)` 在
    // `vue-tsc -b`（构建档，覆盖 test/）里是 TS2345——`-p tsconfig.app.json` 不检 test/，量不到。
    const xs = new Set<number>(o!.series[0].data.map((d: any) => d.value[0] as number))
    expect(Math.max(...xs)).toBeLessThan(active.length)
  })

  it('RDL 放宽在 3D 里同样生效（边界并上规格限）——纯函数契约，见上注', () => {
    const tight = build(clipped, { mode: 'clip', rangeType: 'CL' })
    const wide = build(clipped, { mode: 'clip', rangeType: 'RDL' })
    expect(wide!.xAxis3D.data.length).toBeGreaterThan(tight!.xAxis3D.data.length)
  })

  it('exclude 与 off 一样不藏柱（只 clip 过滤）', () => {
    expect(build(clipped, { mode: 'exclude' })!.xAxis3D.data).toHaveLength(NB)
  })

  it('tooltip 取的是原 bin 下标对应的 bin_counts，并把「全站点」写进文案', () => {
    const o = build(clipped, { mode: 'clip' })
    const active = activeBinIndices({
      binCenters: clipped.bin_centers, handlingMode: 'clip', outlierInfo: clipped.outlier_info,
      rangeType: 'RDL', lowerLimit: clipped.lower_limit, upperLimit: clipped.upper_limit,
    })
    const x = o!.series[0].data[0].value[0]
    const html = o!.tooltip.formatter({ value: [x, 0, 1.23] })
    expect(html).toContain('全站点该 bin n=' + clipped.bin_counts[active[x]])
    expect(html).toContain('1.23%')
    expect(html).toContain('Site1')
    // 整句等值：只断言「含 1.23%」时，把 formatPercent 换成 toFixed(2) 一条都不红
    // （质量复审实测 E 存活），而 0.0005% 这种极小占比会被四舍五入成 0.00%。
    const n0 = clipped.bin_counts[active[x]]
    expect(o!.tooltip.formatter({ value: [x, 0, 1.23] })).toBe(
      `<b>Site1</b> · ${o!.xAxis3D.data[x]}<br/>占比 1.23%（全站点该 bin n=${n0}）`,
    )
    expect(o!.tooltip.formatter({ value: [x, 0, 0.0005] })).toBe(
      `<b>Site1</b> · ${o!.xAxis3D.data[x]}<br/>占比 <0.001%（全站点该 bin n=${n0}）`,
    )
  })
})

describe('⑧ 机位常量单一来源', () => {
  it('初始 viewControl 与复位目标读同一份 SITE3D_VIEW', () => {
    expect(SITE3D_VIEW).toEqual({ alpha: 28, beta: 30, distance: 245, orthographicSize: 150 })
    const vc = build(mkResult())!.grid3D.viewControl
    expect(vc.alpha).toBe(SITE3D_VIEW.alpha)
    expect(vc.beta).toBe(SITE3D_VIEW.beta)
    expect(vc.distance).toBe(SITE3D_VIEW.distance)
    expect(vc.orthographicSize).toBe(SITE3D_VIEW.orthographicSize)
    expect(vc.center).toEqual([0, 0, 0])
    expect(vc).toEqual(defaultViewControl())
  })

  it('opts.view 生效：机位逐字段来自传入视角（记忆回放）', () => {
    const v: Site3DView = { alpha: 12, beta: -34, distance: 300, orthographicSize: 88, center: [1, 2, 3] }
    const vc = build(mkResult(), { view: v })!.grid3D.viewControl
    expect(vc).toEqual(viewControlFromView(v))
    expect(vc).toMatchObject(v)
  })

  it('applyView 写任意视角、applyDefaultView 写默认（都是 merge，不碰 series）', () => {
    const calls: any[][] = []
    const chart = { setOption: (...args: any[]) => calls.push(args) }
    const v: Site3DView = { alpha: 5, beta: 6, distance: 200, orthographicSize: 90, center: [0, 1, 0] }
    applyView(chart, v)
    applyDefaultView(chart)
    expect(calls[0][0].grid3D.viewControl).toEqual(viewControlFromView(v))
    expect(calls[1][0].grid3D.viewControl).toEqual(viewControlFromView(defaultSite3DView()))
    // 只传一个参数：setOption(opt, true) 是 notMerge，会把柱数据一起换掉
    expect(calls.map((a) => a.length)).toEqual([1, 1])
    expect(calls.every((a) => a[0].series === undefined)).toBe(true)
  })

  it('applyDefaultView 用同一份值做合并写（不是 notMerge 全量重建）', () => {
    const calls: any[] = []
    applyDefaultView({ setOption: (o: any) => calls.push(o) })
    expect(calls).toHaveLength(1)
    expect(calls[0].grid3D.viewControl).toEqual(defaultViewControl())
    expect(calls[0].series).toBeUndefined()
  })

  it('实例为 null 时复位静默不抛（图还没建时点按钮）', () => {
    expect(() => applyDefaultView(null)).not.toThrow()
    expect(() => applyDefaultView(undefined)).not.toThrow()
  })
})

/**
 * 本批**刻意不画**的东西也要有判据：代码没写 ≠ 有人不会写。spec §4 定了 LSL/USL 不画，
 * §5 末条定了 axisPointer 不适用（bar3D 的 tooltip 走默认 `item` 触发，gl 不画那个黑胶囊，
 * 写了就是无人消费的死配置），色键只由 piecewise visualMap 承担（gl 系列不进 ECharts legend，
 * 掺 `inRange` 还会覆盖 pieces）。
 */
describe('刻意不画的三件：写了就该红', () => {
  it('不写 axisPointer，不建 legend', () => {
    const o = build(mkResult())!
    expect(o.tooltip).not.toHaveProperty('axisPointer')
    expect(o).not.toHaveProperty('legend')
  })

  it('不画规格限：任何系列都不带 markLine', () => {
    for (const s of build(mkResult())!.series) {
      expect(s).not.toHaveProperty('markLine')
    }
  })
})
