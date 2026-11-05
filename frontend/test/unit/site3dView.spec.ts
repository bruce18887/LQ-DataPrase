/**
 * T2：3D 视角的形状校验与实时读取（specs/2026-11-05 §4）。
 *
 * 两条承重：
 * ① `orthographicSize` 存**模型值**：gl 的 Grid3DView 用 `setFromViewControlModel(model, 0)`
 *    调用（echarts-gl.js:41467），extraOpts 为假值 ⇒ baseOrthoSize=1（:39002-39016）。
 *    所以读取 = 实时值 − 1；写回由 gl 再加 1。去掉 -1 会让「记住的视角」每次重渲染缩一档。
 * ② 毒数据整份丢弃：五个量任一非有限数就返回 null（半信一半会画出怪机位）。
 */
import { describe, expect, it } from 'vitest'

import { isSameSite3DView, readLiveView, sanitizeSite3DView, type Site3DView } from '../../src/pages/analysis/composables/site3dView'

const GOOD: Site3DView = { alpha: 31.5, beta: -12, distance: 260, orthographicSize: 149, center: [1, 2, 3] }

function fakeChart(control: Record<string, unknown> | null) {
  return {
    getModel: () => ({ getComponent: (name: string) => (name === 'grid3D' ? { kind: 'grid3d' } : null) }),
    getViewOfComponentModel: () => (control ? { _control: control } : {}),
  }
}

function fakeControl(over: Record<string, unknown> = {}) {
  return {
    getAlpha: () => 40,
    getBeta: () => -7,
    getDistance: () => 300,
    getOrthographicSize: () => 151,
    getCenter: () => [0.5, 1.5, 2.5],
    ...over,
  }
}

describe('sanitizeSite3DView', () => {
  it('合法对象原样返回（center 复制成新数组，不共享入参）', () => {
    const out = sanitizeSite3DView(GOOD)!
    expect(out).toEqual(GOOD)
    expect(out.center).not.toBe(GOOD.center)
  })

  it('缺字段/NaN/字符串/center 长度不对 → null', () => {
    expect(sanitizeSite3DView(null)).toBeNull()
    expect(sanitizeSite3DView(undefined)).toBeNull()
    expect(sanitizeSite3DView({ ...GOOD, alpha: undefined })).toBeNull()
    expect(sanitizeSite3DView({ ...GOOD, beta: Number.NaN })).toBeNull()
    expect(sanitizeSite3DView({ ...GOOD, distance: '260' })).toBeNull()
    expect(sanitizeSite3DView({ ...GOOD, orthographicSize: Number.POSITIVE_INFINITY })).toBeNull()
    expect(sanitizeSite3DView({ ...GOOD, center: [1, 2] })).toBeNull()
    expect(sanitizeSite3DView({ ...GOOD, center: [1, 2, Number.NaN] })).toBeNull()
    expect(sanitizeSite3DView({ ...GOOD, center: [1, 2, 3, 4] })).toBeNull()
    const holey = [1, 2, 3] as number[]
    delete holey[1]
    expect(sanitizeSite3DView({ ...GOOD, center: holey })).toBeNull()
    expect(sanitizeSite3DView({ ...GOOD, extra: 'ignored' })).toEqual(GOOD)
  })
})

describe('isSameSite3DView — 「镜头动没动」的判据', () => {
  const base: Site3DView = { alpha: 31.5, beta: -12, distance: 245, orthographicSize: 150, center: [0, 0, 0] }

  it('完全相等 / 浮点微差 → true（单击 tooltip 不该被当成拖动）', () => {
    expect(isSameSite3DView(base, { ...base, center: [...base.center] })).toBe(true)
    expect(isSameSite3DView(base, { ...base, alpha: base.alpha + 0.005 })).toBe(true)
    expect(isSameSite3DView(base, { ...base, center: [0.005, -0.005, 0] })).toBe(true)
  })

  it('任一分量真的变了 → false', () => {
    expect(isSameSite3DView(base, { ...base, alpha: base.alpha + 0.02 })).toBe(false)
    expect(isSameSite3DView(base, { ...base, beta: base.beta - 0.02 })).toBe(false)
    expect(isSameSite3DView(base, { ...base, distance: base.distance + 0.02 })).toBe(false)
    expect(isSameSite3DView(base, { ...base, orthographicSize: base.orthographicSize - 0.02 })).toBe(false)
    expect(isSameSite3DView(base, { ...base, center: [0.02, 0, 0] })).toBe(false)
    expect(isSameSite3DView(base, { ...base, center: [0, -0.02, 0] })).toBe(false)
    expect(isSameSite3DView(base, { ...base, center: [0, 0, 0.02] })).toBe(false)
  })
})

describe('readLiveView', () => {
  it('从 OrbitControl 读实时机位，orthographicSize 减掉 grid3D 的 base 1', () => {
    const v = readLiveView(fakeChart(fakeControl()))!
    expect(v).toEqual({ alpha: 40, beta: -7, distance: 300, orthographicSize: 150, center: [0.5, 1.5, 2.5] })
  })

  it('实例/视图/私有字段缺失或 getter 抛错 → null（不影响出图）', () => {
    expect(readLiveView(null)).toBeNull()
    expect(readLiveView({})).toBeNull()
    expect(readLiveView(fakeChart(null))).toBeNull()
    expect(readLiveView(fakeChart(fakeControl({ getAlpha: () => { throw new Error('disposed') } })))).toBeNull()
    expect(readLiveView(fakeChart(fakeControl({ getOrthographicSize: () => Number.NaN })))).toBeNull()
    expect(readLiveView(fakeChart(fakeControl({ getCenter: () => [0, 0] })))).toBeNull()
  })
})
