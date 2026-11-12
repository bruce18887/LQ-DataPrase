/**
 * 子集面板单例生命周期（T2，node 环境）。
 *
 * ① detached effectScope 回归：create() 里的裸 watch 会绑在首个调用
 *    useSubsetPanels() 的组件 effect scope 上；登出 / 401 forceLogout 卸载
 *    MainLayout → SingleParamTab，scope 停掉 watch 随之永久停止；模块单例不重建、
 *    resetSubsetPanels() 只清面板不重臂 watch ⇒ 重新登录后切文件不再清面板
 *    （R5 跨上下文泄漏）。切文件清空由用例 1 钉；切参数语义反转后（2026-11-12
 *    子集跟进计划），「watch 仍活着」的承重断言是用例 2 的 serials 跟随重查——
 *    watch 若随组件 scope 死掉，param 不更新、请求不发，必红。
 * ② 切参数不再清空（本计划对 R5 的显式例外）：serials 面板用新参数重查，
 *    value_range 面板（后端没回 serials）冻结在原参数原结果。
 * ③ epoch 双 load 竞态（T2-M2 补强）：同一面板连发 load，过期响应/过期拒绝
 *    都不得碰 result/error/loading；loading 由最新一次 load 接管（旧 finally
 *    不得提前收起骨架）。mock api.post 返回受控 deferred，人为交错落地顺序。
 *
 * 单例约束：useSubsetPanels 是模块单例，watch 绑定首次调用时活跃的 store 实例 ⇒
 * 全文件共享同一份 pinia（模块顶层创建），勿逐用例 createPinia()，否则第二条用例
 * 拿到的 store 不再是 watch 订阅的那份。面板直接推 panels.value，不调 create()
 * （那会发真实 histogram 请求）；用例 2 的重查走 watch→load 通路，api.post 已 mock。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { effectScope, nextTick } from 'vue'

// api 仅被 load 消费；mock 切断真实 api 模块的 import 期副作用链（axios 拦截器 /
// element-plus / auth store），与 userSettings.spec.ts mock api/auth 同形。
const post = vi.fn()
vi.mock('../../src/api', () => ({ default: { post: (...args: any[]) => post(...args) } }))

import { useSingleTabStore } from '../../src/stores/analysisTabs'
import { useSubsetPanels, type SubsetPanel } from '../../src/pages/analysis/composables/useSubsetPanels'

const pinia = createPinia()

function fakePanel(): SubsetPanel {
  return {
    id: 1, param: 'P1',
    selection: { kind: 'value_range', lo: 0, hi: 1 },
    result: null, loading: false, error: null, epoch: 0,
  }
}

describe('useSubsetPanels 单例生命周期（detached effectScope）', () => {
  beforeEach(() => {
    setActivePinia(pinia)
    post.mockReset()
  })

  it('组件 scope.stop() 后切 fileId 仍清面板（登出/卸载回归）', async () => {
    const store = useSingleTabStore()
    store.fileId = 1
    store.selectedParam = 'P1'

    // 模拟组件 setup：首次调用在组件作用域内创建单例
    const scope = effectScope()
    const api = scope.run(() => useSubsetPanels())!
    api.panels.value = [fakePanel()]
    scope.stop()  // 模拟 MainLayout / SingleParamTab 卸载

    store.fileId = 2
    await nextTick()
    expect(api.panels.value.length, 'detached watch 必须在组件卸载后仍清面板').toBe(0)
  })

  it('组件 scope.stop() 后切 selectedParam：面板不清空，serials 跟随重查 / value_range 冻结', async () => {
    const store = useSingleTabStore()
    store.fileId = 1  // 从上一条用例的 2 复位
    store.selectedParam = 'P1'
    await nextTick()  // 先冲掉 fileId 复位触发的清空，免得它掩盖下面的参数断言

    // 再模拟一次挂载/卸载（重新登录后再次卸载，watch 仍不得死）
    const scope = effectScope()
    const api = scope.run(() => useSubsetPanels())!
    const serialsPanel: SubsetPanel = {
      id: 1, param: 'P1',
      selection: { kind: 'serials', serials: [4, 5, 6], serial_col: 'Serial_No' },
      result: null, loading: false, error: null, epoch: 0,
    }
    const rangePanel: SubsetPanel = { ...fakePanel(), id: 2 }
    api.panels.value = [serialsPanel, rangePanel]
    scope.stop()

    post.mockResolvedValue({ data: { results: { P2: { total_count: 3 } } } })
    store.selectedParam = 'P2'
    await nextTick()

    // 切参数不再清空（本计划对 R5 的显式例外）
    expect(api.panels.value.length, '切参数不得清空面板').toBe(2)
    // detached watch 仍活着的承重断言：serials 面板跟随新参数并重查
    // （watch 若随组件 scope 死掉，param 不更新、请求不发，这两条必红）
    expect(serialsPanel.param).toBe('P2')
    expect(post).toHaveBeenCalledTimes(1)
    const body = post.mock.calls[0][1]
    expect(body.params).toEqual(['P2'])
    expect(body.selection).toEqual({ kind: 'serials', serials: [4, 5, 6], serial_col: 'Serial_No' })
    // value_range 面板冻结：原参数、原选区、不发请求
    expect(rangePanel.param).toBe('P1')
    expect(rangePanel.selection).toEqual({ kind: 'value_range', lo: 0, hi: 1 })

    // 重查结果落地（epoch 匹配，loading 由本次 load 收尾）
    await new Promise((r) => setTimeout(r, 0))
    expect(serialsPanel.result).toEqual({ total_count: 3 })
    expect(serialsPanel.loading).toBe(false)
    expect(serialsPanel.error).toBeNull()
  })

  it('epoch 守卫：交错双 load，过期响应与过期拒绝都不得碰 result/error/loading', async () => {
    const store = useSingleTabStore()
    const api = useSubsetPanels()
    // 先清面板再复位参数：否则 selectedParam 变化会对上一条用例遗留的
    // serials 面板触发重查，污染 post 计数。
    api.clearAll()
    store.fileId = 1
    store.selectedParam = 'P1'
    await nextTick()

    // 受控 deferred：resolve/reject 时机由用例掌握，模拟响应乱序到达
    function deferred() {
      let resolve!: (v: any) => void
      let reject!: (e: any) => void
      const promise = new Promise<any>((res, rej) => { resolve = res; reject = rej })
      return { promise, resolve, reject }
    }
    const flush = () => new Promise((r) => setTimeout(r, 0))

    // ① 过期响应：create(load#1) + retry(load#2) 连发，#2 先落地、#1 晚到
    const d1 = deferred()
    const d2 = deferred()
    post.mockImplementationOnce(() => d1.promise).mockImplementationOnce(() => d2.promise)
    api.create({ kind: 'serials', serials: [4, 5, 6], serial_col: 'Serial_No' })
    const panel = api.panels.value[0]
    api.retry(panel.id)
    expect(panel.loading).toBe(true)
    expect(post).toHaveBeenCalledTimes(2)

    d2.resolve({ data: { results: { P1: { total_count: 3 } } } })
    await flush()
    expect(panel.result).toEqual({ total_count: 3 })
    expect(panel.loading).toBe(false)
    expect(panel.error).toBeNull()

    // #1 带着不同结果晚到：epoch 不匹配，result/loading/error 一律不得被碰
    d1.resolve({ data: { results: { P1: { total_count: 999 } } } })
    await flush()
    expect(panel.result, '过期响应不得覆盖新结果').toEqual({ total_count: 3 })
    expect(panel.loading, '过期响应的 finally 不得改 loading').toBe(false)
    expect(panel.error).toBeNull()

    // ② 过期拒绝：retry×2 连发（#3/#4），#3 在 #4 仍 pending 时拒绝——
    //    不得写 error，也不得提前收起骨架（loading 归最新 load 所有）
    const d3 = deferred()
    const d4 = deferred()
    post.mockImplementationOnce(() => d3.promise).mockImplementationOnce(() => d4.promise)
    api.retry(panel.id)
    api.retry(panel.id)
    expect(panel.loading).toBe(true)
    d3.reject(new Error('stale boom'))
    await flush()
    expect(panel.error, '过期拒绝不得写 error').toBeNull()
    expect(panel.loading, '过期拒绝不得提前收起骨架').toBe(true)
    expect(panel.result, '过期拒绝不得碰 result').toEqual({ total_count: 3 })

    // #4 正常落地：最新 load 收尾
    d4.resolve({ data: { results: { P1: { total_count: 5 } } } })
    await flush()
    expect(panel.result).toEqual({ total_count: 5 })
    expect(panel.loading).toBe(false)
    expect(panel.error).toBeNull()
    expect(post).toHaveBeenCalledTimes(4)
  })
})
