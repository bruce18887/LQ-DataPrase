/**
 * dock guest（会话级子集面板）模型（T2，纯函数）。
 *
 * 承重判据（D4/R5 账号记忆契约）：
 *  ① guestFreeSnapshot 无 guest 时**逐字原样**返回（不重排不归一）——既有 localStorage/
 *     账号存档不能被 guest 机制改写（chart-memory 契约）。
 *  ② 有 guest 时剥离 guest 列/空行、主图相对顺序保留、占比归一 → 持久化永不携带 subset:。
 *  ③ reconcileRows 把 guest 视为 active 成员时保留其行（勾选变化不丢子集）。
 */
import { describe, it, expect } from 'vitest'
import { guestFreeSnapshot, isGuestKey, guestKeyOf, guestIdOf } from '../../src/pages/analysis/composables/useChartDock'
import { reconcileRows } from '../../src/pages/analysis/composables/dockGeometry'

describe('guest key helpers', () => {
  it('isGuestKey / guestKeyOf / guestIdOf 往返', () => {
    expect(isGuestKey('subset:3')).toBe(true)
    expect(isGuestKey('hist')).toBe(false)
    expect(guestKeyOf(3)).toBe('subset:3')
    expect(guestIdOf('subset:3')).toBe(3)
  })
})

describe('guestFreeSnapshot — 持久化剥离 guest', () => {
  it('无 guest：逐字原样返回（同一引用，不重排不归一）', () => {
    const rows = [['hist'], ['serial', 'qq']] as any
    const rowPcts = [60, 40]
    const colPcts = [[100], [50, 50]]
    const out = guestFreeSnapshot(rows, rowPcts, colPcts, 900)
    expect(out.rows).toBe(rows)
    expect(out.rowPcts).toBe(rowPcts)
    expect(out.colPcts).toBe(colPcts)
    expect(out.bodyH).toBe(900)
  })

  it('guest 独占行：整行剔除，剩余行占比归一', () => {
    const out = guestFreeSnapshot(
      [['hist'], ['subset:1']] as any, [70, 30], [[100], [100]], null,
    )
    expect(out.rows).toEqual([['hist']])
    expect(out.rowPcts).toEqual([100])
    expect(out.colPcts).toEqual([[100]])
  })

  it('guest 与 hist 同排：guest 列剔除，hist 列占比归一到 100', () => {
    const out = guestFreeSnapshot(
      [['hist', 'subset:1'], ['serial']] as any, [60, 40], [[50, 50], [100]], null,
    )
    expect(out.rows).toEqual([['hist'], ['serial']])
    expect(out.colPcts[0]).toEqual([100])
    expect(out.rowPcts).toEqual([60, 40])
  })

  it('多 guest 混合：主图相对顺序保留', () => {
    const out = guestFreeSnapshot(
      [['subset:1'], ['serial', 'subset:2'], ['qq']] as any, [20, 50, 30], [[100], [40, 60], [100]], null,
    )
    expect(out.rows).toEqual([['serial'], ['qq']])
    expect(out.rowPcts).toEqual([62.5, 37.5])
    expect(out.colPcts).toEqual([[100], [100]])
  })
})

describe('reconcileRows — guest 随 active 保留', () => {
  it('勾选变化不丢 guest 行（guest 计入 active）', () => {
    const prev = [['hist'], ['subset:1']] as any
    const { rows } = reconcileRows(prev, ['hist', 'serial', 'subset:1'] as any)
    expect(rows).toEqual([['hist'], ['subset:1'], ['serial']])
  })
  it('guest 不在 active 时被裁掉（面板已关的场景由桥 removeGuest 先行）', () => {
    const prev = [['hist'], ['subset:1']] as any
    const { rows } = reconcileRows(prev, ['hist'] as any)
    expect(rows).toEqual([['hist']])
  })
})