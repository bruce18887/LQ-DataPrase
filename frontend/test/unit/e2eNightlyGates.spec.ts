// frontend/test/unit/e2eNightlyGates.spec.ts
// 并行时代的退化判据。基准全是实测数：N=4 干净轮 6.2min / 单价 3.10s / 效率 3.04（串行 19.7min / 2.89s）。
import { describe, expect, it } from 'vitest'
import { THRESHOLDS, blockingReds, evaluateGates, flakeTotal } from '../../e2e/helpers/nightly-gates.mjs'

const clean = {
  specs: 384, wallMs: 6.2 * 60_000, perSpecMs: 3_100, efficiency: 3.04,
  stats: { unexpected: 0, flaky: 0 },
}

describe('阈值就是实测标定', () => {
  it('墙钟 12min（10min 级目标 + 余量），单价 4.5s，用例 450，flake 5，效率下限 0.7N', () => {
    expect(THRESHOLDS.wallMs).toBe(12 * 60_000)
    expect(THRESHOLDS.perSpecMs).toBe(4_500)
    expect(THRESHOLDS.specs).toBe(450)
    expect(THRESHOLDS.flakes).toBe(5)
    expect(THRESHOLDS.efficiencyFloorFactor).toBe(0.7)
  })
})

describe('evaluateGates', () => {
  it('干净轮不拦', () => { expect(evaluateGates(clean, 4)).toEqual([]) })

  it('墙钟超 12min 拦（挂死与目标同一条）', () => {
    expect(evaluateGates({ ...clean, wallMs: 13 * 60_000 }, 4).join()).toMatch(/墙钟/)
  })

  it('效率低于 0.7N 拦：这是「并行在空转」的唯一硬信号', () => {
    expect(evaluateGates({ ...clean, efficiency: 2.0 }, 4).join()).toMatch(/效率/)
    expect(evaluateGates({ ...clean, efficiency: 2.81 }, 4)).toEqual([])
  })

  it('单价阈值随并发放宽，不会把争用误报成退化（实测 3.01~3.90s）', () => {
    expect(evaluateGates({ ...clean, perSpecMs: 3_900 }, 4)).toEqual([])
    expect(evaluateGates({ ...clean, perSpecMs: 4_600 }, 4).join()).toMatch(/单价/)
  })

  it('崩池轮什么都不判：verdict=VOID(infra) 时指标不可信，交给人重跑', () => {
    const voided = { ...clean, verdict: 'VOID (infra)', infraSlots: [1, 3], stats: { unexpected: 155, flaky: 0 } }
    expect(evaluateGates(voided, 4)).toEqual([])
    expect(blockingReds(voided)).toEqual({ count: null, voided: true, confirmed: 0, unresolved: 0 })
  })

  it('有复跑判级时：负载抖动不拦门禁，真红与"没验成"才拦', () => {
    const withRecheck = {
      ...clean, stats: { unexpected: 3, flaky: 0 },
      recheck: { confirmed: ['a.spec.ts'], loadFlakes: ['b.spec.ts', 'c.spec.ts'], unresolved: [], countsBlock: true },
    }
    expect(blockingReds(withRecheck)).toEqual({ count: 1, voided: false, confirmed: 1, unresolved: 0 })
    expect(evaluateGates(withRecheck, 4).join()).toMatch(/真红 1/)
    expect(flakeTotal(withRecheck)).toBe(2)            // flaky 0 + 负载抖动 2
  })

  it('复跑后全绿的一轮：flake 记账但门禁放行', () => {
    const r = {
      ...clean, stats: { unexpected: 2, flaky: 0 },
      recheck: { confirmed: [], loadFlakes: ['x.spec.ts', 'y.spec.ts'], unresolved: [], countsBlock: false },
    }
    expect(evaluateGates(r, 4)).toEqual([])
    expect(flakeTotal(r)).toBe(2)
  })

  it('负载抖动累计超过 flake 阈值仍然拦 —— 抖动变多不是可以无限吞的', () => {
    const r = {
      ...clean, stats: { unexpected: 6, flaky: 0 },
      recheck: { confirmed: [], loadFlakes: ['1', '2', '3', '4', '5', '6'], unresolved: [], countsBlock: false },
    }
    expect(evaluateGates(r, 4).join()).toMatch(/flake 6 > 5/)
  })

  it('没有复跑结果时退回原始 unexpected 计数（不给"没跑复跑"留后门）', () => {
    expect(blockingReds({ ...clean, stats: { unexpected: 2, flaky: 0 } })).toEqual({ count: 2, voided: false, confirmed: 2, unresolved: 0 })
  })

  it('旧的串行产物没有 efficiency 字段 —— 缺字段不等于违规，不许误报效率', () => {
    const legacy = { specs: 384, wallMs: 8 * 60_000, perSpecMs: 2_890, stats: { unexpected: 0, flaky: 0 } }
    expect(evaluateGates(legacy, 1)).toEqual([])
    // 而墙钟本身照样管：串行 19.7min 在新阈值下就是超目标，该报
    expect(evaluateGates({ ...legacy, wallMs: 19.7 * 60_000 }, 1).join()).toMatch(/墙钟/)
  })

  it('用例数超上限单独报（套件变大是另一件事）', () => {
    expect(evaluateGates({ ...clean, specs: 451 }, 4).join()).toMatch(/用例数/)
  })
})
