/**
 * Task 5 审查修复 —— 子集面板单例的「清空 watch」必须在组件卸载后存活（T2，node 环境）。
 *
 * bug 形状：create() 里的裸 watch 绑在首个调用 useSubsetPanels() 的组件 effect scope 上；
 * 登出 / 401 forceLogout 卸载 MainLayout → SingleParamTab，scope 停掉 watch 随之永久停止；
 * 模块单例不重建、resetSubsetPanels() 只清面板不重臂 watch ⇒ 重新登录后切文件/参数不再
 * 清面板（R5 跨上下文泄漏）。修复：effectScope(true) detached scope 承载 watch。
 * 本文件钉「scope.stop() 之后 watch 仍触发」——缺修复时两条用例必红。
 *
 * 单例约束：useSubsetPanels 是模块单例，watch 绑定首次调用时活跃的 store 实例 ⇒
 * 全文件共享同一份 pinia（模块顶层创建），勿逐用例 createPinia()，否则第二条用例
 * 拿到的 store 不再是 watch 订阅的那份。面板直接推 panels.value，不调 create()
 * （那会发真实 histogram 请求）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { effectScope, nextTick } from 'vue'

// api 仅被 createPanel→load 消费，本文件从不调 create()；mock 只为切断真实 api
// 模块的 import 期副作用链（axios 拦截器 / element-plus / auth store），
// 与 userSettings.spec.ts mock api/auth 同形。
vi.mock('../../src/api', () => ({ default: { post: vi.fn() } }))

import { useSingleTabStore } from '../../src/stores/analysisTabs'
import { useSubsetPanels, type SubsetPanel } from '../../src/pages/analysis/composables/useSubsetPanels'

const pinia = createPinia()

function fakePanel(): SubsetPanel {
  return {
    id: 1, param: 'P1',
    selection: { kind: 'value_range', lo: 0, hi: 1 },
    result: null, loading: false, error: null,
  }
}

describe('useSubsetPanels 单例清空 watch（detached effectScope）', () => {
  beforeEach(() => {
    setActivePinia(pinia)
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

  it('组件 scope.stop() 后切 selectedParam 同样清面板', async () => {
    const store = useSingleTabStore()
    store.fileId = 1  // 从上一条用例的 2 复位
    store.selectedParam = 'P1'
    await nextTick()  // 先冲掉 fileId 复位触发的清空，免得它掩盖下面的参数断言

    // 再模拟一次挂载/卸载（重新登录后再次卸载，watch 仍不得死）
    const scope = effectScope()
    const api = scope.run(() => useSubsetPanels())!
    api.panels.value = [fakePanel()]
    scope.stop()

    store.selectedParam = 'P2'
    await nextTick()
    expect(api.panels.value.length, '切参数同样必须清面板').toBe(0)
  })
})