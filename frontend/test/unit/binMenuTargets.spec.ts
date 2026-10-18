/**
 * T2：Bin 右键「定位」的目标顺序。
 *
 * 红格测试列 → 临界橙格列 → Bin。橙格只是解释 fail 原因，不能把
 * fail_cells 的语义改掉；隐藏列要跳过，全隐藏时返回 null 由调用方
 * 退回整行 flash。
 */
import { describe, expect, it } from 'vitest'

import { orderedJumpTargets, firstVisibleJumpTarget } from '../../src/pages/data/components/browser/binMenuTargets'

const base = {
  failCols: ['BIN'],
  borderlineCols: [],
  binCol: 'BIN',
  displayCols: ['BIN', 'A', 'B', 'C'],
}

describe('orderedJumpTargets', () => {
  it('红格测试列在前、橙格居中、Bin 最后', () => {
    expect(
      orderedJumpTargets({
        ...base,
        failCols: ['A', 'BIN'],
        borderlineCols: ['C'],
      }),
    ).toEqual(['A', 'C', 'BIN'])
  })

  it('纯 Bin fail 有临界项 → 先跳临界列', () => {
    expect(firstVisibleJumpTarget({ ...base, borderlineCols: ['C'] })).toBe('C')
  })

  it('纯 Bin fail 无临界项 → 退回 Bin', () => {
    expect(firstVisibleJumpTarget(base)).toBe('BIN')
  })

  it('同一列同时出现在红/橙列表时不重复', () => {
    expect(
      orderedJumpTargets({ ...base, failCols: ['A', 'BIN'], borderlineCols: ['A'] }),
    ).toEqual(['A', 'BIN'])
  })

  it('跳过隐藏列；目标列全隐藏返回 undefined 由调用方整行 flash', () => {
    expect(
      firstVisibleJumpTarget({ ...base, borderlineCols: ['C'], displayCols: ['BIN', 'A'] }),
    ).toBe('BIN')
    expect(
      firstVisibleJumpTarget({ ...base, borderlineCols: ['C'], displayCols: ['A'] }),
    ).toBeUndefined()
    expect(
      firstVisibleJumpTarget({ ...base, borderlineCols: ['C'], displayCols: [] }),
    ).toBeUndefined()
  })
})
