/**
 * 单文件分析图表账号级记忆（/auth/settings/ 的 analysis_chart_* 两字段）。
 * ────────────────────────────────────────────────
 * - load() 单飞：分析页多个消费方（useChartDock / SingleParamTab）共享一次拉取。
 * - save() 防抖合并：layout（useChartDock 各 persist 点）与 toggles（勾选 watch）
 *   各自上报，800ms 内合并为一次部分 PUT；pagehide 立即冲刷防丢最后一次改动。
 * - 开关三态：null=settings 未返回或拉取失败（localStorage 照写、后端不写——
 *   与「用户关开关」区分开，避免一次网络抖动被当成主动关闭而清掉本机布局）/
 *   true=正常同步 / false=用户已关闭（两层都阻断）。
 * - 结构校验在本模块；后端哑 JSON 存储同 export_filename_templates 模式。
 * - 登录/登出必须调 resetChartMemoryCache()（auth store 已接），否则 SPA 内
 *   换账号会复用上一账号的设置缓存。
 * 放 src/composables 而非 pages/analysis/composables：设置页恢复按钮也复用。
 * 注意：与 useChartDock 运行时互相 import（ESM 活绑定，调用时解析安全），
 * 任何一侧都不得在模块顶层调用对方的导出。
 */
import { authApi } from '../api/auth'
import { safeRemoveItem } from '../utils/safeStorage'
import { DOCK_LAYOUT_STORAGE_KEY, isValidLayout, type DockLayout } from '../pages/analysis/composables/useChartDock'

const DEBOUNCE_MS = 800

export interface ChartToggles { serial: boolean; qq: boolean; box: boolean }
export interface ChartMemorySnapshot { layout: DockLayout | null; toggles: ChartToggles | null }
export interface ChartMemoryLoadResult {
  memoryEnabled: boolean | null
  fetchFailed: boolean
  state: ChartMemorySnapshot
}

let settingsPromise: Promise<ChartMemoryLoadResult> | null = null
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
  return { serial: o.serial, qq: o.qq, box: o.box }
}

function parseState(raw: unknown): ChartMemorySnapshot {
  if (!raw || typeof raw !== 'object') return { layout: null, toggles: null }
  const o = raw as Record<string, unknown>
  return { layout: isValidLayout(o.layout) ? o.layout : null, toggles: parseToggles(o.toggles) }
}

export function loadChartMemory(): Promise<ChartMemoryLoadResult> {
  if (!settingsPromise) {
    settingsPromise = authApi
      .getSettings()
      .then(({ data }) => {
        const d = (data ?? {}) as Record<string, unknown>
        memoryEnabled = d.analysis_chart_memory !== false
        const state = parseState(d.analysis_chart_state)
        // 快速 F5 会丢掉防抖窗口里的勾选上报（pagehide 请求在 unload 中被浏览器
        // 取消），服务端可能只剩 layout 没有 toggles。布局里的 key 就是「当时勾着」
        // 的事实记录，由它反推勾选——否则勾选缺省全 false → active 收缩 →
        // reconcile 把已存布局裁剪掉（两层同时降级，之后每次刷新都复现）。
        if (memoryEnabled && state.layout && !state.toggles) {
          const keys = new Set(state.layout.rows.flat())
          state.toggles = { serial: keys.has('serial'), qq: keys.has('qq'), box: keys.has('box') }
        }
        if (memoryEnabled && latest) scheduleFlush()
        else if (memoryEnabled === false) latest = null
        return { memoryEnabled, fetchFailed: false, state }
      })
      .catch(() => {
        // 拉取失败 ≠ 用户关开关：后端本会话不写；本机门控保持开启，
        // 避免下游「关=复位布局」分支把一次网络抖动误清成默认布局
        memoryEnabled = null
        latest = null
        return { memoryEnabled, fetchFailed: true, state: { layout: null, toggles: null } }
      })
  }
  return settingsPromise
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
  authApi.updateSettings({ analysis_chart_state: { ...payload } }).catch(() => {
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
    await authApi.updateSettings({ analysis_chart_state: {} })
    return true
  } catch {
    return false
  }
}

/** 设置页「保存为开」时调用：SPA 会话内把开关拨回 true（布局套用下次进入分析页生效） */
export function setChartMemoryEnabled(enabled: boolean) {
  memoryEnabled = enabled
}

/** 登录/登出/账号切换时重置全部模块态（auth store 的 reset*Cache 同款先例） */
export function resetChartMemoryCache() {
  settingsPromise = null
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
    authApi.updateSettingsKeepalive({ analysis_chart_state: { ...payload } })
  })
}
