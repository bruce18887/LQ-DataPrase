/**
 * T2（`docs/reference/testing-gates.md` §2）：多文件对比图的 ECharts option 层判据。
 *
 * 这一档此前**没有地方写**：option 逻辑长在 `MultiFileChart.vue` 的 `buildOption()` 里，
 * 要断言就得开浏览器（分诊文档把「ECharts option 层断言」列为无处可落的 32 例之一）。
 * 纯模块 `pages/analysis/multiFileChartOption.ts` 搬出来后，这里按零 DOM 压住。
 *
 * 承重口径（lessons「断言必须承重而不是全绿」）：
 * ① 正态公式与后端 `normal_pdf_curve` 逐点对齐 —— 黄金值由
 *   `python -c "…normal_pdf_curve(0.0,1.0,-3.0,3.0,n_points=7)"` 现取，不是手算；
 * ② 钳制有对照组（0.002% 被抬到保底、12.5% 不动），只断「三元组形状」会放过整条钳制失效；
 * ③ 轴扩展断**恒等式**（两端外扩量相等且 >0），不断常数；
 * ④ 双主题两侧色值都写死对照，单侧断言会把「night/light 用同一份」当成绿。
 */
import { describe, expect, it } from 'vitest'

import {
  axisColors,
  buildLimitMarkLines,
  buildMultiFileOption,
  deriveBinGap,
  lotDisplayName,
  multiLotTooltipHtml,
  normalPDFAt,
  sampleNormalCurve,
} from '../../src/pages/analysis/multiFileChartOption'
import type { MultiFileLot, MultiLotResponse, MultiLotTheme } from '../../src/pages/analysis/multiFileChartOption'
import {
  MIN_BAR_HEIGHT_PCT,
  clampBarValue,
  getBarGroupPad,
  getMaxBarWidthPercent,
  mapLotColorToTheme,
} from '../../src/utils/chart-bar'

const LIGHT: MultiLotTheme = {
  textColor: '#111',
  axisLineColor: '#222',
  tooltipBg: '#333',
  tooltipBorder: '#444',
  tooltipText: '#555',
  isDark: false,
}
const NIGHT: MultiLotTheme = { ...LIGHT, isDark: true }

function lot(over: Partial<MultiFileLot> = {}): MultiFileLot {
  return {
    file_id: 11,
    name: 'a.csv',
    color: '#0077BB',
    mean: 2.5,
    std: 0.75,
    bar_data: [[1, 12.5], [2, 0.002], [3, 0]],
    upper_limit: 3.5,
    lower_limit: 1.5,
    ...over,
  }
}

function response(lots: MultiFileLot[], over: Partial<MultiLotResponse> = {}): MultiLotResponse {
  return { lot_data: lots, bin_centers: [1, 2, 3], global_mean: 2.4115, ...over }
}

function optionFor(lots: MultiFileLot[], cfg: string[], over: Partial<MultiLotResponse> = {}, theme: MultiLotTheme = LIGHT) {
  return buildMultiFileOption({
    lotData: response(lots, over),
    chartConfig: cfg,
    barWidthPercent: 40,
    fileNames: {},
    selectedParam: 'SW_Bin',
    theme,
  })
}

const byName = (option: any, name: string) => option.series.find((s: any) => s.name === name)

describe('空数据：不产 option，也不抛', () => {
  const base = { chartConfig: ['normal'], barWidthPercent: 40, fileNames: {}, selectedParam: 'P', theme: LIGHT }
  it('lot_data 缺失 / 空数组 / 整个响应为 null 都返回空对象', () => {
    for (const lotData of [{ bin_centers: [1, 2] }, { lot_data: [] }, null, undefined]) {
      expect(buildMultiFileOption({ ...base, lotData: lotData as any })).toEqual({})
    }
  })
  it('有 lot 但缺 bin_centers 时仍能出柱（fallback 到 chart_min/max）', () => {
    const o = buildMultiFileOption({ ...base, lotData: { lot_data: [lot()] } as any })
    expect(o.series).toHaveLength(1)
    expect(o.xAxis.min).toBeUndefined()
    expect(o.xAxis.max).toBeUndefined()
  })
})

describe('正态公式：与后端单源逐点对齐', () => {
  it('后端 normal_pdf_curve(0,1,-3,3,7) 的 7 个点，JS 侧逐点相等（±1e-6）', () => {
    // 黄金值来自 `python -c "…normal_pdf_curve(0.0,1.0,-3.0,3.0,n_points=7)"`（6 位小数是后端 round 的形状）
    const golden: [number, number][] = [
      [-3, 0.004432], [-2, 0.053991], [-1, 0.241971], [0, 0.398942],
      [1, 0.241971], [2, 0.053991], [3, 0.004432],
    ]
    for (const [x, y] of golden) expect(normalPDFAt(x, 0, 1), `x=${x}`).toBeCloseTo(y, 6)
    // 对照组：非平凡 mean/std 也对齐（normal_pdf_curve(2.5,0.75,…) 在 x=2 与 x=1 处的值）
    expect(normalPDFAt(2.0, 2.5, 0.75)).toBeCloseTo(0.425931, 6)
    expect(normalPDFAt(1.0, 2.5, 0.75)).toBeCloseTo(0.071988, 6)
  })
  it('峰值等于 1/(σ√2π)；std=0 返回 0 而不是 Infinity', () => {
    expect(normalPDFAt(2.5, 2.5, 0.75)).toBeCloseTo(1 / (0.75 * Math.sqrt(2 * Math.PI)), 12)
    expect(normalPDFAt(1, 1, 0)).toBe(0)
  })
  it('采样：100 段 = 101 点，末点正好落在 xMax（累加写法会掉成 100 点）', () => {
    const pts = sampleNormalCurve(2.5, 0.75, 1, 3)
    expect(pts).toHaveLength(101)
    expect(pts[0][0]).toBe(1)
    expect(pts[pts.length - 1][0]).toBe(3)
    // 均匀性：相邻 x 之差处处等于 step（累加写法的误差不恒等）
    const step = 2 / 100
    for (let i = 1; i < pts.length; i++) expect(pts[i][0] - pts[i - 1][0]).toBeCloseTo(step, 12)
  })
  it('退化输入返回空数组（旧写法在单个 bin_center 上 step=0，会无限循环）', () => {
    expect(sampleNormalCurve(1, 0, 0, 2)).toEqual([])
    expect(sampleNormalCurve(1, -1, 0, 2)).toEqual([])
    expect(sampleNormalCurve(1, 1, 2, 2)).toEqual([])
    expect(sampleNormalCurve(1, 1, 3, 2)).toEqual([])
  })
})

describe('柱状系列：钳制、柱宽与图例顺序', () => {
  it('每个 lot 一根柱，data 是 [x, 钳制值, 真实值] 三元组', () => {
    const o = optionFor([lot()], [])
    const bar = o.series[0]
    expect(bar.type).toBe('bar')
    expect(bar.data[0]).toEqual([1, 12.5, 12.5])
    expect(bar.data[1][1]).toBe(MIN_BAR_HEIGHT_PCT) // 0.002% 被抬到保底
    expect(bar.data[1][2]).toBe(0.002) // 真实值留给 tooltip/标签
    expect(bar.data[2]).toEqual([3, 0, 0]) // 0 不被抬（否则假零柱）
    expect(clampBarValue(0.002)).toBe(MIN_BAR_HEIGHT_PCT)
    expect(clampBarValue(12.5)).toBe(12.5)
  })
  it('柱宽取 min(用户值, N 系列上限)，且 N 越大上限越小', () => {
    const three = [lot(), lot({ file_id: 12 }), lot({ file_id: 13 })]
    const o = optionFor(three, [])
    expect(o.series[0].barWidth).toBe(`${getMaxBarWidthPercent(3)}%`)
    expect(getMaxBarWidthPercent(3)).toBeLessThan(getMaxBarWidthPercent(2))
    expect(o.series.length).toBe(3)
  })
  it('标签 formatter：>0 显示自适应百分比，0 显示空串', () => {
    const fmt = optionFor([lot()], []).series[0].label.formatter
    expect(fmt({ data: [1, 12.5, 12.5] })).toMatch(/%$/)
    expect(fmt({ data: [3, 0, 0] })).toBe('')
  })
  it('图例顺序：柱 → 规格限 → 正态 → KDE，且每档都按 lot 分条', () => {
    const kde = [[1, 0.1], [2, 0.2]]
    const o = optionFor([lot({ kde_curve: kde }), lot({ file_id: 12, name: 'b.csv', kde_curve: kde })], ['limit', 'normal', 'kde'])
    expect(o.legend.data).toEqual([
      'a.csv', 'b.csv',
      'a.csv 规格限', 'b.csv 规格限',
      'a.csv 正态分布', 'b.csv 正态分布',
      'a.csv KDE', 'b.csv KDE',
    ])
    expect(o.series.map((s: any) => s.type)).toEqual(['bar', 'bar', 'scatter', 'scatter', 'line', 'line', 'line', 'line'])
  })
})

describe('规格限 markLine：display_* 优先、单边只画一条', () => {
  it('双侧限值 → 两条竖线，标签是 `<名> USL` / `<名> LSL`', () => {
    const { mk, upper, lower } = buildLimitMarkLines(lot(), 'a.csv', '#0077BB')
    expect(mk).toHaveLength(2)
    expect(upper).toBe(3.5)
    expect(lower).toBe(1.5)
    expect(mk.map((m: any) => m.label.formatter)).toEqual(['a.csv USL', 'a.csv LSL'])
    expect(mk.map((m: any) => m.xAxis)).toEqual([3.5, 1.5])
  })
  it('display_upper 覆盖 upper_limit；单边限值不补另一侧', () => {
    const both = buildLimitMarkLines(lot({ display_upper: 4.25 }), 'a.csv', '#0077BB')
    expect(both.upper).toBe(4.25)
    expect(both.mk[0].xAxis).toBe(4.25)
    const one = buildLimitMarkLines(lot({ upper_limit: null, lower_limit: 0.5 }), 'a.csv', '#0077BB')
    expect(one.mk).toHaveLength(1)
    expect(one.mk[0].label.formatter).toBe('a.csv LSL')
  })
  it('完全没限值 → option 里不出现 规格限 系列；锚点 x 缺限值时回退 bin_centers[0]', () => {
    const o = optionFor([lot({ upper_limit: null, lower_limit: null })], ['limit'])
    expect(o.series.some((s: any) => s.name.includes('规格限'))).toBe(false)
    const anchored = buildLimitMarkLines(lot({ upper_limit: null, lower_limit: null }), 'a.csv', '#0077BB')
    expect(anchored.mk).toEqual([])
    // 有 bin_centers、无限值时 scatter 锚点用第一个 bin（markLine 需要挂在有数据的点上）
    const partial = optionFor([lot({ upper_limit: null, lower_limit: 1.5 })], ['limit'])
    expect(byName(partial, 'a.csv 规格限').data).toEqual([[1.5, 0]])
  })
})

describe('曲线档位：概率密度轴与 grid 只在该档打开时出现', () => {
  it('normal 开：每个 std>0 的 lot 一条线、走 yAxisIndex 1、第二轴与加宽右栏同时出现', () => {
    const o = optionFor([lot(), lot({ file_id: 12, name: 'b.csv', std: 0 })], ['normal'])
    const curve = byName(o, 'a.csv 正态分布')
    expect(curve.yAxisIndex).toBe(1)
    expect(curve.data).toHaveLength(101)
    expect(o.yAxis).toHaveLength(2)
    expect(o.yAxis[1].name).toBe('概率密度')
    expect(o.grid.right).toBe(80)
    // std=0 的 lot 不产生曲线，也不进图例
    expect(byName(o, 'b.csv 正态分布')).toBeUndefined()
    expect(o.legend.data).toEqual(['a.csv', 'b.csv', 'a.csv 正态分布'])
  })
  it('normal 与 kde 都关：只有一根百分比轴，右栏回到 55', () => {
    const o = optionFor([lot()], [])
    expect(o.yAxis).toHaveLength(1)
    expect(o.grid.right).toBe(55)
  })
  it('KDE 原样下发后端点集（不再本地采样），线宽 2.5 区别于正态的 3', () => {
    const kde = [[1, 0.01], [2, 0.02], [3, 0.03]]
    const o = optionFor([lot({ kde_curve: kde })], ['kde'])
    const s = byName(o, 'a.csv KDE')
    expect(s.data).toEqual(kde)
    expect(s.lineStyle.width).toBe(2.5)
    expect(byName(o, 'a.csv 正态分布')).toBeUndefined()
  })
})

describe('图例名与主题', () => {
  it('名优先级的三档：账号自定义文件名 > 后端 name > File <id>', () => {
    const fileNames = { 11: '自定义A' }
    expect(lotDisplayName(lot({ name: 'a.csv' }), fileNames)).toBe('自定义A')
    expect(lotDisplayName(lot({ name: 'a.csv' }), {})).toBe('a.csv')
    expect(lotDisplayName(lot({ name: '' }), {})).toBe('File 11')
  })
  it('双主题：轴辅助色与 lot 色都随主题换，且两侧不是同一份', () => {
    expect(axisColors(false)).toEqual({ left: '#1E88E5', normal: '#F57F17' })
    expect(axisColors(true)).toEqual({ left: '#64B5F6', normal: '#FFA726' })
    const light = optionFor([lot()], ['normal'], {}, LIGHT)
    const night = optionFor([lot()], ['normal'], {}, NIGHT)
    expect(light.yAxis[0].axisLine.lineStyle.color).toBe('#1E88E5')
    expect(night.yAxis[0].axisLine.lineStyle.color).toBe('#64B5F6')
    expect(light.series[0].itemStyle.color).toBe(mapLotColorToTheme('#0077BB', false))
    expect(night.series[0].itemStyle.color).toBe(mapLotColorToTheme('#0077BB', true))
    expect(night.series[0].itemStyle.color).not.toBe(light.series[0].itemStyle.color)
    // tooltip 与轴线色取自传入主题，不是硬编码
    expect(night.tooltip.backgroundColor).toBe(NIGHT.tooltipBg)
    expect(night.xAxis.axisLine.lineStyle.color).toBe(NIGHT.axisLineColor)
  })
})

describe('轴范围：多系列分组偏移的两端扩展', () => {
  it('有 bin_centers 时两端外扩同一个 axisPad（恒等式，不是常数）', () => {
    const three = [lot(), lot({ file_id: 12 }), lot({ file_id: 13 })]
    const o = optionFor(three, [])
    const pad = getBarGroupPad(3, 1, getMaxBarWidthPercent(3))
    expect(o.xAxis.min).toBeCloseTo(1 - pad, 9)
    expect(o.xAxis.max).toBeCloseTo(3 + pad, 9)
    expect(o.xAxis.max - 3).toBeCloseTo(1 - o.xAxis.min, 9) // 左右对称
    expect(pad).toBeGreaterThan(0)
  })
  it('无 bin_centers 时退回后端给的 chart_min/chart_max', () => {
    const o = optionFor([lot()], [], { bin_centers: [], chart_min: -7, chart_max: 9 })
    expect(o.xAxis.min).toBe(-7)
    expect(o.xAxis.max).toBe(9)
  })
  it('binGap 两个来源：bin_centers 相邻差优先，缺失时从 bar_data 前两点推导，再退化给 0', () => {
    expect(deriveBinGap([lot()], [1, 1.5, 2])).toBeCloseTo(0.5, 9)
    expect(deriveBinGap([lot()], [])).toBeCloseTo(1, 9)
    expect(deriveBinGap([lot({ bar_data: [[1, 5]] })], [])).toBe(0)
  })
})

describe('tooltip 与标题', () => {
  it('只有 bar 参与，显示真实值 data[2]；单对象与非 bar 都正确处理', () => {
    const html = multiLotTooltipHtml([
      { seriesType: 'bar', seriesName: 'a.csv', data: [2, MIN_BAR_HEIGHT_PCT, 0.002] },
      { seriesType: 'line', seriesName: 'a.csv 正态分布', data: [2, 0.4] },
    ] as any)
    expect(html).toContain('值: 2.0000')
    expect(html).toContain('a.csv:')
    expect(html).not.toContain('正态分布:')
    expect(multiLotTooltipHtml([] as any)).toBe('')
    // 单对象（非 axis 触发）也要能出文本
    expect(multiLotTooltipHtml({ seriesType: 'bar', seriesName: 'a.csv', data: [1, 12.5, 12.5] } as any)).toContain('12.5')
  })
  it('标题带 μ；global_mean 为 null 时不带', () => {
    expect(optionFor([lot()], []).title.text).toBe('SW_Bin  (μ=2.4115)')
    expect(optionFor([lot()], [], { global_mean: null }).title.text).toBe('SW_Bin  ')
    expect(optionFor([lot()], []).toolbox).toBeTruthy()
  })
})
