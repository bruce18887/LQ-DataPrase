/**
 * 导出请求超时（秒）的模块级缓存。
 *
 * 值来自系统设置 UserSetting.export_timeout（GET /auth/settings/）。导出调用点
 * （DataBrowserAgGrid / useExport / ExportFooter）统一 await getExportTimeoutMs()
 * 获取超时毫秒值，不再各自硬编码。
 *
 * 缓存为模块单例（仿 useZoom / echarts-theme 先例）：首次导出时单飞拉取一次
 * 设置，失败回退默认值；SettingsPage 加载/保存后通过 setExportTimeoutSec 同步，
 * auth store 在登录/登出时 reset，防止跨用户串值。
 */

import { authApi } from '../api/auth'

export const DEFAULT_EXPORT_TIMEOUT_SEC = 600
export const MIN_EXPORT_TIMEOUT_SEC = 30
export const MAX_EXPORT_TIMEOUT_SEC = 3600

/** 钳位到合法范围（30–3600 秒），非法输入回退默认值。 */
export function clampExportTimeoutSec(sec: number): number {
  if (!Number.isFinite(sec)) return DEFAULT_EXPORT_TIMEOUT_SEC
  return Math.min(MAX_EXPORT_TIMEOUT_SEC, Math.max(MIN_EXPORT_TIMEOUT_SEC, Math.round(sec)))
}

let cachedSec: number | null = null
let fetchPromise: Promise<number> | null = null

/** 本地写入缓存（SettingsPage 加载/保存后调用，不触发网络请求）。 */
export function setExportTimeoutSec(sec: number): void {
  cachedSec = clampExportTimeoutSec(sec)
}

/** 清空缓存（auth store 登录/登出时调用，防跨用户串值）。 */
export function resetExportTimeoutCache(): void {
  cachedSec = null
  fetchPromise = null
}

/**
 * 导出请求超时毫秒值。缓存未命中时单飞拉取一次 /auth/settings/，
 * 失败回退默认值（等效此前 DataBrowser 的硬编码 600s）。
 */
export function getExportTimeoutMs(): Promise<number> {
  if (cachedSec !== null) return Promise.resolve(cachedSec * 1000)
  if (!fetchPromise) {
    fetchPromise = (async () => {
      try {
        const { data } = await authApi.getSettings()
        cachedSec = clampExportTimeoutSec(Number(data?.export_timeout))
      } catch {
        cachedSec = DEFAULT_EXPORT_TIMEOUT_SEC
      }
      return cachedSec * 1000
    })()
  }
  return fetchPromise
}
