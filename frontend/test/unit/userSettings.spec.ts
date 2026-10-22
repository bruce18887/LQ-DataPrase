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
 *
 * 6b 修复轮再加五条，全部**逐条变异证明**过（去掉对应守卫就红，见 task-6-report.md §13）：
 * 纪元守卫要覆盖三条通道（ensure 的 GET、save 的 PUT、以及 patch/save 作废在飞 GET），
 * 外加陈旧 `.finally` 不得让新 ensure 提前 resolve。
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
   * 不能再把 settled 置真。缺它时的可达链路：axios 401 拦截器 forceLogout（api/index.ts:149，
   * 401 分支调用点 :215/:221）或登录时 stores/auth.ts 的 reset，正好撞在路由守卫那次 GET 在飞上
   * ⇒ 上一个账号的 payload 落进 raw 且 settled=true ⇒ 本页生命周期内不再重取（串账号 + 永久少取）。
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

  /**
   * 修复轮 Important 1 —— `save()` 也纳入纪元守卫（0a 当时只裁了 `ensure()`）。
   * 缺它时的形状：PUT 在飞时切账号（登录 reset / 401 forceLogout，桌面版只换 hash ⇒ 同一文档
   * 同一个 store 实例），旧账号的**全量**响应照样写进 raw 并把 settled 置真
   * ⇒ 新账号整页读上一个账号的设置、且守卫级 ensure() 因 settled 直接早退不再重取。
   */
  it('reset 期间在飞的 PUT 返回后既不写 raw 也不记已结算（Important 1：save 的纪元守卫）', async () => {
    let resolvePut!: (v: { data: Record<string, unknown> }) => void
    updateSettings.mockImplementation(() => new Promise((r) => { resolvePut = r }))
    const s = useUserSettingsStore()
    const inFlight = s.save({ page_size: 999 })
    await Promise.resolve()
    expect(typeof resolvePut, 'PUT 应已派发（在飞）').toBe('function')
    s.reset()
    resolvePut({ data: { page_size: 999, chart_renderer: 'canvas' } })
    await inFlight

    expect(s.raw, '旧账号的 PUT 响应不得写进 raw').toBeNull()
    getSettings.mockResolvedValue({ data: { page_size: 100 } })
    await s.ensure()
    expect(getSettings, '旧 PUT 响应不得把 settled 置真（新账号必须能重取）').toHaveBeenCalledTimes(1)
    expect(s.raw).toEqual({ page_size: 100 })
  })

  /**
   * 修复轮 Important 2 —— 本地写（patch/save）必须作废**更早派发**的那次 GET，
   * 否则旧响应回来时是「整份替换 raw」，把刚写进去的值静默回滚掉（两种结局都坏：
   * ① 落地成功 → 恢复成写之前的服务端快照，整页剩余时间都是旧值；
   * ② 落地失败 → .catch 把 raw 清成 null 而 settled 仍为真 → 每个消费方各自回退默认值且不再重取）。
   * 真实入口：`useChartMemory.ts:102-115` 的模块级 800ms 防抖跨导航存活，能在新一轮守卫 GET
   * 的窗口里 fire（`analysis_chart_state` 走 store.save）。
   */
  it('ensure 在飞时 patch 不被更早派发的 GET 整份回滚（Important 2①）', async () => {
    let resolveGet!: (v: { data: Record<string, unknown> }) => void
    getSettings.mockImplementation(() => new Promise((r) => { resolveGet = r }))
    const s = useUserSettingsStore()
    const inFlight = s.ensure()
    await Promise.resolve()
    s.patch({ analysis_chart_state: { layout: null, toggles: null } })
    resolveGet({ data: { page_size: 100, analysis_chart_state: { stale: true } } })
    await inFlight

    expect(s.raw, '旧 GET 的全量 payload 不得覆盖本地写').toEqual({ analysis_chart_state: { layout: null, toggles: null } })
  })

  it('ensure 在飞时 patch 后那次 GET 失败也不得把 raw 清成 null（Important 2②）', async () => {
    let rejectGet!: (e: unknown) => void
    getSettings.mockImplementation(() => new Promise((_r, j) => { rejectGet = j }))
    const s = useUserSettingsStore()
    const inFlight = s.ensure()
    await Promise.resolve()
    s.patch({ page_size: 200 })
    rejectGet(new Error('boom'))
    await inFlight

    expect(s.raw, '失败续体不得清 raw —— 清了就是全页静默回退默认值').toEqual({ page_size: 200 })
    await s.ensure()
    expect(getSettings, 'patch 仍算已取过（口径未放宽）').toHaveBeenCalledTimes(1)
  })

  it('ensure 在飞时 save 的 PUT 响应不被更早派发的 GET 换回去（Important 2 的 save 侧）', async () => {
    let resolveGet!: (v: { data: Record<string, unknown> }) => void
    getSettings.mockImplementation(() => new Promise((r) => { resolveGet = r }))
    updateSettings.mockResolvedValue({ data: { page_size: 200, chart_renderer: 'svg' } })
    const s = useUserSettingsStore()
    const get = s.ensure()
    await Promise.resolve()
    await s.save({ page_size: 200 })
    resolveGet({ data: { page_size: 100, chart_renderer: 'canvas' } })  // 那次 GET 的旧快照后到
    await get

    expect(s.raw, 'PUT 之后 raw 必须是 PUT 响应，不得被更早的 GET 换回旧值').toEqual({ page_size: 200, chart_renderer: 'svg' })
  })

  /**
   * 修复轮 Minor（store 里 generation 注释的第 ③ 条危害，此前零用例覆盖）——
   * 陈旧续体的 `.finally` 不得动 **reset 之后新发起**的那次状态：它会把新 inflight 清成 null
   * 并把 settled 提前置真 ⇒ 后来者 `await ensure()` 会**提前 resolve**、在第二次 GET 还没落地时
   * 读到 raw===null，按「拉取失败」回退默认值并 memo 一整个文档（useChartMemory 就 memo 这个）。
   * ⚠ 断言不能用 promise 身份：Pinia 的 dev 档 action wrapper 会把返回的 promise 再 `.then` 一层
   *   （实测 `s.ensure() === 上一次返回的那条` 恒 false），只有「是否提前 resolve」是干净判据。
   */
  it('陈旧 .finally 不得让 reset 后新发起的 ensure 提前 resolve（单飞/结算守恒）', async () => {
    let resolveFirst!: (v: { data: Record<string, unknown> }) => void
    let resolveSecond!: (v: { data: Record<string, unknown> }) => void
    getSettings
      .mockImplementationOnce(() => new Promise((r) => { resolveFirst = r }))
      .mockImplementationOnce(() => new Promise((r) => { resolveSecond = r }))
    const s = useUserSettingsStore()
    const first = s.ensure()
    await Promise.resolve()
    s.reset()
    const second = s.ensure()
    await Promise.resolve()
    expect(getSettings, '两次 ensure 各发一条 GET').toHaveBeenCalledTimes(2)

    resolveFirst({ data: { page_size: 999 } })   // 旧账号响应在第二次仍 in 飞时落地
    await first

    let earlyResolve = false
    void s.ensure().then(() => { earlyResolve = true })
    await new Promise((r) => setTimeout(r, 0))   // 冲掉所有微任务：陈旧续体若作乱，这里就翻true
    expect(earlyResolve, '陈旧续体不得清掉新 inflight / 提前置 settled').toBe(false)
    expect(getSettings, '单飞未破 ⇒ 不该冒出第三条 GET').toHaveBeenCalledTimes(2)

    resolveSecond({ data: { page_size: 100 } })
    await second
    await new Promise((r) => setTimeout(r, 0))
    expect(earlyResolve, '第二次落地后 ensure 才算取过').toBe(true)
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
