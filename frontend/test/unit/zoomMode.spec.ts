/**
 * T2：页面缩放接管权的判定表（`zoomMode.ts`）。
 *
 * 承重的是「两档必须相反」这组对照，而不是把实现抄一遍：
 * - 写成恒 true ⇒ 浏览器档又去给 `<html>` 写 CSS zoom，teleport 到 body 的下拉/popover
 *   重新按「坐标 ×(zoom−1)」跑位（2026-10-21 那个 bug 的形状）；
 * - 写成恒 false ⇒ 桌面版连应用内缩放都没了（Electron 档必须仍由应用接管）。
 * 浏览器档的实际后果（派发 Ctrl+滚轮后 `<html>` 仍无 zoom、不出指示器）由
 * `e2e/global/global.spec.ts` 那条回归钉住——那是只有浏览器能证的部分。
 */
import { describe, expect, it } from 'vitest'

import { detectZoomRuntime, shouldOwnZoom, type ZoomRuntime } from '../../src/composables/zoomMode'

const RUNTIMES: ZoomRuntime[] = ['electron', 'browser']

describe('detectZoomRuntime — 有 electronAPI 才算桌面档', () => {
  it.each([
    [true, 'electron'],
    [false, 'browser'],
  ] as const)('hasElectronApi=%s → %s', (hasApi, expected) => {
    expect(detectZoomRuntime(hasApi)).toBe(expected)
  })
})

describe('shouldOwnZoom — 只有桌面档接管缩放', () => {
  it('桌面档接管、浏览器档让给原生缩放', () => {
    expect(shouldOwnZoom('electron')).toBe(true)
    expect(shouldOwnZoom('browser')).toBe(false)
  })

  it('两档判据相反（对照组：防它被改成恒真/恒假的常量）', () => {
    const verdicts = RUNTIMES.map(shouldOwnZoom)
    expect(new Set(verdicts).size, '两档必须给出不同结论').toBe(2)
  })

  it('运行环境判定与接管权一一对应，不存在第三种 runtime', () => {
    for (const hasApi of [true, false]) {
      expect(shouldOwnZoom(detectZoomRuntime(hasApi))).toBe(hasApi)
    }
  })
})
