/**
 * 导出请求超时（秒）的读取入口。
 *
 * 值来自系统设置 UserSetting.export_timeout（GET /auth/settings/）。导出调用点
 * （DataBrowserAgGrid / useExport / useBrowserExport / useFileCorrelation /
 * useBatchExport）统一 await getExportTimeoutMs() 获取超时毫秒值，不再各自硬编码。
 *
 * 缓存不再是本模块的私有物：账号设置的唯一持有者是 stores/userSettings.ts
 * （今天 6 个模块各自单飞同一端点，一次导航实测 2–6 次 GET）。本模块只保留
 * 键位、钳位与回退默认值；登录/登出的失效由 auth store 调 store.reset() 统一负责。
 */

import { useUserSettingsStore } from '../stores/userSettings'

export const DEFAULT_EXPORT_TIMEOUT_SEC = 600
export const MIN_EXPORT_TIMEOUT_SEC = 30
export const MAX_EXPORT_TIMEOUT_SEC = 3600

/** 钳位到合法范围（30–3600 秒），非法输入回退默认值。 */
export function clampExportTimeoutSec(sec: number): number {
  if (!Number.isFinite(sec)) return DEFAULT_EXPORT_TIMEOUT_SEC
  return Math.min(MAX_EXPORT_TIMEOUT_SEC, Math.max(MIN_EXPORT_TIMEOUT_SEC, Math.round(sec)))
}

/** 本地写入账号设置（SettingsPage 加载/保存后调用，不触发网络请求）。 */
export function setExportTimeoutSec(sec: number): void {
  useUserSettingsStore().patch({ export_timeout: clampExportTimeoutSec(sec) })
}

/**
 * 导出请求超时毫秒值。签名保持不变（调用点一律 await），值取自唯一持有者：
 * 未取过时由 store 单飞拉一次 /auth/settings/，取不到（未设/失败）回退默认值
 * （等效此前 DataBrowser 的硬编码 600s），且失败后整页不再重试。
 */
export function getExportTimeoutMs(): Promise<number> {
  const store = useUserSettingsStore()
  return store
    .ensure()
    .then(() => clampExportTimeoutSec(Number(store.raw?.export_timeout)) * 1000)
}
