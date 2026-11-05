/**
 * T2：`analysis_chart_state` 的 PUT 载荷必须**完整**（specs/2026-11-05 §4.3）。
 *
 * 背景：后端该字段是整份 JSON 替换（apps/accounts/serializers.py，partial=True 只表示
 * 字段可选，不表示 JSON 内部合并）。旧实现 `latest` 只累积本次防抖窗口内的键，
 * 于是「只上报 site3dView」会把账号里的 layout/toggles 冲掉——视角是高频写入，
 * 这条窄缝会被放大成「记住视角 = 布局丢光」。
 * 判据：任何单键上报，PUT 的 analysis_chart_state 仍是**已知的 layout+toggles + 新键**；
 * 且「加载完成前就排队」与「PUT 失败」两条现实路径都不许退化成单键载荷。
 */
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const holder = vi.hoisted(() => {
  // node 环境没有 document，而 useChartMemory 只在导入时按 `typeof document` 注册
  // pagehide ⇒ 桩必须早于模块求值（vi.hoisted 先于 import 执行），否则那条通道
  // 在本文件里根本不存在，pagehide 用例会变成空跑。
  const listeners: Record<string, () => void> = {}
  ;(globalThis as any).document = {
    // Vue runtime-dom 导入时就会 doc.createElement('template')，只桩 addEventListener 会崩
    createElement: () => ({}),
    addEventListener: (type: string, fn: () => void) => {
      listeners[type] = fn
    },
  }
  return { raw: null as any, saves: [] as any[], failNext: false, listeners }
})

vi.mock('../../src/stores/userSettings', () => ({
  useUserSettingsStore: () => ({
    get raw() { return holder.raw },
    ensure: () => Promise.resolve(),
    save: (p: any) => {
      holder.saves.push(p)
      if (holder.failNext) {
        holder.failNext = false
        return Promise.reject(new Error('network down'))
      }
      return Promise.resolve()
    },
    saveKeepalive: (p: any) => { holder.saves.push(p) },
  }),
}))

// 本文件不量本机布局落盘；不 mock 会撞上真 safeStorage 的 DOMException 噪声
vi.mock('../../src/utils/safeStorage', () => ({
  safeGetItem: () => null,
  safeSetItem: () => {},
  safeRemoveItem: () => {},
}))

import {
  clearChartMemoryState,
  getCachedChartState,
  loadChartMemory,
  resetChartMemoryCache,
  saveChartState,
  setChartMemoryEnabled,
} from '../../src/composables/useChartMemory'
import type { Site3DView } from '../../src/pages/analysis/composables/site3dView'
import type { DockLayout } from '../../src/pages/analysis/composables/useChartDock'

// 账号里存的是带 v 的存档形状（isValidLayout 要求 v===1）；DockLayout 类型本身不含 v
const LAYOUT = {
  v: 1,
  rows: [['hist'], ['box', 'site3d']],
  rowPcts: [70, 30],
  colPcts: [[100], [50, 50]],
  bodyH: 900,
} as unknown as DockLayout
const TOGGLES = { hist: true, serial: false, qq: false, box: true, site3d: true }
const VIEW: Site3DView = { alpha: 33, beta: -8, distance: 260, orthographicSize: 149, center: [0, 0, 0] }

beforeEach(() => {
  resetChartMemoryCache()
  holder.saves = []
  holder.failNext = false
  vi.useFakeTimers()
  holder.raw = {
    analysis_chart_memory: true,
    analysis_chart_state: { layout: LAYOUT, toggles: TOGGLES, site3dView: VIEW },
  }
})

afterEach(() => {
  vi.useRealTimers()
  resetChartMemoryCache()
})

afterAll(() => {
  // 文件内隔离之外再收一次，别把只有 createElement 的假 document 留给后续用例
  delete (globalThis as any).document
})

describe('analysis_chart_state 的读取与整体性', () => {
  it('解析出 site3dView，并可从同步入口读到同一份快照', async () => {
    const r = await loadChartMemory()
    expect(r.state.site3dView).toEqual(VIEW)
    expect(getCachedChartState()).toEqual({ layout: LAYOUT, toggles: TOGGLES, site3dView: VIEW })
  })

  it('site3dView 坏值 → null，其余字段照常', async () => {
    holder.raw.analysis_chart_state.site3dView = { alpha: Number.NaN }
    const r = await loadChartMemory()
    expect(r.state.site3dView).toBeNull()
    expect(r.state.layout).toEqual(LAYOUT)
    expect(r.state.toggles).toEqual(TOGGLES)
  })

  it('记忆开关关闭时同步快照为 null（重挂载的图回默认机位，不套旧账号态）', async () => {
    holder.raw.analysis_chart_memory = false
    const r = await loadChartMemory()
    expect(r.memoryEnabled).toBe(false)
    expect(getCachedChartState()).toBeNull()
  })

  it('视角单键上报：PUT 仍携带加载时的 layout+toggles（防整份冲洗）', async () => {
    await loadChartMemory()
    const next = { ...VIEW, alpha: 40 }
    saveChartState({ site3dView: next })
    vi.advanceTimersByTime(800)
    expect(holder.saves).toHaveLength(1)
    expect(holder.saves[0]).toEqual({
      analysis_chart_state: { layout: LAYOUT, toggles: TOGGLES, site3dView: next },
    })
  })

  it('视角上报后同步快照立即更新（dock 勾掉再勾回不闪回旧机位）', async () => {
    await loadChartMemory()
    const next = { ...VIEW, alpha: 44 }
    saveChartState({ site3dView: next })
    expect(getCachedChartState()?.site3dView).toEqual(next)
  })

  it('布局上报同样立即反映到同步快照（快照是整份记忆，不是只有视角）', async () => {
    await loadChartMemory()
    const layout = { ...LAYOUT, bodyH: 700 }
    saveChartState({ layout })
    expect(getCachedChartState()?.layout).toEqual(layout)
  })

  it('加载完成前的上报：加载后冲刷仍带 layout+toggles', async () => {
    saveChartState({ site3dView: { ...VIEW, alpha: 45 } }) // memoryEnabled 仍为 null
    expect(holder.saves).toHaveLength(0)
    await loadChartMemory()
    vi.advanceTimersByTime(800)
    expect(holder.saves).toHaveLength(1)
    expect(holder.saves[0]).toEqual({
      analysis_chart_state: { layout: LAYOUT, toggles: TOGGLES, site3dView: { ...VIEW, alpha: 45 } },
    })
    // 载荷合并的同时快照也要跟上：否则重挂载会短暂读回加载时的旧视角
    expect(getCachedChartState()?.site3dView).toEqual({ ...VIEW, alpha: 45 })
  })

  it('PUT 失败不丢基底：下一次冲刷仍是完整载荷', async () => {
    await loadChartMemory()
    holder.failNext = true
    saveChartState({ site3dView: { ...VIEW, alpha: 41 } })
    vi.advanceTimersByTime(800)
    saveChartState({ site3dView: { ...VIEW, alpha: 42 } })
    vi.advanceTimersByTime(800)
    expect(holder.saves).toHaveLength(2)
    expect(holder.saves[1]).toEqual({
      analysis_chart_state: { layout: LAYOUT, toggles: TOGGLES, site3dView: { ...VIEW, alpha: 42 } },
    })
  })

  it('pagehide 抢在防抖前冲刷：加载前排队的改动 + 基底一起发', async () => {
    // 加载前排队的 latest 只有视角；加载成功只补 knownState 并排防抖，不回填 latest。
    // 用户此刻关页 ⇒ pagehide 必须自己并基底，否则 keepalive 也是整份替换、布局/勾选被冲掉。
    saveChartState({ site3dView: { ...VIEW, beta: -12 } })
    await loadChartMemory()
    holder.listeners.pagehide?.()
    expect(holder.saves).toHaveLength(1)
    expect(holder.saves[0]).toEqual({
      analysis_chart_state: { layout: LAYOUT, toggles: TOGGLES, site3dView: { ...VIEW, beta: -12 } },
    })
    vi.advanceTimersByTime(800) // 处理器已清掉防抖计时器，不许再发第二次
    expect(holder.saves).toHaveLength(1)
  })

  it('会话内重新开启记忆：丢弃关闭/失败时的解析 memo，下次 load 重取', async () => {
    holder.raw.analysis_chart_memory = false
    await loadChartMemory()
    expect(getCachedChartState()).toBeNull()
    holder.raw = {
      analysis_chart_memory: true,
      analysis_chart_state: { layout: LAYOUT, toggles: TOGGLES, site3dView: VIEW },
    }
    setChartMemoryEnabled(true)
    const r = await loadChartMemory()
    expect(r.memoryEnabled).toBe(true)
    expect(getCachedChartState()?.site3dView).toEqual(VIEW)
  })

  it('拉取失败（raw=null）：快照清空、开关记为未知，不把旧快照当当前态', async () => {
    await loadChartMemory()
    resetChartMemoryCache()
    holder.raw = null
    const r = await loadChartMemory()
    expect(r.fetchFailed).toBe(true)
    expect(r.memoryEnabled).toBeNull()
    expect(getCachedChartState()).toBeNull()
  })

  it('清空会作废解析 memo：下次 load 重新读服务端而不是回放旧结果', async () => {
    await loadChartMemory()
    await clearChartMemoryState()
    expect(getCachedChartState()).toBeNull()
    const fresh = { ...VIEW, alpha: 50 }
    holder.raw = { analysis_chart_memory: true, analysis_chart_state: { layout: LAYOUT, toggles: TOGGLES, site3dView: fresh } }
    const r = await loadChartMemory()
    expect(r.state.site3dView).toEqual(fresh)
    expect(getCachedChartState()?.site3dView).toEqual(fresh)
  })
})
