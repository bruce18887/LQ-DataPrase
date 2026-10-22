/**
 * Task 6a — /auth/settings/ 唯一持有者的行为契约（T2，node 环境，mock 掉 api 模块）。
 *
 * 承重四条（缺任何一条都不算数）：
 * ① N 个并发 ensure() 只发 1 次 GET（单飞）——今天 6 个模块各自单飞，一次导航实测 2–6 次；
 * ② 已取过后不再发（幂等）；
 * ③ **GET 失败后不再重试**（对照组 = 防请求风暴回归：今天 echarts-theme.ts:44-51 的降级口径）；
 * ④ save 只 PUT 脏字段（后端 serializer partial=True，apps/accounts/views.py:218-225）。
 * 另加 reset（登录/登出串账号防线）与 patch 的「等同已取过」语义（旧 setChartRenderer
 * 会连带把 _rendererFetched 置 true）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

const getSettings = vi.fn()
const updateSettings = vi.fn()
const updateSettingsKeepalive = vi.fn()
vi.mock('../../src/api/auth', () => ({
  authApi: {
    getSettings: (...a: any[]) => getSettings(...a),
    updateSettings: (...a: any[]) => updateSettings(...a),
    updateSettingsKeepalive: (...a: any[]) => updateSettingsKeepalive(...a),
  },
}))

import { useUserSettingsStore } from '../../src/stores/userSettings'

describe('userSettings store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getSettings.mockReset()
    updateSettings.mockReset()
    updateSettingsKeepalive.mockReset()
  })

  it('并发 ensure 只发一次 GET（单飞）', async () => {
    getSettings.mockResolvedValue({ data: { page_size: 100 } })
    const s = useUserSettingsStore()
    await Promise.all([s.ensure(), s.ensure(), s.ensure()])
    expect(getSettings).toHaveBeenCalledTimes(1)
  })

  it('已取过后再次 ensure 不再发请求', async () => {
    getSettings.mockResolvedValue({ data: { page_size: 100 } })
    const s = useUserSettingsStore()
    await s.ensure()
    await s.ensure()
    expect(getSettings).toHaveBeenCalledTimes(1)
    expect(s.raw).toEqual({ page_size: 100 })
  })

  it('GET 失败后 ensure 不再重试（对照组：防请求风暴回归）', async () => {
    getSettings.mockRejectedValue(new Error('boom'))
    const s = useUserSettingsStore()
    await s.ensure()
    await s.ensure()
    expect(getSettings).toHaveBeenCalledTimes(1)
    expect(s.raw).toBeNull()
  })

  it('reset 后 ensure 会重新发一次（登录/登出串账号防线）', async () => {
    getSettings.mockResolvedValue({ data: { page_size: 100 } })
    const s = useUserSettingsStore()
    await s.ensure()
    s.reset()
    await s.ensure()
    expect(getSettings).toHaveBeenCalledTimes(2)
  })

  it('save 只 PUT 脏字段，不发全量', async () => {
    getSettings.mockResolvedValue({ data: { page_size: 100, chart_renderer: 'canvas' } })
    updateSettings.mockResolvedValue({ data: { page_size: 200, chart_renderer: 'canvas' } })
    const s = useUserSettingsStore()
    await s.ensure()
    await s.save({ page_size: 200 })
    expect(updateSettings).toHaveBeenCalledTimes(1)
    expect(updateSettings.mock.calls[0][0]).toEqual({ page_size: 200 })
    // 响应体整份替换 raw（不是 merge）：服务端才是事实来源
    expect(s.raw).toEqual({ page_size: 200, chart_renderer: 'canvas' })
  })

  it('patch 后 ensure 不再发请求（等同旧 setChartRenderer 标记已取过）', async () => {
    const s = useUserSettingsStore()
    s.patch({ page_size: 200 })
    await s.ensure()
    expect(getSettings).toHaveBeenCalledTimes(0)
    expect(s.raw).toEqual({ page_size: 200 })
  })

  it('saveKeepalive 走 pagehide 通道且本地即时生效（不发 updateSettings）', async () => {
    const s = useUserSettingsStore()
    s.saveKeepalive({ analysis_chart_memory: false })
    expect(updateSettingsKeepalive).toHaveBeenCalledTimes(1)
    expect(updateSettingsKeepalive.mock.calls[0][0]).toEqual({ analysis_chart_memory: false })
    expect(updateSettings).toHaveBeenCalledTimes(0)
    expect(s.raw).toEqual({ analysis_chart_memory: false })
    await s.ensure()
    expect(getSettings).toHaveBeenCalledTimes(0)
  })

  /**
   * R24 0a —— 纪元守卫：reset 之后**已经派发出去**的 .then/.finally 不能再写 raw、
   * 不能再把 settled 置真。缺它时的可达链路：axios 401 拦截器 forceLogout（api/index.ts:226
   * 附近）或登录时 stores/auth.ts 的 reset，正好撞在路由守卫那次 GET 在飞上 ⇒ 上一个账号的
   * payload 落进 raw 且 settled=true ⇒ 本页生命周期内不再重取（串账号 + 永久少取）。
   */
  it('reset 期间在飞的 GET 返回后既不写 raw 也不记已结算（R24 纪元守卫）', async () => {
    let resolveFirst!: (v: { data: Record<string, unknown> }) => void
    getSettings.mockImplementation(() => new Promise((r) => { resolveFirst = r }))
    const s = useUserSettingsStore()
    const inFlight = s.ensure()
    await Promise.resolve()  // ensure 内层是 Promise.resolve().then(...)，跑一次才真派发请求
    expect(typeof resolveFirst, 'GET 应已派发（在飞）').toBe('function')
    s.reset()                       // 切账号：纪元 +1
    resolveFirst({ data: { page_size: 999 } })  // 上一账号的响应此刻才回
    await inFlight

    expect(s.raw, '旧 payload 不得写进 raw').toBeNull()
    // settled 没被旧响应置真 ⇒ 下一次 ensure 必须真发一次 GET
    getSettings.mockReset()
    getSettings.mockResolvedValue({ data: { page_size: 100 } })
    await s.ensure()
    expect(getSettings, '旧响应不得抑制新账号的取数').toHaveBeenCalledTimes(1)
    expect(s.raw).toEqual({ page_size: 100 })
  })

  it('在飞 GET 失败后遇到 reset，同样不得把 settled 置真（R24 0a 的 catch/finally 分支）', async () => {
    let rejectFirst!: (e: unknown) => void
    getSettings.mockImplementation(() => new Promise((_r, j) => { rejectFirst = j }))
    const s = useUserSettingsStore()
    const inFlight = s.ensure()
    await Promise.resolve()
    expect(typeof rejectFirst, 'GET 应已派发（在飞）').toBe('function')
    s.reset()
    rejectFirst(new Error('401'))
    await inFlight

    getSettings.mockReset()
    getSettings.mockResolvedValue({ data: { page_size: 100 } })
    await s.ensure()
    expect(getSettings).toHaveBeenCalledTimes(1)
    expect(s.raw).toEqual({ page_size: 100 })
  })

  // R24 0b —— PUT 响应就是那 20 个字段的全量（apps/accounts/views.py:218-225 +
  // serializers.py:95-107），raw 可证明完整，所以 save 之后不该再补一次 GET。
  // 少掉的正是本任务要消灭的「每次导航多一次 GET」里的一次。
  it('save 之后 ensure 不再发 GET（PUT 响应即全量，R24 0b）', async () => {
    getSettings.mockResolvedValue({ data: { page_size: 100 } })
    updateSettings.mockResolvedValue({ data: { page_size: 200, chart_renderer: 'svg' } })
    const s = useUserSettingsStore()
    await s.ensure()
    await s.save({ page_size: 200 })
    expect(getSettings).toHaveBeenCalledTimes(1)
    await s.ensure()
    expect(getSettings, 'save 已把 raw 换成服务端全量，不应再取').toHaveBeenCalledTimes(1)
  })

  it('从未 ensure 过时 save 也记已结算（0b 的另一半：save 单独调用后 ensure 不发 GET）', async () => {
    updateSettings.mockResolvedValue({ data: { page_size: 300 } })
    const s = useUserSettingsStore()
    await s.save({ page_size: 300 })
    await s.ensure()
    expect(getSettings).toHaveBeenCalledTimes(0)
    expect(s.raw).toEqual({ page_size: 300 })
  })

  /**
   * R24 0c —— `ensure()` 里 API 调用**同步抛**（拦截器/构造期异常）不得冒泡：
   * router/index.ts:178 那句 `await ensureChartRenderer()` 外面没有 try/catch，
   * 冒泡出去就是整条导航被中断。用 Promise.resolve().then(() => getSettings()) 包一层。
   */
  it('getSettings 同步抛错时 ensure 只 resolve，不把异常交给路由守卫（R24 0c）', async () => {
    getSettings.mockImplementation(() => { throw new Error('sync boom') })
    const s = useUserSettingsStore()
    await expect(s.ensure()).resolves.toBeUndefined()
    expect(s.raw).toBeNull()
  })
})
