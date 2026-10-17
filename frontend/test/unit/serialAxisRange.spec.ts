import { describe, expect, it } from 'vitest'

import {
  DATA_PAD,
  JITTER_SPAN_RATIO,
  LIMIT_PAD,
  jitterForPoint,
  resolveSerialYBounds,
  type SerialPoint,
  type SerialYBoundsInput,
} from '../../src/pages/analysis/composables/serial-axis-range'

/**
 * T2：序列分布 Y 轴范围纯函数。
 * 判据全部来自 serial-axis-range.ts 头部那两条不变量——「正常点永不被裁」与
 * 「RDL/CL 两限同时可见且外侧留余量」。浏览器侧只另留一条接线证明
 * （e2e/analysis/serial-adaptive-range.spec.ts），此处不重复渲染断言。
 */

function pts(...values: Array<[number, number]>): SerialPoint[] {
  return values.map(([serial, value]) => [serial, value, 0, 0])
}

function input(over: Partial<SerialYBoundsInput> = {}): SerialYBoundsInput {
  return {
    points: pts([1, 1.0], [2, 1.2], [3, 1.1]),
    fallback: [-1, 11],
    lowerLimit: 0,
    upperLimit: 10,
    rangeType: 'RDL',
    ...over,
  }
}

/** 边界一律按近似值比：padding 是乘法产物，逐位相等会把测试写成公式复刻 */
function expectBounds(bounds: [number, number], lo: number, hi: number, msg = '') {
  expect(bounds[0], `${msg} 下边界`).toBeCloseTo(lo, 9)
  expect(bounds[1], `${msg} 上边界`).toBeCloseTo(hi, 9)
}

describe('resolveSerialYBounds · RDL 档限值入框', () => {
  // 用户截图那组数：限 [0,10]，数据 0.75~10.58（数据带比规格窗还宽）
  it('数据宽于规格窗：下边界由限值窗顶开，LSL 不再压在轴边上', () => {
    const bounds = resolveSerialYBounds(input({ points: pts([1, 0.75], [2, 10.58]) }))
    const dataPad = (10.58 - 0.75) * DATA_PAD
    expectBounds(bounds, -LIMIT_PAD * 10, 10.58 + dataPad)
    expect(0 - bounds[0], 'LSL 外侧余量 = 限宽 10%').toBeCloseTo(1, 9)
  })

  it('数据窄于规格窗（高 CP）：贴到最紧的合规框，两限各留 10% 余量', () => {
    const bounds = resolveSerialYBounds(input({ points: pts([1, 0.95], [2, 1.05]) }))
    expectBounds(bounds, -1, 11)
  })

  it('CL 档同语义（用户自定义限就是用户认的规格窗）', () => {
    expectBounds(
      resolveSerialYBounds(input({ rangeType: 'CL', points: pts([1, 4], [2, 6]) })),
      -1, 11,
    )
  })

  it('不变量 1：任一侧数据超出限值窗时都不会被裁', () => {
    const bounds = resolveSerialYBounds(input({ points: pts([1, -50], [2, 300]) }))
    expect(bounds[0]).toBeLessThan(-50)
    expect(bounds[1]).toBeGreaterThan(300)
  })

  it('anchor≠0 的超界点不参与范围（巨大 fail 值不把轴撑开）', () => {
    const points: SerialPoint[] = [[1, 1.0, 0, 0], [2, 1.2, 0, 0], [3, 1e5, 1, 2], [4, -1e5, 1, 3]]
    expectBounds(resolveSerialYBounds(input({ points })), -1, 11)
  })
})

describe('resolveSerialYBounds · 不参与入框的档位', () => {
  const wide = { points: pts([1, 4], [2, 6]) }
  const dataOnly: [number, number] = [4 - (6 - 4) * DATA_PAD, 6 + (6 - 4) * DATA_PAD]

  it('DR / S3 / S4 / S6 / 缺档：保持数据自适应，σ 窗不进图', () => {
    for (const rangeType of ['DR', 'S3', 'S4', 'S6', '']) {
      expectBounds(resolveSerialYBounds(input({ ...wide, rangeType })), dataOnly[0], dataOnly[1], rangeType)
    }
  })

  it('限值缺一侧 / 零宽窗 / NaN：后端本就不画规格限，前端也不为它撑范围', () => {
    for (const bad of [{ upperLimit: null }, { lowerLimit: null }, { lowerLimit: 5, upperLimit: 5 }, { lowerLimit: NaN }]) {
      const got = resolveSerialYBounds(input({ ...wide, ...bad }))
      expectBounds(got, dataOnly[0], dataOnly[1], JSON.stringify(bad))
    }
  })
})

describe('resolveSerialYBounds · 退化与兜底', () => {
  it('单值/全等列用 |v|·5% 撑开，零值列靠 1e-9 保证非零宽', () => {
    const flat = resolveSerialYBounds(input({ rangeType: 'DR', points: pts([1, 8], [2, 8]) }))
    expectBounds(flat, 7.6, 8.4)
    expectBounds(resolveSerialYBounds(input({ rangeType: 'DR', points: pts([1, 0]) })), -1e-9, 1e-9)
  })

  it('本 lane 无可绘制点：回退后端范围，但仍保证限值窗余量', () => {
    expectBounds(resolveSerialYBounds(input({ points: [[1, null, 1, 1]] })), -1, 11)
    // 后端连限值都给不出（无规格限参数走 null，SerialChart 原样透传）→ 由限值窗单独撑起
    const noFallback = input({ points: [], fallback: [null, null] as unknown as [number, number] })
    expectBounds(resolveSerialYBounds(noFallback), -1, 11)
  })

  it('非数值 value（bool/str 漏网）被跳过而不是炸范围', () => {
    const points: SerialPoint[] = [[1, '1.5', 0, 0], [2, 4, 0, 0], [3, 6, 0, 0]]
    const got = resolveSerialYBounds(input({ rangeType: 'DR', points }))
    expectBounds(got, 4 - (6 - 4) * DATA_PAD, 6 + (6 - 4) * DATA_PAD)
  })
})

describe('resolveSerialYBounds · 异常值处理档优先且不受入框影响', () => {
  const outlierInfo = { has_outliers: true, lower_bound: 2, upper_bound: 8 }

  it('clip / exclude：用 IQR 栅栏 ±10%，不叠加限值余量', () => {
    for (const mode of ['clip', 'exclude'] as const) {
      expectBounds(resolveSerialYBounds(input({ outlierHandling: mode, outlierInfo })), 1.4, 8.6, mode)
    }
  })

  it('off / 无异常值 / 栅栏零宽：回到常规路径', () => {
    const framed = resolveSerialYBounds(input({ outlierHandling: 'off', outlierInfo }))
    expectBounds(framed, -1, 11)
    expectBounds(
      resolveSerialYBounds(input({ outlierHandling: 'clip', outlierInfo: { has_outliers: false } })),
      -1, 11,
    )
    expectBounds(
      resolveSerialYBounds(input({ outlierHandling: 'clip', outlierInfo: { has_outliers: true, lower_bound: 5, upper_bound: 5 } })),
      -1, 11,
    )
  })
})

describe('jitterForPoint · 纵向抖动', () => {
  const SPAN = 12.3664

  it('关闭时恒为 0（默认档必须逐字节等于不抖）', () => {
    for (let i = 0; i < 50; i++) {
      expect(jitterForPoint(i, 0, 1.25, SPAN, false)).toBe(0)
    }
  })

  it('确定性：同一轴位置重复求值一字不差（重绘/缩放/切参数不许让点跳）', () => {
    const first = Array.from({ length: 40 }, (_, i) => jitterForPoint(i, 0, 1.25, SPAN, true))
    const again = Array.from({ length: 40 }, (_, i) => jitterForPoint(i, 0, 1.25, SPAN, true))
    expect(first).toEqual(again)
    expect(new Set(first).size, '40 个点应散布在多个偏移上，而不是全挤一处').toBeGreaterThan(20)
    expect(Math.min(...first), '散布要有正负两侧').toBeLessThan(0)
    expect(Math.max(...first)).toBeGreaterThan(0)
  })

  it('幅度受 |span|×3% 约束', () => {
    for (let i = 0; i < 200; i++) {
      expect(Math.abs(jitterForPoint(i, 0, 1.25, SPAN, true)))
        .toBeLessThanOrEqual(SPAN * JITTER_SPAN_RATIO + 1e-12)
    }
  })

  it('只有 anchor==0 参与：无值/超界点仍贴在原位（贴边点抖开会被读成一个具体刻度）', () => {
    for (const anchor of [1, 2, 3]) {
      expect(jitterForPoint(7, anchor, 1.25, SPAN, true), `anchor=${anchor}`).toBe(0)
    }
  })

  it('值非数值 / 跨度非正 / 跨度 NaN：一律不抖', () => {
    expect(jitterForPoint(7, 0, null, SPAN, true)).toBe(0)
    expect(jitterForPoint(7, 0, '1.25', SPAN, true)).toBe(0)
    expect(jitterForPoint(7, 0, 1.25, 0, true)).toBe(0)
    expect(jitterForPoint(7, 0, 1.25, Number.NaN, true)).toBe(0)
  })

  it('字符串序列号：同串稳定、不同串散布', () => {
    expect(jitterForPoint('A0012', 0, 1.25, SPAN, true))
      .toBe(jitterForPoint('A0012', 0, 1.25, SPAN, true))
    const many = ['A1', 'A2', 'A3', 'B1', 'B2', 'C7', 'D9'].map(
      (s) => jitterForPoint(s, 0, 1.25, SPAN, true))
    expect(new Set(many).size).toBeGreaterThan(4)
  })

  /**
   * 承重不变量：抖完仍落在本 lane 可见范围内。
   * 最坏位置是数据极值点——它离边界只剩数据自适应那 8% padding，
   * 而抖动上界是可见跨度的 3%，可见跨度 ≥ 数据跨度 ⇒ 3% < 8%，不该越界。
   * 三种形状各测一遍（限值入框 / 数据远宽于限值 / 单值退化）。
   */
  it('抖动后不被裁出可见范围：取数据极值点验算', () => {
    const cases: Array<{ name: string; bounds: [number, number]; extremes: number[] }> = [
      { name: 'RDL 限值入框', bounds: resolveSerialYBounds(input({ points: pts([1, 0.75], [2, 10.58]) })), extremes: [0.75, 10.58] },
      { name: '数据远宽于限值', bounds: resolveSerialYBounds(input({ points: pts([1, -50], [2, 300]) })), extremes: [-50, 300] },
      { name: '高 CP 窄数据带', bounds: resolveSerialYBounds(input({ points: pts([1, 0.95], [2, 1.05]) })), extremes: [0.95, 1.05] },
      { name: '单值退化', bounds: resolveSerialYBounds(input({ rangeType: 'DR', points: pts([1, 8]) })), extremes: [8] },
    ]
    for (const c of cases) {
      const span = c.bounds[1] - c.bounds[0]
      for (const v of c.extremes) {
        for (let i = 0; i < 300; i++) {
          const y = v + jitterForPoint(i, 0, v, span, true)
          expect(y, `${c.name} 值 ${v} 抖到 ${y} 越出 [${c.bounds}]`).toBeGreaterThanOrEqual(c.bounds[0])
          expect(y, `${c.name} 值 ${v} 抖到 ${y} 越出 [${c.bounds}]`).toBeLessThanOrEqual(c.bounds[1])
        }
      }
    }
  })
})
