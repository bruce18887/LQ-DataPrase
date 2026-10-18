/**
 * T2：右键菜单落位在页面缩放下的坐标换算。
 *
 * 承重判据是「**画出来的位置 == 右键点**」这条恒等式：`left` 写的是 local px，
 * 浏览器把它乘回 zoom 才落到屏幕上，所以断言一律乘回去再比，而不是去核对某个
 * 手算常数（那只会把实现抄一遍，改错也照样绿）。
 *
 * zoom=1 那组是对照组：它必须逐字等于旧写法 `max(8, min(clientX, vw - w - 8))`，
 * 用来证明这次换算没有顺手改掉 100% 档的既有行为。
 */
import { describe, expect, it } from 'vitest'

import { contextMenuPoint } from '../../src/pages/data/components/browser/contextMenuPosition'

const VP = { viewportWidth: 1200, viewportHeight: 800 }

const point = (clientX: number, clientY: number, zoom: number, menuWidth = 200, menuHeight = 72) =>
  contextMenuPoint({ clientX, clientY, menuWidth, menuHeight, ...VP, zoom })

/** 旧实现（无换算、无 zoom 概念）在同样入参下的落点 */
const legacy = (clientX: number, clientY: number, menuWidth = 200, menuHeight = 72) => ({
  x: Math.max(8, Math.min(clientX, VP.viewportWidth - menuWidth - 8)),
  y: Math.max(8, Math.min(clientY, VP.viewportHeight - menuHeight - 8)),
})

describe('contextMenuPoint — 画出来的位置必须等于右键点', () => {
  for (const zoom of [0.5, 0.8, 1, 1.25, 1.5, 2]) {
    it(`zoom=${zoom}：未夹紧时 left*zoom 回到 clientX`, () => {
      // 取一组远离边缘的点，夹紧不参与，判据纯粹是空间换算
      for (const [cx, cy] of [[120, 90], [400, 300], [648, 450]] as const) {
        const p = point(cx, cy, zoom)
        expect(p.x * zoom, `zoom=${zoom} (${cx},${cy})`).toBeCloseTo(cx, 6)
        expect(p.y * zoom, `zoom=${zoom} (${cx},${cy})`).toBeCloseTo(cy, 6)
      }
    })
  }

  it('zoom=1 与旧实现逐字相同（对照组：本次换算不动 100% 档）', () => {
    for (const [cx, cy] of [[0, 0], [120, 90], [648, 450], [1190, 790], [5000, 5000]] as const) {
      expect(point(cx, cy, 1)).toEqual(legacy(cx, cy))
    }
  })

  it('偏移量随距离线性增长：不换算的话 1.25 档会偏出 clientX*(zoom-1)', () => {
    // 这条钉住「bug 的量级」本身：旧写法在 1.25 档把 648 摆到 810，偏 162px
    const fixed = point(648, 450, 1.25)
    expect(fixed.x * 1.25).toBeCloseTo(648, 6)
    expect(648 * 1.25 - 648).toBeCloseTo(162, 6)
  })
})

describe('contextMenuPoint — 夹紧也在同一空间里算', () => {
  it('高倍档贴右下：菜单整体不出视口（视口 px 口径）', () => {
    for (const zoom of [1.25, 1.5, 2]) {
      const w = 200
      const h = 72
      const p = point(1190, 790, zoom, w, h)
      expect(p.x * zoom + w, `zoom=${zoom} 右缘`).toBeLessThanOrEqual(VP.viewportWidth + 1e-6)
      expect(p.y * zoom + h, `zoom=${zoom} 下缘`).toBeLessThanOrEqual(VP.viewportHeight + 1e-6)
    }
  })

  it('贴左上角时收在 8 local px，不落到负数', () => {
    expect(point(0, 0, 1.5)).toEqual({ x: 8, y: 8 })
  })

  it('菜单比视口还宽时停在留白处，而不是翻成负 left', () => {
    const p = point(1190, 790, 1, 5000, 5000)
    expect(p).toEqual({ x: 8, y: 8 })
  })

  it('留白按 local px 生效：8 local px 在 1.25 档画出来是 10 视口 px', () => {
    const p = point(1199, 799, 1.25)
    expect(p.x).toBeCloseTo((1200 - 200) / 1.25 - 8, 6)
    expect(p.x * 1.25).toBeCloseTo(1200 - 200 - 10, 6)
  })
})

describe('contextMenuPoint — 入参退化', () => {
  it('zoom 为 0 / 负数 / NaN 时按 1 处理', () => {
    for (const bad of [0, -1, Number.NaN]) {
      expect(point(648, 450, bad)).toEqual(point(648, 450, 1))
    }
  })

  it('首帧（menuWidth/Height=0）只换算空间，不参与夹紧', () => {
    expect(point(648, 450, 1.25, 0, 0)).toEqual({ x: 648 / 1.25, y: 450 / 1.25 })
  })
})
