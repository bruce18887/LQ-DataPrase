/**
 * SFTP 下载超时（秒）的模块级缓存。
 *
 * 值来自用户设置 UserSetting.sftp_download_timeout（GET /auth/settings/），
 * 与 exportTimeout 同构：
 * - SFTP 浏览器下载参数（SSE 请求体 timeout + 批量下载 axios timeout）统一
 *   await getSftpTimeoutSec()，不再各自硬编码；
 * - SftpBrowser 工具栏可自由调整并持久化（PUT /auth/settings/）；
 * - auth store 在登录/登出时 reset，防止跨用户串值。
 */

import { authApi } from '../api/auth'

export const DEFAULT_SFTP_TIMEOUT_SEC = 600
export const MIN_SFTP_TIMEOUT_SEC = 30
export const MAX_SFTP_TIMEOUT_SEC = 3600

/** 钳位到合法范围（30–3600 秒），非法输入回退默认值。 */
export function clampSftpTimeoutSec(sec: number): number {
  if (!Number.isFinite(sec)) return DEFAULT_SFTP_TIMEOUT_SEC
  return Math.min(MAX_SFTP_TIMEOUT_SEC, Math.max(MIN_SFTP_TIMEOUT_SEC, Math.round(sec)))
}

let cachedSec: number | null = null
let fetchPromise: Promise<number> | null = null

/** 本地写入缓存（不触发网络请求）。 */
export function setSftpTimeoutSec(sec: number): void {
  cachedSec = clampSftpTimeoutSec(sec)
}

/** 清空缓存（auth store 登录/登出时调用，防跨用户串值）。 */
export function resetSftpTimeoutCache(): void {
  cachedSec = null
  fetchPromise = null
}

/**
 * SFTP 下载超时秒数。缓存未命中时单飞拉取一次 /auth/settings/，
 * 失败回退默认 600 秒。
 */
export function getSftpTimeoutSec(): Promise<number> {
  if (cachedSec !== null) return Promise.resolve(cachedSec)
  if (!fetchPromise) {
    fetchPromise = (async () => {
      try {
        const { data } = await authApi.getSettings()
        cachedSec = clampSftpTimeoutSec(Number(data?.sftp_download_timeout))
      } catch {
        cachedSec = DEFAULT_SFTP_TIMEOUT_SEC
      }
      return cachedSec
    })()
  }
  return fetchPromise
}

/** 批量下载等 axios 调用使用的毫秒值。 */
export function getSftpTimeoutMs(): Promise<number> {
  return getSftpTimeoutSec().then((sec) => sec * 1000)
}
