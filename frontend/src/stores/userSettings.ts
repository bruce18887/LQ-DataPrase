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
   * 纪元计数（6b 评审 R24 0a，修复轮补 Important 1/2 的两处缺口）。**每次写 raw 的发起点**都 +1：
   * `ensure()` 发 GET 前、`patch()`、`save()` 发 PUT 前，以及 `reset()`。每条续体开头比对
   * `gen !== generation` 就整段跳过 —— 缺它时 `reset()` 只能把 `inflight` 置 null，**拦不住已经
   * 派发出去的 .then/.catch/.finally**，于是三族串值/回滚都可达：
   * ① 切账号后旧账号的 GET **或 PUT** 响应照样写 `raw` 并把 `settled` 置真（此后整页不再取数）；
   *    桌面版是同一文档 —— `forceLogout()`（api/index.ts:149，401 分支调用点 :215/:221）只
   *    `window.location.hash = '#/login'`，登录时 `stores/auth.ts` 的 `login()` 第一句
   *    `resetUserSettingsCaches()`（该调用在 :38，`logout()` 另在 :87）才再 reset 一次，store 实例不换；
   * ② 本地 `patch()`/`save()` 之后，**更早**派发的那次 GET 用「写之前」的服务端快照整份覆盖 `raw`
   *    （本地写被静默回滚），或它失败时 `.catch` 把 `raw` 清成 null 而 `settled` 仍为真
   *    ⇒ 每个消费方各自回退默认值、且整页不再重取；
   * ③ 陈旧 `.finally` 把 reset/新 `ensure()` 之后那条 `inflight` 清成 null ⇒ 单飞被破、同页重复发 GET。
   * ②③ 经 `useChartMemory.ts:102-115` 那个跨导航存活的 800ms 防抖真能撞上（它能在新一轮守卫 GET
   * 的窗口里 fire）。`patch()`/`save()` 顺带把被作废的那条 `inflight` 清掉，否则 `ensure()` 会一直
   * 返回一条「永远不会有人写 raw」的旧 promise。
   */
  let generation = 0

  /** 纪元 +1 并清掉被作废的那条在飞 GET：见 `generation` 注释里的 ②③。 */
  function invalidate(): void {
    generation++
    if (inflight) inflight = null
  }

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
    invalidate()  // 作废更早派发的 GET：否则它会把这次本地写整份回滚（见 generation 注释 ②）
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
    // 纪元取在**这次 PUT 自己**上：invalidate() 先把更早的 GET 作废（②），再把 PUT 派出去；
    // 响应回来时若期间发生过 reset()/patch()/又一次 save()，这次续体整段跳过（①②）。
    // 副作用：invalidate() 之后到 PUT 落地之间存在「raw 还没人写」的瞬时，两个面都要写明：
    // ① 常规形状（调用方都 await 过 ensure）：settled 已真 ⇒ ensure() 直接 resolve、不会再发 GET，
    //    瞬时只影响「此刻读 raw」的人，按 raw===null 走各消费方自己的回退值（与失败同口径），读不到半份。
    // ② 若 PUT 早于任何成功的 GET（settled 仍为 false，而 invalidate() 已把 inflight 清成 null）：
    //    并发的 ensure() 会发**第二次 GET**，它自增的纪元高于这次 PUT ⇒ PUT 的续体整段被跳过、
    //    raw 改由那条 GET 的服务端快照写。保存仍在服务端生效，但本地要等那次 GET 回来才看得见。
    //    今天打不出 ②：save() 只有三个发起点 —— SettingsPage.vue:161、useChartMemory.ts:112（防抖冲刷）、
    //    :134 clearChartMemoryState（调用方含 AnalysisLayoutSettings.vue:25 与 SettingsPage.vue:174），
    //    它们都跑在路由守卫 await 过 ensure 之后。第四条 PUT 通道 saveKeepalive
    //    （useChartMemory.ts:175，pagehide 专用）先 patch() 再发 keepalive 请求，patch 已把 settled 置真
    //    ⇒ 也不落在 ② 里（它是 keepalive 直发，不经 save()）。
    invalidate()
    const gen = generation
    const { data } = await authApi.updateSettings(p as Record<string, unknown>)
    if (gen !== generation) return
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
