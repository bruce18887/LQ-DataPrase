/**
 * T2：ECharts 色 token 与 grid3D 样式件（specs/2026-11-04 §5、lessons R7①②）。
 *
 * 承重四条：
 * ① 两套 token 的键集**逐字相等**——不对称时 TS 会把 colors 推成联合类型、取键即红，
 *    但「两边都有该键、值一个是 var(--x) 一个是色值」这种半吊子只有断言抓得住；
 * ② grid3D 的每一处颜色都来自传入的 colors（不是写死），换主题必须换值——
 *    写死一份就等于「night 抄了 light 的长相」，正是本项目修过多轮的形状；
 * ③ 3D 用到的那把键（GRID3D_TOKEN_KEYS）在两分支都存在，缺一个就是运行时 undefined；
 * ④ 主题→色板的映射在本模块（echartsColorsFor），theme.ts 只许委托——详见下面那个
 *    describe 的来历（M10b 曾 SURVIVED）。
 * 外加一条库坑：`axisLine.show` 必须是 true——echarts-gl 的 Grid3DAxis 只在
 * `if (axisLineModel.get('show'))` 里写 `axisLineCoords`，构造里先置 null，
 * 而 `_updateAxisLabelAlign()`（由 `_onCameraChange` → `_updateAxisLinePosition` 调用）无条件读它
 * ⇒ show:false 时每次相机更新抛一次 TypeError。可重跑复核：
 * `cd frontend && grep -n axisLineCoords node_modules/echarts-gl/dist/echarts-gl.js`
 * （恰好三处命中，就是上面这三行；node_modules 在 frontend 下，从仓库根跑会报 No such file）；
 * 结论也记在 spec §6 坑 2。「想抹掉轴线」只能给全透明色，不能关 show。
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import {
  ECHARTS_COLORS_LIGHT,
  ECHARTS_COLORS_NIGHT,
  GRID3D_TOKEN_KEYS,
  echartsColorsFor,
  grid3DStyle,
} from '../../src/utils/echarts-tokens'

const keys = (o: object) => Object.keys(o).sort()

describe('双主题 token 对称（R7①）', () => {
  it('light/night 键集逐字相等', () => {
    expect(keys(ECHARTS_COLORS_NIGHT)).toEqual(keys(ECHARTS_COLORS_LIGHT))
  })

  it('3D 消费的每一把我都取得到', () => {
    for (const k of GRID3D_TOKEN_KEYS) {
      expect(ECHARTS_COLORS_LIGHT, `light 缺 token: ${k}`).toHaveProperty(k)
      expect(ECHARTS_COLORS_NIGHT, `night 缺 token: ${k}`).toHaveProperty(k)
    }
  })

  it('seriesColors 两边都是 8 格（站点色板按 % 8 循环，长度变了取色会错位）', () => {
    expect(ECHARTS_COLORS_LIGHT.seriesColors).toHaveLength(8)
    expect(ECHARTS_COLORS_NIGHT.seriesColors).toHaveLength(8)
  })
})

describe('grid3DStyle — 逐项取 token，不写死', () => {
  const light = grid3DStyle(ECHARTS_COLORS_LIGHT)
  const night = grid3DStyle(ECHARTS_COLORS_NIGHT)

  it('键集与轴型结构两边一致', () => {
    expect(keys(night)).toEqual(keys(light))
    expect(keys(night.axisLine)).toEqual(keys(light.axisLine))
    expect(keys(night.axisLabel)).toEqual(keys(light.axisLabel))
  })

  it('颜色确实随主题变化，且等于该主题的 token 值', () => {
    expect(light.axisLine.lineStyle.color).toBe(ECHARTS_COLORS_LIGHT.splitLineColor)
    expect(night.axisLine.lineStyle.color).toBe(ECHARTS_COLORS_NIGHT.splitLineColor)
    expect(night.axisLine.lineStyle.color).not.toBe(light.axisLine.lineStyle.color)
    expect(light.splitLine.lineStyle.color).toBe(ECHARTS_COLORS_LIGHT.gridLineColor)
    expect(night.splitLine.lineStyle.color).toBe(ECHARTS_COLORS_NIGHT.gridLineColor)
    expect(light.axisLabel.color).toBe(ECHARTS_COLORS_LIGHT.axisLabelColor)
    expect(night.axisLabel.color).toBe(ECHARTS_COLORS_NIGHT.axisLabelColor)
    expect(light.nameTextStyle.color).toBe(ECHARTS_COLORS_LIGHT.textColor)
  })

  it('网格线对齐 2D 直方图：light #dbdee4（ECharts neutral15），night 保持淡白', () => {
    // ECharts 6 默认 axisSplitLine = tokens.color.neutral15 = #dbdee4；
    // 直方图没有覆写 splitLine，所以它在两个主题下画的就是这个灰。
    expect(ECHARTS_COLORS_LIGHT.gridLineColor).toBe('#dbdee4')
    expect(ECHARTS_COLORS_NIGHT.gridLineColor).toBe('rgba(255, 255, 255, 0.04)')
  })

  it('axisLabel 三件平铺在本级（嵌套 textStyle 只靠 ECharts 6 兼容层拆平，getOption 里 textStyle 为 null）', () => {
    for (const s of [light, night]) {
      expect(s.axisLabel).not.toHaveProperty('textStyle')
      expect(Object.keys(s.axisLabel).sort()).toEqual(['color', 'fontFamily', 'fontSize', 'margin', 'show'])
    }
  })

  it('没有任何 CSS 变量混进 setOption（R7②：ECharts 不解析 var(--x)）', () => {
    const text = JSON.stringify({ light, night })
    expect(text).not.toMatch(/var\(--/)
    expect(text).not.toMatch(/color-mix/)
  })

  it('gl 库坑：axisLine.show 恒为 true（false 会让每次相机更新抛一次 TypeError）', () => {
    expect(light.axisLine.show).toBe(true)
    expect(night.axisLine.show).toBe(true)
  })

  it('平涂不吃光：main 强度 0、不写 shadow（阴影是 demo 感主要来源）', () => {
    expect(light.light.main.intensity).toBe(0)
    expect(light.light.ambient.intensity).toBe(1)
    expect(JSON.stringify(light.light)).not.toContain('shadow')
  })

  it('轴线宽收到 1（gl 默认是 2 的 #333 硬线）', () => {
    expect(light.axisLine.lineStyle.width).toBe(1)
  })
})

/**
 * 主题→色板的映射。计划 Task4 Step4 原本把这行写成 `isDark.value ? NIGHT : LIGHT`
 * 留在 echarts-theme.ts 里，于是「选反色板」这条变异在本层无人红（实施方 M10b 实测
 * SURVIVED：新 spec 全绿 + 全量 test/unit 全绿 + vue-tsc exit 0）——根因是 pinia 在 node
 * 不可测，不是漏写断言。修法：把映射搬进本模块成为唯一那份，theme.ts 只做委托。
 */
describe('echartsColorsFor — 主题到通用色板的映射', () => {
  it('true→night 板、false→light 板（按引用相等：复制一份同值对象也算错，那会有两份事实来源）', () => {
    expect(echartsColorsFor(true)).toBe(ECHARTS_COLORS_NIGHT)
    expect(echartsColorsFor(false)).toBe(ECHARTS_COLORS_LIGHT)
  })

  it('echarts-theme.ts 只许委托本映射，不许把选板写回原地', () => {
    const theme = readFileSync(
      fileURLToPath(new URL('../../src/utils/echarts-theme.ts', import.meta.url)),
      'utf-8',
    )
    // 实参容忍任意主题判定写法（局部变量改名、内联 `currentTheme === 'night'`、参数换行都不该
    // 误报），但不许字面量、不许取反、不许拿 `=== true/false` 把语义翻过去——那等于赌一个分支。
    expect(theme).toMatch(/echartsColorsFor\(\s*(?!true\b|false\b|!)[A-Za-z_$]/)
    expect(theme).not.toMatch(/echartsColorsFor\([^)]*[!=]==?\s*(?:true|false)/)
    // 色板名重新出现在这儿 = 有人把 `? NIGHT : LIGHT` 写回原处，从此有两份事实来源
    expect(theme).not.toMatch(/ECHARTS_COLORS_(LIGHT|NIGHT)/)
    // 这组是**源文本判据**（弱判据）：它只钉委托形式，钉不到更刁的实参写法。真选反在浏览器里
    // 由 e2e/analysis/site3d.spec.ts 的 night 判据兜住（Task 8），别把这条当唯一防线。
  })
})
