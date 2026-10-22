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
 *   ⚠ 由此带来的口径（6b 评审 R24 纠的原文错处）：raw **可能只含部分键**。正常链路
 *   （路由守卫先 await ensureChartRenderer，再挂任何页面组件）第一次就是服务端全量，
 *   但守卫那次 GET 失败后（raw=null）若有人调 setter，patch 出来的就是只含那几个键的 raw，
 *   其余键一律读到各消费方自己的回退值 —— 与今天各模块私有缓存「失败即默认值」同形，不退化。
 */
export const useUserSettingsStore = defineStore('userSettings', () => {
  const raw = ref<UserSettings | null>(null)
  let settled = false
  let inflight: Promise<void> | null = null
  /**
   * 纪元计数（6b 评审 R24 0a）。reset() 只能把 inflight 置 null，**拦不住已经派发出去的
   * .then/.finally**：没有它时，那两条续体会把上一个账号的 payload 写进 raw 并把 settled
   * 置真（此后整页不再取数），还会顺手把 reset 之后新发起的那次 inflight 也清成 null。
   * 可达链路：登录时 stores/auth.ts 的 reset / axios 401 的 forceLogout（api/index.ts:226 附近）
   * 正好撞在路由守卫那次 GET 在飞上。每次 ensure 捕获自己的 gen，续体开头比对，不等就整段跳过。
   */
  let generation = 0

  /** 幂等：取过就不再取；失败也算取过（与 echarts-theme.ts:44-51 的降级口径一致，防请求风暴）。 */
  function ensure(): Promise<void> {
    if (inflight) return inflight
    if (settled) return Promise.resolve()
    const gen = ++generation
    // 包一层再调：authApi.getSettings() 若是**同步**抛（拦截器/请求构造期异常），
    // 直接冒泡会打断 router/index.ts:178 那句没有 try/catch 的 await ⇒ 整条导航被中断。
    inflight = Promise.resolve()
      .then(() => authApi.getSettings())
      .then(({ data }) => {
        if (gen !== generation) return
        raw.value = (data ?? null) as UserSettings | null
      })
      .catch(() => {
        if (gen !== generation) return
        raw.value = null
      })
      .finally(() => {
        if (gen !== generation) return
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

  /**
   * 只 PUT 调用方给的键（后端 serializer 是 partial=True，增量合法）。
   * 顺带记为已取过：PUT 的响应体就是那 20 个字段的全量
   * （apps/accounts/views.py:218-225 + apps/accounts/serializers.py:95-107），
   * raw 可证明完整 ⇒ 保存后不该再补一次 GET（R24 0b，砍掉本任务要消灭的每导航多一次 GET 中的一次）。
   */
  async function save(p: Partial<UserSettings>): Promise<void> {
    const { data } = await authApi.updateSettings(p as Record<string, unknown>)
    raw.value = (data ?? null) as UserSettings | null
    settled = true
  }

  /** 卸载期冲刷专用（pagehide），沿用 api/auth.ts:174-191 的 keepalive 通道。 */
  function saveKeepalive(p: Partial<UserSettings>): void {
    patch(p)
    authApi.updateSettingsKeepalive(p as Record<string, unknown>)
  }

  /** 登录/登出调用，防跨账号串值。纪元 +1 ⇒ 在飞响应的续体整段作废。 */
  function reset(): void {
    generation++
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
