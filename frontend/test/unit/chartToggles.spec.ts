/**
 * T2：五图勾选的两条纯逻辑 + composable 接线（specs/2026-11-04 §4/§10；
 * 实现 `pages/analysis/composables/useChartToggles.ts`）。
 *
 * 为什么要有这份：`onDockClose` 的五个分支此前没有任何 T2 承重（只在组件层存在，
 * 删掉 site3d 那一支也没有 T2 会变红），抽成 `closeChartIn` / `activeChartKeysOf`
 * 两个纯函数后，五个键可以在这里逐一钉住；下半段再调一次真 composable，保证
 * `closeChart` 确实把每个键接到了自己的 ref 上（只测纯函数会放过「composable
 * 里接错键」这类错）。
 *
 * 记忆读写在 node 里不可达（store 会发 GET），所以 mock 掉 useChartMemory：
 * 「套用与上报互斥」两条语义（applying 期间不回写、用户在返回前动过就不套用）
 * 在这里用可控 promise 按下；存档解析口径由 chartLayout.spec.ts 承担。
 */
import { describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

const memory = vi.hoisted(() => ({
  enabled: false as boolean | null,
  toggles: null as any,
  saves: [] as any[],
  /** true = loadChartMemory 挂起，由用例手动 settle（量 touched 守卫） */
  hold: false,
  pending: [] as Array<() => void>,
}))

vi.mock('../../src/composables/useChartMemory', () => ({
  loadChartMemory: () => new Promise((resolve) => {
    const settle = () => resolve({
      memoryEnabled: memory.enabled,
      fetchFailed: false,
      state: { layout: null, toggles: memory.toggles },
    })
    if (memory.hold) memory.pending.push(settle)
    else settle()
  }),
  saveChartState: (patch: unknown) => { memory.saves.push(patch) },
}))

import {
  TOGGLE_KEYS,
  activeChartKeysOf,
  closeChartIn,
  defaultToggles,
  useChartToggles,
} from '../../src/pages/analysis/composables/useChartToggles'
import type { ChartToggles } from '../../src/composables/useChartMemory'
import type { ChartKey } from '../../src/pages/analysis/composables/useChartDock'

const ALL_ON: ChartToggles = { hist: true, serial: true, qq: true, box: true, site3d: true }
const ALL_OFF: ChartToggles = { hist: false, serial: false, qq: false, box: false, site3d: false }

/** composable 返回的五个勾选 ref（键名与 ChartKey 一一对应） */
function toggleRefs(t: ReturnType<typeof useChartToggles>): Record<ChartKey, { value: boolean }> {
  return {
    hist: t.showHistogram,
    serial: t.showSerial,
    qq: t.showQQPlot,
    box: t.showBoxPlot,
    site3d: t.showSite3D,
  }
}

describe('useChartToggles：记忆套用与上报互斥（搬家后语义不变）', () => {
  it('memoryEnabled=true：套用五个值，套用本身不回写 saveChartState；其后用户改动才上报', async () => {
    memory.enabled = true
    memory.toggles = { hist: false, serial: true, qq: true, box: false, site3d: true }
    memory.saves.length = 0
    const t = useChartToggles()
    await Promise.resolve() // 让 loadChartMemory().then 跑起来
    await nextTick() // applying 在 nextTick 里复位
    expect(t.showHistogram.value).toBe(false)
    expect(t.showSerial.value).toBe(true)
    expect(t.showQQPlot.value).toBe(true)
    expect(t.showBoxPlot.value).toBe(false)
    expect(t.showSite3D.value).toBe(true)
    // 套用期间 watcher 若回写，会把「恢复」当「用户改动」再存一遍
    expect(memory.saves).toEqual([])
    t.showBoxPlot.value = true
    await nextTick()
    expect(memory.saves).toEqual([
      { toggles: { hist: false, serial: true, qq: true, box: true, site3d: true } },
    ])
  })

  it('用户在记忆返回前已动过勾选 ⇒ 不套用（touched 守卫）', async () => {
    memory.hold = true
    memory.enabled = true
    memory.toggles = { ...ALL_ON }
    const t = useChartToggles()
    t.showQQPlot.value = true // 用户在 GET 返回前点了勾选
    memory.hold = false
    for (const settle of memory.pending.splice(0)) settle()
    await nextTick()
    // 直方图保持默认 true、序列/3D 保持默认 false —— 服务端那份 ALL_ON 没盖下来
    expect(t.showHistogram.value).toBe(true)
    expect(t.showSerial.value).toBe(false)
    expect(t.showSite3D.value).toBe(false)
  })

  it('memoryEnabled=false：即使服务端有 toggles 也不套用（只在明确开启时生效）', async () => {
    memory.enabled = false
    memory.toggles = { ...ALL_ON }
    const t = useChartToggles()
    await Promise.resolve()
    await nextTick()
    expect(t.showHistogram.value).toBe(true)
    expect(t.showSerial.value).toBe(false)
    expect(t.showQQPlot.value).toBe(false)
    expect(t.showBoxPlot.value).toBe(false)
    expect(t.showSite3D.value).toBe(false)
  })
})

describe('closeChartIn：关闭某图只清它自己的勾选', () => {
  for (const key of TOGGLE_KEYS) {
    it(`关闭 ${key}：只有 ${key} 变 false，其余四个保持 true`, () => {
      const before: ChartToggles = { ...ALL_ON }
      const after = closeChartIn(before, key)
      expect(after[key]).toBe(false)
      for (const other of TOGGLE_KEYS) {
        if (other !== key) expect(after[other], `关闭 ${key} 时误改了 ${other}`).toBe(true)
      }
      // 返回新对象、不改入参：composable 的 snapshot() 每次新建，但纯函数别养成原地改的习惯
      expect(before).toEqual(ALL_ON)
    })
  }

  it('关闭本来就关着的图：仍为 false，其余原值一格不动', () => {
    const before: ChartToggles = { ...ALL_OFF, hist: true, box: true }
    expect(closeChartIn(before, 'site3d')).toEqual(before)
  })
})

describe('activeChartKeysOf：勾选集 → dock 的 active keys（顺序即 reconcile 依据）', () => {
  it('全开时按 hist/serial/qq/box/site3d 排（ChartDock 初始布局按这个顺序分块）', () => {
    expect(activeChartKeysOf(ALL_ON)).toEqual(['hist', 'serial', 'qq', 'box', 'site3d'])
  })

  it('顺序不随对象键的插入顺序变化（按 TOGGLE_KEYS 过滤，不是 Object.keys）', () => {
    const reversed = { site3d: true, box: true, qq: true, serial: true, hist: true }
    expect(activeChartKeysOf(reversed)).toEqual(['hist', 'serial', 'qq', 'box', 'site3d'])
  })

  it('只勾部分图时保持全局顺序，不按勾选先后追加', () => {
    expect(activeChartKeysOf({ hist: false, serial: true, qq: false, box: true, site3d: true }))
      .toEqual(['serial', 'box', 'site3d'])
  })

  it('全关 = 空数组（父组件据此走「未选择任何图表」占位）', () => {
    expect(activeChartKeysOf(ALL_OFF)).toEqual([])
  })

  it('TOGGLE_KEYS 就是五个键且顺序固定', () => {
    expect([...TOGGLE_KEYS]).toEqual(['hist', 'serial', 'qq', 'box', 'site3d'])
  })

  it('默认勾选：只有直方图开（新图默认不勾，别把 dock 从 4 格挤成 5 格）', () => {
    expect(defaultToggles()).toEqual({ hist: true, serial: false, qq: false, box: false, site3d: false })
  })
})

describe('useChartToggles：closeChart 与 activeChartKeys 确实接在五个 ref 上', () => {
  for (const key of TOGGLE_KEYS) {
    it(`closeChart('${key}')：该 ref 变 false，其余四个不动`, () => {
      const t = useChartToggles()
      const refs = toggleRefs(t)
      for (const k of TOGGLE_KEYS) refs[k].value = true
      t.closeChart(key)
      expect(refs[key].value).toBe(false)
      for (const other of TOGGLE_KEYS) {
        if (other !== key) expect(refs[other].value, `closeChart('${key}') 误改了 ${other}`).toBe(true)
      }
    })
  }

  it('activeChartKeys 跟随勾选变化且保持全局顺序', () => {
    const t = useChartToggles()
    const refs = toggleRefs(t)
    // 默认：只有 hist
    expect(t.activeChartKeys.value).toEqual(['hist'])
    refs.box.value = true
    refs.site3d.value = true
    expect(t.activeChartKeys.value).toEqual(['hist', 'box', 'site3d'])
    refs.hist.value = false
    expect(t.activeChartKeys.value).toEqual(['box', 'site3d'])
    expect(t.anyChartVisible.value).toBe(true)
    refs.box.value = false
    refs.site3d.value = false
    expect(t.activeChartKeys.value).toEqual([])
    expect(t.anyChartVisible.value).toBe(false)
  })
})
