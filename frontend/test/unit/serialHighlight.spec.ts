import { describe, it, expect } from 'vitest'
import { pickHighlightPoints } from '../../src/pages/analysis/composables/serialHighlight'

/** 绘制点全字段（与 SerialChart laneGroups 的点对象同形）：tooltip 需要这些字段原样保留。 */
interface DrawPoint {
  value: [number, number, number, number]
  realY: number
  realSerial: number | string
  isFail: boolean
  anchor: number
}

function pt(realSerial: number | string, y = 1): DrawPoint {
  return { value: [0, y, 0, 0], realY: y, realSerial, isFail: false, anchor: 0 }
}

describe('pickHighlightPoints', () => {
  it('逐 lane 精确匹配：各 lane 只留命中点，保持 lane 结构与顺序', () => {
    const a0 = pt(1); const a1 = pt(2); const a2 = pt(3)
    const b0 = pt(4); const b1 = pt(5)
    const lanes = [[a0, a1, a2], [b0, b1]]
    const out = pickHighlightPoints(lanes, [2, 4])
    expect(out).toEqual([[a1], [b0]])
    // lane 数不变（即使某 lane 无命中也保留空 lane）
    expect(out.length).toBe(2)
  })

  it('点对象原样保留（同一引用，全字段不丢）', () => {
    const a = pt(7, 3.5)
    const out = pickHighlightPoints([[a]], [7])
    expect(out[0][0]).toBe(a) // 引用相等 ⇒ value/realY/realSerial/isFail/anchor 全在
    expect(out[0][0].realY).toBe(3.5)
    expect(out[0][0].value).toEqual([0, 3.5, 0, 0])
  })

  it('严格类型：数值 4 不匹配字符串 "4"（与后端 isin 口径一致）', () => {
    const num = pt(4)
    const str = pt('4')
    const lanes = [[num, str]]
    expect(pickHighlightPoints(lanes, [4])).toEqual([[num]])
    expect(pickHighlightPoints(lanes, ['4'])).toEqual([[str]])
    // 混合 serials 各取各的，互不串配
    expect(pickHighlightPoints(lanes, [4, '4'])).toEqual([[num, str]])
  })

  it('空 serials → 各 lane 空（lane 结构仍在）', () => {
    const lanes = [[pt(1), pt(2)], [pt(3)]]
    expect(pickHighlightPoints(lanes, [])).toEqual([[], []])
  })

  it('serials 重复 → 点只出现一次（Set 成员判定，不按 serials 次数复制）', () => {
    const a = pt(4)
    const lanes = [[a, pt(5)]]
    const out = pickHighlightPoints(lanes, [4, 4, 4])
    expect(out).toEqual([[a]])
    expect(out[0].length).toBe(1)
  })

  it('未命中 serial → 空 lane', () => {
    const lanes = [[pt(1), pt(2)], [pt(3)]]
    expect(pickHighlightPoints(lanes, [99, 'nope'])).toEqual([[], []])
  })

  it('空 laneGroups → 空数组', () => {
    expect(pickHighlightPoints([], [1, 2])).toEqual([])
  })

  it('字符串序列号路径：按 label 精确匹配', () => {
    const a = pt('A1'); const b = pt('A2'); const c = pt('B1')
    const out = pickHighlightPoints([[a, b, c]], ['A2', 'B1'])
    expect(out).toEqual([[b, c]])
  })
})
