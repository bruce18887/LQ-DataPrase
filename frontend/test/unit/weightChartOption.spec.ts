/**
 * T2（docs/reference/testing-gates.md §2）：`environment: node`、零 DOM、零网络。
 * 2026-10-20 起「每个测试项一张图」：调用方按组分别调用，本模块只构建**一个** group 的 option。
 *
 * 承重口径（lessons「断言必须承重而不是全绿」）：
 * ① 三组长度 16 / 8 / 64 分别构建，x 上界必须 15 / 7 / 63；
 *    把 `groupCodeMax` 写回 `doc.code_max` 的实现在这一条上红。
 * ② 不等宽组（3 条）：只用前三种线型，`dashDot` 一次都不出现；4 条组才吃到第四档。
 * ③ 组色按 `group.index` 取：第 1 组必须是 COLORS[1]（按调用顺序取第 0 项会红）。
 * ④ 图例从 `{show:false}` 改为每图自带（只列本组 4/5 条），但仍不按系列名查表。
 * ⑤ 素材前置：夹具真的不等宽、真的含 null、色板真的 8 色且不含均值灰 —— 否则对应判据恒真。
 * ⑥ 逐槽开关（2026-10-22）：线型按**原槽位**取、x 上界按**全组**算、缺省全显与 `[]` 全关分开钉 ——
 *    这三条各挡一种写错的实现（顶位换型 / 轴随隐藏收缩 / 把缺省读成全关）。
 */
import { describe, expect, it } from 'vitest'
import {
  buildWeightOption, groupColor, groupCodeMax, slotCount, DASH_BY_WITHIN_GROUP,
  MEAN_DASH, MEAN_WIDTH, LINE_WIDTH, MARKER_SIZE,
  PAGE_MAX_DECIMALS, formatWeightCell, formatWeightLabel, legendLabel,
} from '../../src/pages/weight/weightChartOption'
import type { BuildOptions, WeightDocDto, WeightGroupDto, WeightSeriesDto } from '../../src/pages/weight/weightChartOption'

// 与 frontend/src/utils/echarts-theme.ts 里 light 分支的 `seriesColors` 逐字同值
// （按符号名定位，别记行号 —— 该文件本轮已被删过二十几行，行号会漂）。
// 色板真源在那边、本模块只收调用方传入的数组（spec §6 第 1 条：Python 侧不存色板）。
const COLORS = ['#2563eb', '#047857', '#d97706', '#b91c1c', '#0284c7', '#86198f', '#475569', '#0d9488']
// 同文件 night 分支的 `seriesColors`；夜主题文本/轴线是真 rgba，不是 var(--x)（lessons R7②）。
const NIGHT = ['#fdd835', '#14b8a6', '#4facfe', '#fb7185', '#38ef7d', '#b45309', '#00f2fe', '#ff9f43']
const NIGHT_BASE = {
  textColor: 'rgba(255, 255, 255, 0.76)', axisLineColor: 'rgba(255, 255, 255, 0.10)',
  meanColor: '#e5e7eb',
}
const base = { textColor: '#6b7280', axisLineColor: '#e5e7eb', meanColor: '#4b5563' }

function mkSeries(name: string, values: (number | null)[]): WeightSeriesDto {
  return { name, source_index: 1, declared_length: values.length, decimals: 5, values }
}
function ramp(n: number): number[] { return Array.from({ length: n }, (_, i) => i * 0.5) }
/** lens 每项是一条成员的长度 ⇒ 能同时造出「组宽不等」与「组内长度不等」。 */
function mkGroup(index: number, lens: number[], tag = `WT000${index + 1}`): WeightGroupDto {
  return {
    index, name: tag, first_row: 1,
    series: lens.map((len, k) => mkSeries(`${tag}_${k + 1}`, ramp(len))),
    mean: mkSeries(`${tag}_Avg`, ramp(Math.max(0, ...lens))),
  }
}
const G0 = mkGroup(0, [16, 16, 16, 16])
const G1 = mkGroup(1, [8, 8, 8, 8])
const G3 = mkGroup(3, [64, 64, 64, 64])

function opt(g: WeightGroupDto, showMean = false, over: Partial<BuildOptions> = {}): any {
  return buildWeightOption(g, {
    showMean, colors: COLORS, ...base, titleText: g.name, ...over,
  })
}
/** 深走 option，收集所有字符串值（函数跳过）——查「CSS 变量混进 setOption」。 */
function stringsOf(node: unknown, out: string[] = []): string[] {
  if (typeof node === 'string') out.push(node)
  else if (Array.isArray(node)) node.forEach((v) => stringsOf(v, out))
  else if (node && typeof node === 'object') Object.values(node).forEach((v) => stringsOf(v, out))
  return out
}

describe('一个测试项一张图', () => {
  it('只画传入组的系列，四条原始曲线带圆点', () => {
    const o = opt(G1)
    expect(o.series).toHaveLength(4)
    expect(o.series.map((s: any) => s.name)).toEqual(['WT0002_1', 'WT0002_2', 'WT0002_3', 'WT0002_4'])
    expect(o.series.every((s: any) => s.symbol === 'circle')).toBe(true)
    expect(o.series.every((s: any) => s.symbolSize === MARKER_SIZE)).toBe(true)
    expect(o.series.every((s: any) => s.showSymbol === true)).toBe(true)
  })

  it('均值线为细虚线、无可见圆点、带数值标签；原始线不带标签', () => {
    const o = opt(G0, true)
    const mean = o.series.at(-1)
    expect(mean.symbolSize).toBe(0)                    // 不盖原始线的点
    expect(mean.lineStyle.type).toBe(MEAN_DASH)
    expect(mean.lineStyle.width).toBe(MEAN_WIDTH)
    expect(mean.label.show).toBe(true)
    expect(mean.label.position).toBe('top')
    expect(mean.labelLayout.hideOverlap).toBe(true)
    // 2026-10-20 用户点定：页面与导出均值都最多 5 位小数（MEAN_DECIMALS=5，见后端 T1）。
    expect(mean.label.formatter({ value: [3, 1.234567] })).toBe('1.23457')
    expect(mean.label.formatter({ value: [3, null] })).toBe('')
    expect(mean.label.formatter({ value: [3, undefined] })).toBe('')
    expect(o.series.slice(0, -1).every((s: any) => s.label === undefined)).toBe(true)
  })

  it('X 轴取本组最长系列 - 1：16/8/64 三组分别是 15/7/63（共用全局值会红）', () => {
    const maxes = [G0, G1, G3].map((g) => opt(g).xAxis[0].max)
    expect(maxes).toEqual([15, 7, 63])
    expect(new Set(maxes).size).toBe(3)        // 对照组：三组本来就不该同值
    expect(opt(G0).xAxis[0].min).toBe(0)
  })

  it('groupCodeMax 是纯函数，空组钳到 0', () => {
    expect(groupCodeMax(G0)).toBe(15)
    expect(groupCodeMax(mkGroup(0, []))).toBe(0)
    expect(opt(mkGroup(0, [])).xAxis[0].max).toBe(0)
  })

  it('每条系列只取自身长度，短数组不补空', () => {
    expect(opt(G1).series[0].data).toHaveLength(8)
    expect(opt(G3).series[0].data).toHaveLength(64)
    const mixed = mkGroup(0, [3, 6])
    const o = opt(mixed)
    expect(o.series.map((s: any) => s.data.length)).toEqual([3, 6])
  })

  it('组内四条按线型区分、共用该组基色', () => {
    const o = opt(G1)
    expect(o.series.map((s: any) => s.lineStyle.type)).toEqual(DASH_BY_WITHIN_GROUP.slice(0, 4))
    expect(new Set(o.series.map((s: any) => s.lineStyle.color))).toEqual(new Set([COLORS[1]]))
  })

  it('开均值加一条、深灰加粗实线；关均值回到 4 条', () => {
    expect(opt(G0).series).toHaveLength(4)
    const on = opt(G0, true)
    expect(on.series).toHaveLength(5)
    const mean = on.series.find((s: any) => s.name === 'WT0001_Avg')
    expect(mean.lineStyle.color).toBe(base.meanColor)
    expect(mean.lineStyle.type).toBe(MEAN_DASH)
    expect(mean.lineStyle.width).toBe(MEAN_WIDTH)
  })

  it('均值长度取组内最大（成员长度不等时也不截断）', () => {
    const g = mkGroup(0, [4, 6])
    expect(opt(g, true).series.at(-1).data).toHaveLength(6)
  })

  it('14 组循环 8 色：第 9 组与第 1 组同色（能力上限，钉住别当 bug 改）', () => {
    expect(groupColor(COLORS, 0)).toBe(COLORS[0])
    expect(groupColor(COLORS, 8)).toBe(COLORS[0])
    expect(groupColor(COLORS, 13)).toBe(COLORS[5])
  })
})

describe('不等宽组的线型在组内重置', () => {
  it('3 条组只用前三种线型，dashDot 一次都不出现；4 条组才到第四档', () => {
    const three = opt(mkGroup(0, [4, 4, 4]))
    const four = opt(mkGroup(1, [4, 4, 4, 4]))
    expect(three.series.map((s: any) => s.lineStyle.type))
      .toEqual([DASH_BY_WITHIN_GROUP[0], DASH_BY_WITHIN_GROUP[1], DASH_BY_WITHIN_GROUP[2]])
    expect(three.series.some((s: any) => JSON.stringify(s.lineStyle.type) === JSON.stringify(DASH_BY_WITHIN_GROUP[3]))).toBe(false)
    expect(four.series.map((s: any) => s.lineStyle.type)).toContain(DASH_BY_WITHIN_GROUP[3])
  })
})

describe('图例：每图自带，只列本组系列', () => {
  it('图例是显式打开的，放底部，颜色走主题文本色（不是旧版 show:false）', () => {
    const o = opt(G0, true)
    expect(o.legend.show).toBe(true)
    expect(o.legend.bottom).toBe(0)
    expect(o.legend.textStyle.color).toBe(base.textColor)
  })

  it('总开关关掉图例：show=false 且把图例那行的底部留白还给画布', () => {
    const on = opt(G0, true, { showLegend: true })
    const off = opt(G0, true, { showLegend: false })
    expect(on.legend.show).toBe(true)
    expect(off.legend.show).toBe(false)
    expect(on.grid.bottom).toBe(40)
    expect(off.grid.bottom).toBe(16)
    expect(off.grid.bottom).toBeLessThan(on.grid.bottom)
    // 只关图例，不动曲线：4 条成员 + 1 条均值都还在（关图例 ≠ 关系列）
    expect(off.series).toHaveLength(5)
  })

  it('showLegend 是可选字段：旧调用方不传就维持显示（缺省不能翻成隐藏）', () => {
    const o = opt(G0, true)
    expect(o.legend.show).toBe(true)
    expect(o.grid.bottom).toBe(40)
  })

  it('图例只显示组内序号 / 均值 / 原始，长组名不把图例挤成两页', () => {
    const o = opt(G0, true)
    expect(o.legend.formatter('WT0001_1')).toBe('1')
    expect(o.legend.formatter('WT0001_4')).toBe('4')
    expect(o.legend.formatter('WT0001_Avg')).toBe('均值')
    expect(o.legend.formatter('WT0001')).toBe('原始')
    expect(legendLabel('A_very_long_unrelated_series_name', 'WT0001')).toBe('A_very_long_unr…')
  })

  it('标题文本是测试项名；可见标题已移到图表卡头，画布内不再重复渲染', () => {
    expect(opt(G3).title.text).toBe('WT0004')
    expect(opt(G3).title.show).toBe(false)
  })
})

describe('组内曲线逐槽开关', () => {
  // 三条语义裁定都要承重：① 线型按**原槽位**固定（隐藏槽 0 后 2/3/4 不许顶成实线）
  // ② x 上界按全组算（隐藏最长那条不许收缩，14 张图在勾选过程中保持可横向对齐）
  // ③ 缺省 = 全显、传 [] = 全关 —— 两种写法在实现里极易混用，各钉一条。
  it('隐藏槽 0：剩 _2/_3/_4，线型仍是 DASH[1..3]（改用过滤后下标就会红）', () => {
    const o = opt(G0, false, { visibleSlots: [1, 2, 3] })
    expect(o.series.map((s: any) => s.name)).toEqual(['WT0001_2', 'WT0001_3', 'WT0001_4'])
    expect(o.series.map((s: any) => s.lineStyle.type)).toEqual([
      DASH_BY_WITHIN_GROUP[1], DASH_BY_WITHIN_GROUP[2], DASH_BY_WITHIN_GROUP[3],
    ])
    // 组色不随槽位变：剩下的还是本组基色
    expect(o.series.map((s: any) => s.lineStyle.color)).toEqual([COLORS[0], COLORS[0], COLORS[0]])
  })

  it('不传 visibleSlots = 全显；传 [] = 全关（只剩轴，均值仍按 showMean 决定）', () => {
    expect(opt(G0).series).toHaveLength(4)
    expect(opt(G0, false, { visibleSlots: [] })).toEqual(expect.objectContaining({ series: [] }))
    const allOffWithMean = opt(G0, true, { visibleSlots: [] })
    expect(allOffWithMean.series.map((s: any) => s.name)).toEqual(['WT0001_Avg'])
  })

  it('隐藏最长那条后 x 上界不变（轴不收缩）', () => {
    const g = mkGroup(0, [64, 8, 8, 8])
    expect(opt(g).xAxis[0].max).toBe(63)
    expect(opt(g, false, { visibleSlots: [1, 2, 3] }).xAxis[0].max).toBe(63)
  })

  it('槽数多于线型数（5 条组）时隐藏任一槽，其余线型与颜色不串位', () => {
    const five = mkGroup(0, [4, 4, 4, 4, 4])
    expect(opt(five).series.map((s: any) => JSON.stringify(s.lineStyle.type))).toEqual(
      [0, 1, 2, 3, 0].map((i) => JSON.stringify(DASH_BY_WITHIN_GROUP[i])))
    const hidden = opt(five, false, { visibleSlots: [0, 1, 2, 3] })
    expect(hidden.series.map((s: any) => s.name)).toEqual(['WT0001_1', 'WT0001_2', 'WT0001_3', 'WT0001_4'])
    expect(hidden.series.map((s: any) => JSON.stringify(s.lineStyle.type))).toEqual(
      [0, 1, 2, 3].map((i) => JSON.stringify(DASH_BY_WITHIN_GROUP[i])))
  })

  it('槽号越界（该组没那么条）不影响其余槽', () => {
    const three = mkGroup(0, [4, 4, 4])
    const o = opt(three, false, { visibleSlots: [0, 1, 2, 3, 4] })
    expect(o.series).toHaveLength(3)
  })

  it('slotCount 取各组成员数的最大值（chip 排按它生成，写死 4 就会漏掉第 5 条）', () => {
    const doc: WeightDocDto = {
      filename: 'x.c', code_max: 63, group_count: 3, series_count: 11,
      groups: [mkGroup(0, [4, 4]), mkGroup(1, [4, 4, 4, 4, 4]), mkGroup(2, [4, 4, 4])],
    }
    expect(slotCount(doc)).toBe(5)
    expect(slotCount({ ...doc, groups: [] })).toBe(0)
  })
})

describe('null 留缺口', () => {
  it('null 点位保留为 [code, null] 且 connectNulls=false（填 0 或删点都会红）', () => {
    const g: WeightGroupDto = {
      index: 0, name: 'WT0001', first_row: 1,
      series: [mkSeries('WT0001_1', [1.5, null, 3.5]), mkSeries('WT0001_2', [null, null, 2])],
      mean: mkSeries('WT0001_Avg', [1.5, null, 2.75]),
    }
    expect(g.series[0].values.filter((v) => v === null)).toHaveLength(1)  // 对照组：素材真有洞
    const o = opt(g)
    expect(o.series[0].data).toEqual([[0, 1.5], [1, null], [2, 3.5]])
    expect(o.series[1].data).toEqual([[0, null], [1, null], [2, 2]])
    expect(o.series.every((s: any) => s.connectNulls === false)).toBe(true)
    expect(o.series.every((s: any) => s.data.length === 3)).toBe(true)
  })

  it('每条系列的 code 就是点上标：0..len-1 连续，短组末点不是全局 code_max', () => {
    const o = opt(G1, true)
    for (const s of o.series) {
      expect(s.data.map((p: any) => p[0])).toEqual(Array.from({ length: s.data.length }, (_, i) => i))
    }
    const short = o.series[0]
    expect(short.data).toHaveLength(8)
    expect(short.data.at(-1)[0]).toBe(7)
    expect(o.xAxis[0].max).toBe(7)
  })
})

describe('均值线与成员的可见差别', () => {
  it('均值恒比成员粗，且颜色恒等于调用方的 meanColor（不是组色）', () => {
    const o = opt(G0, true)
    const mean = o.series.at(-1)
    const members = o.series.slice(0, -1)
    expect(mean.lineStyle.color).toBe(base.meanColor)
    expect(COLORS).not.toContain(mean.lineStyle.color)
    for (const m of members) expect(mean.lineStyle.width).toBeGreaterThan(m.lineStyle.width)
  })

  it('MEAN_DASH/宽度常量：4 种成员线型互不相同，均值虚线且比成员略粗', () => {
    expect(DASH_BY_WITHIN_GROUP).toHaveLength(4)
    expect(new Set(DASH_BY_WITHIN_GROUP.map((d) => JSON.stringify(d))).size).toBe(4)
    expect(MEAN_DASH).toBe('dashed')
    expect(MEAN_WIDTH).toBeGreaterThan(LINE_WIDTH)
    expect(LINE_WIDTH).toBe(1.25)
    expect(MEAN_WIDTH).toBe(1.5)
  })
})

describe('轴', () => {
  it('两轴都是 value 轴，x 钉 0 与本组上界、y 不钉 min', () => {
    const o = opt(G0)
    expect(o.xAxis[0].type).toBe('value')
    expect(o.yAxis[0].type).toBe('value')
    expect(o.xAxis[0].min).toBe(0)
    expect(o.xAxis[0].max).toBe(15)
    expect(o.yAxis[0].min).toBeUndefined()
  })
})

describe('系列名不是唯一键：按组内位置成图', () => {
  // Task 2 评审实测的已接受行为：A×2 + 字面 A_1 ⇒ ['A_1','A_2','A_1']；字面 A_Avg 还会与均值线撞名。
  const dup: WeightGroupDto = {
    index: 0, name: 'A', first_row: 1,
    series: [mkSeries('A_1', ramp(4)), mkSeries('A_2', ramp(4)), mkSeries('A_1', ramp(4))],
    mean: mkSeries('A_1', ramp(4)),
  }

  it('撞名不合并、不报错：3 成员 + 1 均值 = 4 条，靠线型/宽度各归各位', () => {
    const o = opt(dup, true)
    expect(o.series).toHaveLength(4)
    expect(o.series.map((s: any) => s.name)).toEqual(['A_1', 'A_2', 'A_1', 'A_1'])
    expect(o.series.map((s: any) => s.lineStyle.type)).toEqual([
      DASH_BY_WITHIN_GROUP[0], DASH_BY_WITHIN_GROUP[1], DASH_BY_WITHIN_GROUP[2], MEAN_DASH,
    ])
    const same = o.series.filter((s: any) => s.name === 'A_1')
    expect(same).toHaveLength(3)
    expect(new Set(same.map((s: any) => s.lineStyle.width)).size).toBe(2)  // 两条成员 + 一条均值
    expect(same.map((s: any) => s.lineStyle.color).slice(0, 2)).toEqual([COLORS[0], COLORS[0]])
    expect(same[2].lineStyle.color).toBe(base.meanColor)
  })
})

describe('双主题：颜色只走调用方给的 JS 值', () => {
  it('light 与 night 两套语义色都能落到 series/axis/title/legend 上', () => {
    const light = opt(G0)
    const night = opt(G0, false, { colors: NIGHT, ...NIGHT_BASE })
    expect(light.series[0].lineStyle.color).toBe(COLORS[0])
    expect(night.series[0].lineStyle.color).toBe(NIGHT[0])
    expect(night.xAxis[0].axisLine.lineStyle.color).toBe(NIGHT_BASE.axisLineColor)
    expect(night.xAxis[0].axisLabel.color).toBe(NIGHT_BASE.textColor)
    expect(night.yAxis[0].axisLabel.color).toBe(NIGHT_BASE.textColor)
    expect(night.title.textStyle.color).toBe(NIGHT_BASE.textColor)
    expect(night.legend.textStyle.color).toBe(NIGHT_BASE.textColor)
    const used = new Set(night.series.map((s: any) => s.lineStyle.color))
    for (const c of used) expect(NIGHT).toContain(c)
  })

  it('整个 option 里没有 var(...) / color-mix(...)：ECharts 不解析 CSS 变量（lessons R7②）', () => {
    const o = buildWeightOption(G0, { showMean: true, colors: NIGHT, ...NIGHT_BASE, titleText: G0.name })
    const hit = stringsOf(o).filter((s) => s.includes('var(') || s.includes('color-mix('))
    expect(hit).toEqual([])
  })
})

describe('显示精度：页面最多 5 位小数', () => {
  it('图上标签去尾零、null 留空；表格按源位数与 5 位取小', () => {
    expect(PAGE_MAX_DECIMALS).toBe(5)                    // 对照组：下限不是随手写的 6
    expect(formatWeightLabel(1.234567)).toBe('1.23457')
    expect(formatWeightLabel(1.2)).toBe('1.2')
    expect(formatWeightLabel(28788.589088)).toBe('28788.58909')
    expect(formatWeightLabel(null)).toBe('')
    expect(formatWeightLabel(undefined)).toBe('')
    expect(formatWeightCell(1.234567, 8)).toBe('1.23457')
    expect(formatWeightCell(1.234567, 5)).toBe('1.23457')
    expect(formatWeightCell(2, 0)).toBe('2')
    expect(formatWeightCell(null, 6)).toBe('')
    expect(formatWeightCell(-0.000004, 6)).toBe('0.00000')  // 负零归一，别显示 -0.00000
  })
})

describe('纯函数', () => {
  it('不改动入参 group，重复调用同值，且每次新建 series 数组', () => {
    const snapshot = JSON.stringify(G0)
    const first = JSON.stringify(opt(G0, true))
    expect(JSON.stringify(G0)).toBe(snapshot)
    expect(JSON.stringify(opt(G0, true))).toBe(first)
    const a = opt(G0, true)
    const b = opt(G0, true)
    expect(b.series).not.toBe(a.series)
  })
})

describe('tooltip 文案', () => {
  it('formatter 打的是系列名 + code + 值，不是组名', () => {
    const o = opt(G1)
    const line = o.tooltip.formatter({ seriesName: 'WT0002_3', value: [7, 3.5] })
    expect(line).toContain('WT0002_3')
    expect(line).toContain('7')
    expect(line).toContain('3.5')
    expect(line).not.toContain('WT0002<')   // 只到组名就丢掉了「是哪一条」
  })
})

describe('色板前提（不成立则 %8 判据变恒真）', () => {
  it('恰好 8 色、互不相同，且 meanColor 不在色板里', () => {
    expect(COLORS).toHaveLength(8)
    expect(NIGHT).toHaveLength(8)
    expect(new Set(COLORS).size).toBe(8)
    expect(COLORS).not.toContain(base.meanColor)
    expect(NIGHT).not.toContain(NIGHT_BASE.meanColor)
  })
})
