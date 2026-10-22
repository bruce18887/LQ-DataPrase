/**
 * T2（docs/reference/testing-gates.md §2，node 环境、零 DOM）：块缓存预算纯函数的关系断言。
 *
 * 只断言「单调性、钳位、窄文件不变、单块/驻留不超预算」，不钉死常数 —— Task 2 的实测单价若重校，
 * 这里不该变红（常数真相在 docs/reference/renderer-memory-baseline-2026-10-22.md §6）。
 * 唯一例外是下面标了「窗口断言」的两条：它们显式写出本文件不变量依赖常数的哪个区间，重校后
 * 一旦落在区间外，按 baseline 文档重新推导取值，不要顺手改成"看起来也能过"的数字。
 * 每条都带对照组，见 lessons「断言必须承重而不是全绿」。
 */
import { describe, it, expect } from 'vitest'
import {
  effectiveBlockSize,
  maxBlocksInCache,
  BLOCK_SIZE_MIN,
  BLOCK_SIZE_MAX,
  DEFAULT_COL_COUNT,
  MAX_BLOCKS,
  CELL_PER_BLOCK_MAX,
  CELL_RETAIN_BUDGET,
} from '../../src/pages/data/components/browser/blockCap'

describe('effectiveBlockSize', () => {
  it('列数未知/为 0 时完全不动用户设置（对照组）', () => {
    for (const n of [50, 100, 500]) {
      expect(effectiveBlockSize(n, null)).toBe(n)
      expect(effectiveBlockSize(n, 0)).toBe(n)
    }
  })
  it('列数未知时设置域钳位仍生效：上限 500、下限 50、0/NaN 回落到下限', () => {
    // 上限：删掉 Math.min(BLOCK_SIZE_MAX, …) 后这里会读出 5000
    expect(effectiveBlockSize(5000, null)).toBe(BLOCK_SIZE_MAX)
    // 下限：删掉 Math.max(BLOCK_SIZE_MIN, …) 后这里会读出 20
    expect(effectiveBlockSize(20, null)).toBe(BLOCK_SIZE_MIN)
    // 0 由外层 Math.max 兜住，NaN 只有 `|| BLOCK_SIZE_MIN` 那一支能兜住（NaN 会穿透两个 Math.*）
    expect(effectiveBlockSize(0, null)).toBe(BLOCK_SIZE_MIN)
    expect(effectiveBlockSize(Number.NaN, null)).toBe(BLOCK_SIZE_MIN)
    expect(effectiveBlockSize(Number.NaN, 100)).toBe(BLOCK_SIZE_MIN)
  })
  it('窄文件不降（对照组：必须等于设置值）', () => {
    expect(effectiveBlockSize(500, DEFAULT_COL_COUNT)).toBe(500)
    expect(effectiveBlockSize(100, 60)).toBe(100)
  })
  it('千列文件必须被压到单块预算内，且不低于下限', () => {
    const n = effectiveBlockSize(500, 1728)
    expect(n).toBeLessThan(500)
    expect(n).toBeGreaterThanOrEqual(BLOCK_SIZE_MIN)
    expect(n * 1728).toBeLessThanOrEqual(CELL_PER_BLOCK_MAX)
  })
  it('R9 不变量：钳位生效的每一档，单块格数都不得吃到 CELL_PER_BLOCK_MAX 之上', () => {
    // 承重：Math.floor 换成 round 后 800 档读 444（355,200）、4000 档读 89（356,000），
    // 换成 ceil 后 1728 档读 206（355,968）—— 都越界 ⇒ 一块吃满预算、翻页退化成请求风暴
    for (const c of [50, 200, 800, 1728, 4000]) {
      expect(effectiveBlockSize(500, c) * c).toBeLessThanOrEqual(CELL_PER_BLOCK_MAX)
    }
  })
  it('列数极多、按格预算算出的行数低于下限时按下限兜底', () => {
    // 8000 列：355,029 / 8000 = 44 < 50 ⇒ 兜到 BLOCK_SIZE_MIN（此处 50×8000 超单块预算是兜底的必然代价）
    expect(effectiveBlockSize(500, 8000)).toBe(BLOCK_SIZE_MIN)
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
    // 窗口断言：min(20, floor(预算 / 100×142)) 要等于 20，需 CELL_RETAIN_BUDGET ≥ 20×14,200 = 284,000
    expect(maxBlocksInCache(100, DEFAULT_COL_COUNT)).toBe(20)
    expect(maxBlocksInCache(100, null)).toBe(20)
    // 列数未知 ⇒ 预算完全不介入，也不按 DEFAULT_COL_COUNT 估宽度。600 > BLOCK_SIZE_MAX 是
    // 刻意取的：它是本函数唯一能看出「有没有偷偷按 142 估」的输入（估了会读 floor(预算/85,200)=16）
    expect(maxBlocksInCache(600, null)).toBe(MAX_BLOCKS)
  })
  it('千列文件必须显著小于 20', () => {
    expect(maxBlocksInCache(100, 1728)).toBeLessThan(20)
    expect(maxBlocksInCache(100, 1728)).toBeGreaterThanOrEqual(1)
  })
  it('钳位下界恒为 1（当前块永不驱逐）', () => {
    // 窗口断言：500×4000 = 2,000,000 格 / 块，要落在 floor 归零那一档，需 CELL_RETAIN_BUDGET < 2,000,000
    expect(maxBlocksInCache(500, 4000)).toBe(1)
  })
  it('驻留上限取「最大可容纳」：cap×格数 ≤ 预算，再加一块就破预算（除非已用满 MAX_BLOCKS）', () => {
    // 承重：Math.floor→round 让 100×800 读 18、500×1728 读 2；→ceil 让 100×1728 读 9；
    // 预算常数误用 CELL_PER_BLOCK_MAX 让 100×1728 读 2（加一块 518,400 其实还没到真预算）—— 全在这里红
    const pairs: ReadonlyArray<readonly [number, number]> = [
      [100, DEFAULT_COL_COUNT],
      [100, 800],
      [100, 1728],
      [200, 600],
      [500, 1728],
    ]
    for (const [blockSize, c] of pairs) {
      const cap = maxBlocksInCache(blockSize, c)
      const cells = blockSize * c
      expect(cap).toBeGreaterThanOrEqual(1)
      expect(cap).toBeLessThanOrEqual(MAX_BLOCKS)
      expect(cap * cells).toBeLessThanOrEqual(CELL_RETAIN_BUDGET)
      if (cap !== MAX_BLOCKS) expect((cap + 1) * cells).toBeGreaterThan(CELL_RETAIN_BUDGET)
    }
  })
})
