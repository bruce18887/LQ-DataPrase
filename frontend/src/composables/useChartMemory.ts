/**
 * 单文件分析图表账号级记忆（/auth/settings/ 的 analysis_chart_* 两字段）。
 * ────────────────────────────────────────────────
 * - 取数走 stores/userSettings（Task 6b）：本模块**不再**自己 GET，分析页多个消费方
 *   （useChartDock / SingleParamTab）共享的是 store 的单飞 + 自己这份已解析结果的 memo。
 * - save() 防抖合并：layout（useChartDock 各 persist 点）与 toggles（勾选 watch）
 *   各自上报，800ms 内合并为一次部分 PUT；pagehide 立即冲刷防丢最后一次改动。
 *   两条 PUT 通道都经 store（save / saveKeepalive），raw 随之更新，不再有「模块知道但
 *   store 是旧的」这种分叉。
 * - 开关三态：null=settings 未返回或拉取失败（localStorage 照写、后端不写——
 *   与「用户关开关」区分开，避免一次网络抖动被当成主动关闭而清掉本机布局）/
 *   true=正常同步 / false=用户已关闭（两层都阻断）。
 *   口径搬自今天的 catch 分支，判据换成 `store.raw === null`：ensure() 失败会把它置 null，
 *   之后整页生命周期不再重取（防请求风暴，见 store 文件头）。
 *   ⚠ 一处收紧：200 但响应体为 null 这种形状（后端 serializer 不会出现，纯防御）今天算
 *   「成功且视为开」，现在算「拿不到设置」⇒ 本会话不写后端、只写本机。
 * - 结构校验在本模块；后端哑 JSON 存储同 export_filename_templates 模式。
 * - 登录/登出必须调 resetChartMemoryCache()（auth store 已接）：它清的是本模块自己的
 *   三态/待冲刷内容/memo（store.reset() 管不到），store 侧由 auth store 另调一次。
 * 放 src/composables 而非 pages/analysis/composables：设置页恢复按钮也复用。
 * 注意：与 useChartDock 运行时互相 import（ESM 活绑定，调用时解析安全），
 * 任何一侧都不得在模块顶层调用对方的导出。
 */
import { useUserSettingsStore } from '../stores/userSettings'
import { safeRemoveItem } from '../utils/safeStorage'
import { DOCK_LAYOUT_STORAGE_KEY, isValidLayout, type DockLayout } from '../pages/analysis/composables/useChartDock'

const DEBOUNCE_MS = 800

export interface ChartToggles { hist: boolean; serial: boolean; qq: boolean; box: boolean }
export interface ChartMemorySnapshot { layout: DockLayout | null; toggles: ChartToggles | null }
export interface ChartMemoryLoadResult {
  memoryEnabled: boolean | null
  fetchFailed: boolean
  state: ChartMemorySnapshot
}

/** load() 结果的 memo：请求的单飞在 store 里，这里只是「同一份解析结果只算一次」。 */
let loadPromise: Promise<ChartMemoryLoadResult> | null = null
let memoryEnabled: boolean | null = null
let latest: { layout?: DockLayout; toggles?: ChartToggles } | null = null
let timer: ReturnType<typeof setTimeout> | null = null

/** 当前记忆开关（null = settings 未返回或拉取失败，非用户主动关闭） */
export function isMemoryEnabled(): boolean | null {
  return memoryEnabled
}

function parseToggles(raw: unknown): ChartToggles | null {
  if (!raw || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  if (typeof o.serial !== 'boolean' || typeof o.qq !== 'boolean' || typeof o.box !== 'boolean') return null
  // hist 为 2026-09-13 新增字段：旧账号数据缺它 → 默认 true（直方图原为常驻不可关）
  return {
    hist: typeof o.hist === 'boolean' ? o.hist : true,
    serial: o.serial,
    qq: o.qq,
    box: o.box,
  }
}

function parseState(raw: unknown): ChartMemorySnapshot {
  if (!raw || typeof raw !== 'object') return { layout: null, toggles: null }
  const o = raw as Record<string, unknown>
  return { layout: isValidLayout(o.layout) ? o.layout : null, toggles: parseToggles(o.toggles) }
}

export function loadChartMemory(): Promise<ChartMemoryLoadResult> {
  if (!loadPromise) {
    const store = useUserSettingsStore()
    loadPromise = store.ensure().then(() => {
      // store.raw === null ⇒ 那次 GET 失败（或被 reset 后尚未重取）：与今天 catch 分支同口径
      if (store.raw === null) {
        memoryEnabled = null
        latest = null
        return { memoryEnabled, fetchFailed: true, state: { layout: null, toggles: null } }
      }
      const d = store.raw as Record<string, unknown>
      memoryEnabled = d.analysis_chart_memory !== false
      const state = parseState(d.analysis_chart_state)
      // 快速 F5 会丢掉防抖窗口里的勾选上报（pagehide 请求在 unload 中被浏览器
      // 取消），服务端可能只剩 layout 没有 toggles。布局里的 key 就是「当时勾着」
      // 的事实记录，由它反推勾选——否则勾选缺省全 false → active 收缩 →
      // reconcile 把已存布局裁剪掉（两层同时降级，之后每次刷新都复现）。
      if (memoryEnabled && state.layout && !state.toggles) {
        const keys = new Set(state.layout.rows.flat())
        state.toggles = {
          hist: keys.has('hist'),
          serial: keys.has('serial'),
          qq: keys.has('qq'),
          box: keys.has('box'),
        }
      }
      if (memoryEnabled && latest) scheduleFlush()
      else if (memoryEnabled === false) latest = null
      return { memoryEnabled, fetchFailed: false, state }
    })
  }
  return loadPromise
}

function scheduleFlush() {
  if (timer) clearTimeout(timer)
  timer = setTimeout(flush, DEBOUNCE_MS)
}

function flush() {
  timer = null
  if (memoryEnabled !== true || !latest) return
  const payload = latest
  latest = null
  useUserSettingsStore().save({ analysis_chart_state: { ...payload } }).catch(() => {
    /* 后台静默同步：失败不打扰用户 */
  })
}

/** layout / toggles 变化上报（内部判开关 + 防抖合并为一次 PUT） */
export function saveChartState(patch: { layout?: DockLayout; toggles?: ChartToggles }) {
  if (memoryEnabled === false) return // 用户已关：不积累、不发送
  latest = { ...(latest ?? {}), ...patch }
  if (memoryEnabled === true) scheduleFlush()
}

/** 清空账号状态 + 本机布局。「保存为关」传 { disableMemory: true } 同步断写 */
export async function clearChartMemoryState(opts: { disableMemory?: boolean } = {}): Promise<boolean> {
  latest = null
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
  safeRemoveItem(DOCK_LAYOUT_STORAGE_KEY)
  if (opts.disableMemory) memoryEnabled = false
  try {
    await useUserSettingsStore().save({ analysis_chart_state: {} })
    return true
  } catch {
    return false
  }
}

/** 设置页「保存为开」时调用：SPA 会话内把开关拨回 true（布局套用下次进入分析页生效） */
export function setChartMemoryEnabled(enabled: boolean) {
  memoryEnabled = enabled
}

/**
 * 登录/登出/账号切换时重置本模块态。⚠ 它**不**负责 store —— store.reset() 由
 * stores/auth.ts 的 resetUserSettingsCaches() 另调一次；本模块留下的三样
 * （memoryEnabled 三态 / 待冲刷的 latest / loadPromise memo）都不是账号设置本身，
 * 是分析页自己的运行时状态，store 治不到。
 */
export function resetChartMemoryCache() {
  loadPromise = null
  memoryEnabled = null
  latest = null
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
}

// 关标签/刷新前立即冲刷：800ms 防抖窗口内的最后一次改动不能丢。
// 必须走 fetch keepalive——axios(XHR) 在 unload 期间会被浏览器直接取消，
// 快速 F5 的最后一次拖拽/勾选就这样静默丢失（服务端留旧态，下次加载
// 「服务端覆盖本机」把新布局吃掉，即「刷新后恢复默认」的种子）。
if (typeof document !== 'undefined') {
  document.addEventListener('pagehide', () => {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
    if (memoryEnabled !== true || !latest) return
    const payload = latest
    latest = null
    useUserSettingsStore().saveKeepalive({ analysis_chart_state: { ...payload } })
  })
}
