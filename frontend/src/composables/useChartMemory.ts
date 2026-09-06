/**
 * 单文件分析图表账号级记忆（/auth/settings/ 的 analysis_chart_* 两字段）。
 * ────────────────────────────────────────────────
 * - load() 单飞：分析页多个消费方（useChartDock / SingleParamTab）共享一次拉取。
 * - save() 防抖合并：layout（useChartDock 各 persist 点）与 toggles（勾选 watch）
 *   各自上报，800ms 内合并为一次部分 PUT。
 * - 开关三态：null=settings 未返回（localStorage 照写、后端暂存，load 返回后
 *   按开关发出或丢弃）/ true=正常同步 / false=两层都阻断；拉取失败按 false。
 * - 结构校验在本模块；后端哑 JSON 存储同 export_filename_templates 模式。
 * 放 src/composables 而非 pages/analysis/composables：设置页恢复按钮也复用。
 */
import { authApi } from '../api/auth'
import { safeRemoveItem } from '../utils/safeStorage'
import { DOCK_LAYOUT_STORAGE_KEY, isValidLayout, type DockLayout } from '../pages/analysis/composables/useChartDock'

const DEBOUNCE_MS = 800

export interface ChartToggles { serial: boolean; qq: boolean; box: boolean }
export interface ChartMemorySnapshot { layout: DockLayout | null; toggles: ChartToggles | null }

let settingsPromise: Promise<{ memoryEnabled: boolean; state: ChartMemorySnapshot }> | null = null
let memoryEnabled: boolean | null = null
let latest: { layout?: DockLayout; toggles?: ChartToggles } | null = null
let timer: ReturnType<typeof setTimeout> | null = null

/** 当前记忆开关（null = settings 未返回）。useChartDock.persist 用它门控本机写入 */
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

export function loadChartMemory(): Promise<{ memoryEnabled: boolean; state: ChartMemorySnapshot }> {
  if (!settingsPromise) {
    settingsPromise = authApi
      .getSettings()
      .then(({ data }) => {
        const d = (data ?? {}) as Record<string, unknown>
        memoryEnabled = d.analysis_chart_memory !== false
        const state = parseState(d.analysis_chart_state)
        if (memoryEnabled && latest) scheduleFlush()
        else if (!memoryEnabled) latest = null
        return { memoryEnabled, state }
      })
      .catch(() => {
        memoryEnabled = false
        latest = null
        return { memoryEnabled, state: { layout: null, toggles: null } }
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
  latest = { ...(latest ?? {}), ...patch }
  if (memoryEnabled === true) scheduleFlush()
}

/** 清空账号状态 + 本机布局。设置页「恢复默认布局」与「保存为关」共用 */
export async function clearChartMemoryState() {
  latest = null
  if (timer) {
    clearTimeout(timer)
    timer = null
  }
  safeRemoveItem(DOCK_LAYOUT_STORAGE_KEY)
  try {
    await authApi.updateSettings({ analysis_chart_state: {} })
  } catch {
    /* 设置页有统一错误提示；本机已清 */
  }
}
