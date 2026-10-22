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
})
