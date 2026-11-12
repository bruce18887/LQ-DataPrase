/**
 * serial 高亮 = brush ∪ 子集面板（T2，node 环境）。
 *
 * 承重判据（2026-11-12 跟进：子图展示即高亮其芯片，关掉子图才取消）：
 *  ① 子集面板（selection 固化为 serials）打开即贡献高亮，serial 图后开启也可见；
 *  ② 右键「清除高亮」(clear) 只清 brush，子集贡献仍在；
 *  ③ 关闭子集面板（clearAll/remove）后子集贡献消失，无 brush 时高亮归零；
 *  ④ 并集去重保序；value_range（未固化）面板不贡献。
 *
 * 单例约束同 subsetPanels.spec：全文件共享一份 pinia；面板直接推 panels.value，
 * 不调 create()（避免真实 histogram 请求）；api 已 mock 切断 import 副作用链。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { nextTick } from 'vue'

const post = vi.fn()
vi.mock('../../src/api', () => ({ default: { post: (...args: any[]) => post(...args) } }))

import { useSubsetPanels, type SubsetPanel } from '../../src/pages/analysis/composables/useSubsetPanels'
import { useSerialHighlight } from '../../src/pages/analysis/composables/useSerialHighlight'

const pinia = createPinia()

function serialsPanel(id: number, serials: (number | string)[]): SubsetPanel {
  return {
    id, param: 'P1',
    selection: { kind: 'serials', serials, serial_col: 'Serial_No' },
    result: null, loading: false, error: null, epoch: 0,
  }
}

describe('useSerialHighlight — brush ∪ 子集', () => {
  beforeEach(() => {
    setActivePinia(pinia)
    post.mockReset()
  })

  it('brush 单独贡献；clear 清零', () => {
    const hl = useSerialHighlight()
    const panels = useSubsetPanels()
    panels.clearAll()
    hl.clear()
    hl.set({ kind: 'serials', serials: [1, 2], serial_col: 'Serial_No' })
    expect(hl.serials.value).toEqual([1, 2])
    hl.clear()
    expect(hl.serials.value).toEqual([])
  })

  it('子集打开即贡献；clear(brush) 后子集仍在；关子集才归零', async () => {
    const hl = useSerialHighlight()
    const panels = useSubsetPanels()
    panels.clearAll()
    hl.clear()
    await nextTick()

    panels.panels.value = [serialsPanel(1, [4, 5, 6])]
    await nextTick()
    expect(hl.serials.value, '子图展示即高亮其芯片').toEqual([4, 5, 6])

    // 右键清除高亮只清 brush，子集贡献保持
    hl.clear()
    expect(hl.serials.value).toEqual([4, 5, 6])

    // 关掉子图才取消
    panels.clearAll()
    await nextTick()
    expect(hl.serials.value).toEqual([])
  })

  it('并集去重保序（brush 在前）；value_range 不贡献', async () => {
    const hl = useSerialHighlight()
    const panels = useSubsetPanels()
    panels.clearAll()
    hl.clear()
    await nextTick()

    hl.set({ kind: 'serials', serials: [1, 2], serial_col: 'Serial_No' })
    panels.panels.value = [
      serialsPanel(1, [2, 3]),
      { ...serialsPanel(2, []), selection: { kind: 'value_range', lo: 0, hi: 1 } },
    ]
    await nextTick()
    expect(hl.serials.value).toEqual([1, 2, 3])
  })
})