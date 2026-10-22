import { defineStore } from 'pinia'
import { ref, type Ref } from 'vue'
import { authApi } from '../api/auth'

export interface UserSettings {
  page_size?: number
  chart_renderer?: string
  export_timeout?: number
  sftp_download_timeout?: number
  filename_wrap?: boolean
  analysis_chart_memory?: boolean
  default_hidden_columns?: string[]
  [k: string]: unknown
}

/**
 * /auth/settings/ 的唯一持有者。
 *
 * 今天这份设置被 6 个互不相干的模块各自单飞（echarts-theme / exportTimeout /
 * filenameWrap / sftpTimeout / useChartMemory / DataBrowserAgGrid），一次导航实测 2–6 次 GET
 * （生产日志 2026-10-22 06:47:47 三条 auth/settings）。
 *
 * 两条不可放宽的口径（改动前请重读 `docs/tasks/lessons.md` 与 task-6-brief 的契约段）：
 * - **失败也算取过**：与今天 echarts-theme.ts:44-51 的降级口径一致，取不到就用各模块自己的
 *   回退值，整页生命周期内不再重试。若失败后重取，就是每次导航都重试的请求风暴。
 * - **patch 也算取过**：等同今天 setChartRenderer 连带把 _rendererFetched 置 true。
 *   路由守卫在任何页面组件挂载前 await ensureChartRenderer()（router/index.ts:177-179），
 *   所以正常链路是「先拿到服务端全量、后被 patch 覆盖个别键」，不会出现只含部分键的 raw。
 */
export const useUserSettingsStore = defineStore('userSettings', () => {
  const raw = ref<UserSettings | null>(null)
  let settled = false
  let inflight: Promise<void> | null = null

  /** 幂等：取过就不再取；失败也算取过（与 echarts-theme.ts:44-51 的降级口径一致，防请求风暴）。 */
  function ensure(): Promise<void> {
    if (inflight) return inflight
    if (settled) return Promise.resolve()
    inflight = authApi
      .getSettings()
      .then(({ data }) => {
        raw.value = (data ?? null) as UserSettings | null
      })
      .catch(() => {
        raw.value = null
      })
      .finally(() => {
        inflight = null
        settled = true
      })
    return inflight
  }

  /** 本地即时生效，不等 PUT 往返。同时记为已取过（等同今天 setChartRenderer 的 _rendererFetched=true）。 */
  function patch(p: Partial<UserSettings>) {
    raw.value = { ...(raw.value ?? {}), ...p }
    settled = true
  }

  /** 只 PUT 调用方给的键（后端 serializer 是 partial=True，增量合法）。 */
  async function save(p: Partial<UserSettings>): Promise<void> {
    const { data } = await authApi.updateSettings(p as Record<string, unknown>)
    raw.value = (data ?? null) as UserSettings | null
  }

  /** 卸载期冲刷专用（pagehide），沿用 auth.ts:174-191 的 keepalive 通道。 */
  function saveKeepalive(p: Partial<UserSettings>): void {
    patch(p)
    authApi.updateSettingsKeepalive(p as Record<string, unknown>)
  }

  /** 登录/登出调用，防跨账号串值。 */
  function reset(): void {
    raw.value = null
    settled = false
    inflight = null
  }

  return { raw, ensure, patch, save, saveKeepalive, reset } as {
    raw: Ref<UserSettings | null>
    ensure: () => Promise<void>
    patch: (p: Partial<UserSettings>) => void
    save: (p: Partial<UserSettings>) => Promise<void>
    saveKeepalive: (p: Partial<UserSettings>) => void
    reset: () => void
  }
})
