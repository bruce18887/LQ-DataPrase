/**
 * T1：块缓存预算纯函数的关系断言。
 *
 * 只断言「单调性、钳位、窄文件不变」，不钉死常数 —— Task 2 的实测单价若重校，
 * 这里不该变红（常数真相在 docs/reference/renderer-memory-baseline-2026-10-22.md §6）。
 * 每条都带对照组，见 lessons「断言必须承重而不是全绿」。
 */
import { describe, it, expect } from 'vitest'
import {
  effectiveBlockSize,
  maxBlocksInCache,
  BLOCK_SIZE_MIN,
  DEFAULT_COL_COUNT,
} from '../../src/pages/data/components/browser/blockCap'

describe('effectiveBlockSize', () => {
  it('列数未知/为 0 时完全不动用户设置（对照组）', () => {
    for (const n of [50, 100, 500]) {
      expect(effectiveBlockSize(n, null)).toBe(n)
      expect(effectiveBlockSize(n, 0)).toBe(n)
    }
  })
  it('窄文件不降（对照组：必须等于设置值）', () => {
    expect(effectiveBlockSize(500, DEFAULT_COL_COUNT)).toBe(500)
    expect(effectiveBlockSize(100, 60)).toBe(100)
  })
  it('千列文件必须被压到单块预算内，且不低于下限', () => {
    const n = effectiveBlockSize(500, 1728)
    expect(n).toBeLessThan(500)
    expect(n).toBeGreaterThanOrEqual(BLOCK_SIZE_MIN)
  })
  it('单调：列数越多，每块行数不增', () => {
    let prev = Infinity
    for (const cols of [50, 200, 800, 1728, 4000]) {
      const n = effectiveBlockSize(500, cols)
      expect(n).toBeLessThanOrEqual(prev)
      prev = n
    }
  })
})

describe('maxBlocksInCache', () => {
  it('窄文件仍是 20 块（对照组，与今天一致）', () => {
    expect(maxBlocksInCache(100, DEFAULT_COL_COUNT)).toBe(20)
    expect(maxBlocksInCache(100, null)).toBe(20)
  })
  it('千列文件必须显著小于 20', () => {
    expect(maxBlocksInCache(100, 1728)).toBeLessThan(20)
    expect(maxBlocksInCache(100, 1728)).toBeGreaterThanOrEqual(1)
  })
  it('钳位下界恒为 1（当前块永不驱逐）', () => {
    expect(maxBlocksInCache(500, 4000)).toBe(1)
  })
})
