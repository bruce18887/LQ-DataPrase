/**
 * T2：分析页 dock 的行高几何（像素目标 + 每行最低高度兜底）。
 *
 * 承重判据是**恒等式**而不是手抄常数：
 *   ① `autoBodyH` 定出的容器，代回 `rowHeightPx` 必须逐行等于 `rowTargetsPx`
 *      （否则「容器变高」和「行高目标」是两套各说各话的算术）；
 *   ② `floorBodyH` 代回 `rowHeightPx` 必须让最低行**恰好**等于 `MIN_ROW_H`
 *      （反解正确性的自证，取偏一个像素就红）。
 * 另配两组**对照组**钉住这次要修的旧行为：4 行时旧 `max(640, min(n*460, 1400))`
 * 会把辅助行压到 192px（低于自家 200px 拖拽下限）、用户拖小整体高度后再加图会把
 * 辅助行摊到 130px。断言写成「新值 > 旧值」，旧实现一旦回来立刻转红。
 */
import { describe, expect, it } from 'vitest'

import {
  AUX_ROW_PX,
  HIST_ROW_PX,
  MAX_BODY_H,
  MIN_ROW_H,
  ROWBAR_H,
  autoBodyH,
  defaultRowPcts,
  effBodyH,
  floorBodyH,
  isDefaultPcts,
  rowBars,
  rowHeightPx,
  rowTargetsPx,
  reconcileRowPcts,
  reconcileRows,
  type DockRow,
} from '../../src/pages/analysis/composables/dockGeometry'

const H: DockRow = 'hist'
const S: DockRow = 'serial'
const Q: DockRow = 'qq'
const B: DockRow = 'box'

/** 旧实现的容器高度算术（ChartDock.vue:153 原文），只作对照组用 */
const legacyAutoH = (rowCount: number) => Math.max(640, Math.min(rowCount * 460, 1400))
/** 旧实现的行占比（useChartDock.ts:76-83 原文，hist 恒为第 0 行） */
const legacyRowPcts = (rowCount: number) =>
  rowCount === 1 ? [100] : [58, ...Array.from({ length: rowCount - 1 }, () => 42 / (rowCount - 1))]
/** 旧实现下单行渲染像素：占比 × (容器 − 分隔条占位)。容器默认取旧的自动高度 */
const legacyRowPx = (rowCount: number, i: number, bodyH = legacyAutoH(rowCount)) => {
  const bars = Math.max(0, rowCount - 1) * ROWBAR_H
  return (legacyRowPcts(rowCount)[i] / 100) * (bodyH - bars)
}

describe('autoBodyH — 容器必须正好装下每行的目标高', () => {
  const cases: [string, DockRow[][]][] = [
    ['单行 hist', [[H]]],
    ['单行辅助图', [[S]]],
    ['2 行（默认勾选序列分布）', [[H], [S]]],
    ['3 行（默认 4 图：hist + serial/qq + box）', [[H], [S, Q], [B]]],
    ['4 行（手动拆成每行一图）', [[H], [S], [Q], [B]]],
    ['6 行（超出旧 1400 上限）', [[H], [S], [Q], [B], [H, S], [Q, B]]],
  ]

  for (const [name, rows] of cases) {
    it(`${name}：每行代回 rowHeightPx 恰好等于自己的目标高度`, () => {
      const body = autoBodyH(rows)
      const bars = rowBars(rows.length)
      const targets = rowTargetsPx(rows)
      const pcts = defaultRowPcts(rows)
      expect(pcts.reduce((a, b) => a + b, 0), '占比之和').toBeCloseTo(100, 6)
      rows.forEach((_, i) => {
        expect(rowHeightPx(pcts[i], body, bars), `第 ${i} 行`).toBeCloseTo(targets[i], 6)
      })
    })
  }

  it('随行数线性增长，不再被 1400 截断', () => {
    expect(autoBodyH([[H], [S]])).toBeLessThan(autoBodyH([[H], [S], [Q]]))
    expect(autoBodyH([[H], [S], [Q], [B]])).toBeGreaterThan(1400)
  })

  it('hist 行高于辅助行（保留「直方图明显更高」的既有意图）', () => {
    const rows: DockRow[][] = [[H], [S, Q], [B]]
    const t = rowTargetsPx(rows)
    expect(t[0]).toBeGreaterThan(t[1])
    expect(t[1]).toBe(t[2])
  })
})

describe('defaultRowPcts — 高份额跟着 hist 所在的行，不是写死第 0 行', () => {
  it('hist 在第二行时，第二行才拿高份额', () => {
    const p = defaultRowPcts([[S, Q], [H]])
    expect(p[1]).toBeGreaterThan(p[0])
  })

  it('无 hist 时各行均分（旧实现会让首行白占 58%）', () => {
    const p = defaultRowPcts([[S], [Q], [B]])
    expect(new Set(p.map((x) => Math.round(x * 1e6))).size).toBe(1)
  })

  it('空 rows 返回空数组（空态兜底不得造出 NaN 占比）', () => {
    expect(defaultRowPcts([])).toEqual([])
  })
})

describe('floorBodyH — 每行最低高度的反解', () => {
  it('代回 rowHeightPx 后最低行恰好等于 MIN_ROW_H（恒等式）', () => {
    const pcts = [70, 30]
    const bars = rowBars(2)
    const body = floorBodyH(pcts, bars)
    expect(rowHeightPx(30, body, bars)).toBeCloseTo(MIN_ROW_H, 6)
    expect(rowHeightPx(70, body, bars)).toBeGreaterThan(MIN_ROW_H)
  })

  it('占比越极端，需要越高的容器才不破下限', () => {
    expect(floorBodyH([98, 1, 1], rowBars(3))).toBeGreaterThan(floorBodyH([40, 30, 30], rowBars(3)))
  })

  it('空数组 / 非正 / 非有限占比一律返回 0，不牵连渲染', () => {
    expect(floorBodyH([], 0)).toBe(0)
    expect(floorBodyH([100], 0)).toBe(0) // 单行没有「最低行」问题：它就是全部
    expect(floorBodyH([NaN, 50], 10)).toBe(0)
    expect(floorBodyH([0, 100], 10)).toBe(0)
    expect(floorBodyH([-5, 105], 10)).toBe(0)
  })
})

describe('effBodyH — 渲染期兜底，不回写 bodyH', () => {
  it('bodyH 为空时取 autoBodyH', () => {
    const rows: DockRow[][] = [[H], [S, Q], [B]]
    expect(effBodyH(null, rows, defaultRowPcts(rows))).toBe(autoBodyH(rows))
  })

  it('bodyH 大于目标时尊重用户拖出的值（兜底只抬不压）', () => {
    const rows: DockRow[][] = [[H], [S]]
    expect(effBodyH(2400, rows, defaultRowPcts(rows))).toBe(2400)
  })

  it('bodyH 被用户拖小后加图：兜到 MIN_ROW_H，不再摊到旧实现的 130px', () => {
    const rows: DockRow[][] = [[H], [S, Q], [B]]
    const pcts = defaultRowPcts(rows)
    const body = effBodyH(640, rows, pcts)
    const aux = rowHeightPx(pcts[1], body, rowBars(rows.length))
    // 用户主动压过整体高度 ⇒ 压缩语义保留，但最低行被抬到下限（旧实现 130.2px）
    expect(aux).toBeCloseTo(MIN_ROW_H, 6)
    expect(legacyRowPx(3, 1, 640)).toBeLessThan(131)
  })

  it('4 行时辅助行不再低于自家 200px 拖拽下限（旧实现 191.8px）', () => {
    const rows: DockRow[][] = [[H], [S], [Q], [B]]
    const pcts = defaultRowPcts(rows)
    const body = effBodyH(null, rows, pcts)
    const aux = rowHeightPx(pcts[1], body, rowBars(rows.length))
    expect(aux).toBeGreaterThanOrEqual(MIN_ROW_H)
    expect(legacyRowPx(4, 1)).toBeLessThan(MIN_ROW_H) // 旧值 191.8 < 200 =  bug 本体
  })

  it('用户手调（可达范围内）出瘦行时，容器被抬到不破 MIN_ROW_H', () => {
    // [71.43, 28.57] 是 bodyH=700 时行间隔条能拖出的极限（minPct = 200/700×100）
    const rows: DockRow[][] = [[H], [S]]
    const tuned = [71.43, 28.57]
    const body = effBodyH(700, rows, tuned)
    expect(rowHeightPx(28.57, body, rowBars(2))).toBeGreaterThanOrEqual(MIN_ROW_H)
  })

  it('损坏的极端占比不得把容器吹过 MAX_BODY_H（兜底也封顶）', () => {
    const rows: DockRow[][] = [[H], [S]]
    const corrupt = [99, 1]
    expect(effBodyH(700, rows, corrupt)).toBeLessThanOrEqual(MAX_BODY_H)
    // 对照组：封顶后绝不等于反解出来的荒谬值
    expect(floorBodyH(corrupt, rowBars(2))).toBeGreaterThan(MAX_BODY_H)
  })
})

describe('reconcileRowPcts — 增删勾选时不得销毁既有比例', () => {
  it('未手调时跟随像素目标：新增行正好拿到辅助行目标高度', () => {
    const prevRows: DockRow[][] = [[H]]
    const nextRows: DockRow[][] = [[H], [S]]
    const p = reconcileRowPcts(prevRows, [100], nextRows, [0, -1])
    expect(p).toEqual(defaultRowPcts(nextRows))
    const body = autoBodyH(nextRows)
    expect(rowHeightPx(p[1], body, rowBars(2))).toBeCloseTo(AUX_ROW_PX, 6)
    expect(rowHeightPx(p[0], body, rowBars(2))).toBeCloseTo(HIST_ROW_PX, 6)
  })

  it('手调过则保留存活行两两比值，新行与最后一个存活行等高', () => {
    const prevRows: DockRow[][] = [[H], [S]]
    const nextRows: DockRow[][] = [[H], [S], [Q]]
    const p = reconcileRowPcts(prevRows, [70, 30], nextRows, [0, 1, -1])
    expect(p[0] / p[1]).toBeCloseTo(70 / 30, 6)
    expect(p[2]).toBe(p[1])
    expect(p.reduce((a, b) => a + b, 0)).toBeCloseTo(100, 6)
  })

  it('取消勾选（行数减少）同样保留比例，不整表抹回默认', () => {
    const prevRows: DockRow[][] = [[H], [S], [Q]]
    const nextRows: DockRow[][] = [[H], [Q]]
    const p = reconcileRowPcts(prevRows, [60, 25, 15], nextRows, [0, 2])
    expect(p[0] / p[1]).toBeCloseTo(60 / 15, 6)
    expect(p.reduce((a, b) => a + b, 0)).toBeCloseTo(100, 6)
  })

  it('存活行内部少了成员（同行两图关一张）仍算存活，占比跟随像素目标', () => {
    const prevRows: DockRow[][] = [[H], [S, Q]]
    const nextRows: DockRow[][] = [[H], [S]]
    // [62.9, 37.1] 就是 prevRows 的默认占比（容差内）⇒ 不算手调
    const p = reconcileRowPcts(prevRows, [62.9, 37.1], nextRows, [0, 1])
    expect(p).toEqual(defaultRowPcts(nextRows))
  })

  it('prevPcts 长度与 prevRows 不符（旧持久化残留）时退回像素目标', () => {
    const prevRows: DockRow[][] = [[H], [S]]
    const nextRows: DockRow[][] = [[H], [S], [Q]]
    const p = reconcileRowPcts(prevRows, [50], nextRows, [0, 1, -1])
    expect(p).toEqual(defaultRowPcts(nextRows))
  })

  it('isDefaultPcts 认得自己刚生成的那组（否则手调判定会误判）', () => {
    const rows: DockRow[][] = [[H], [S, Q], [B]]
    expect(isDefaultPcts(defaultRowPcts(rows), rows)).toBe(true)
    expect(isDefaultPcts([50, 25, 25], rows)).toBe(false)
    expect(isDefaultPcts([NaN, 50, 50], rows)).toBe(false)
  })
})

describe('reconcileRows — 存活行的来源索引不得随渲染序位漂移', () => {
  it('首挂补图：新行标 -1，存活行标回它在旧 rows 里的下标', () => {
    const r = reconcileRows([[H]], [H, S])
    expect(r.rows).toEqual([[H], [S]])
    expect(r.srcIdx).toEqual([0, -1])
  })

  it('同行两图关一张：行仍算存活，成员消失但索引不变', () => {
    const r = reconcileRows([[H], [S, Q]], [H, S])
    expect(r.rows).toEqual([[H], [S]])
    expect(r.srcIdx).toEqual([0, 1])
  })

  it('中间整行清空后，后面那行的索引仍是旧下标（漂移就会拿错占比）', () => {
    // 旧第 1 行 [serial] 被取消勾选而消失，旧第 2 行 [qq] 降到渲染第 1 行
    const r = reconcileRows([[H], [S], [Q]], [H, Q, B])
    expect(r.rows).toEqual([[H], [Q], [B]])
    expect(r.srcIdx).toEqual([0, 2, -1])
  })

  it('一次勾选多张新图：按每行 2 张分块追加', () => {
    const r = reconcileRows([[H]], [H, S, Q, B])
    expect(r.rows).toEqual([[H], [S, Q], [B]])
    expect(r.srcIdx).toEqual([0, -1, -1])
  })

  it('全关 → 空态占位行，索引 -1（不得返回空 rows 让 v-for 无从渲染）', () => {
    const r = reconcileRows([[H], [S]], [])
    expect(r.rows).toEqual([[]])
    expect(r.srcIdx).toEqual([-1])
  })

  it('恒等式：摊平后的 rows 恰好等于 active 集合，无重复无遗漏', () => {
    const cases: [DockRow[][], DockRow[]][] = [
      [[[H], [S, Q], [B]], [H, S, Q, B]],
      [[[H], [S, Q], [B]], [Q, B]],
      [[[H], [S, Q], [B]], [H, S, Q, B, H]],
      [[[H, S]], [B, Q]],
    ]
    for (const [prev, active] of cases) {
      const flat = reconcileRows(prev, active).rows.flat()
      expect(new Set(flat)).toEqual(new Set(active))
      expect(flat.length, `不应出现重复图：${JSON.stringify(active)}`).toBe(new Set(active).size)
    }
  })
})
