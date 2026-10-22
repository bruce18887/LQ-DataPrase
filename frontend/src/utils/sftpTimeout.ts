/**
 * SFTP 下载超时（秒）的读取入口。
 *
 * 值来自用户设置 UserSetting.sftp_download_timeout（GET /auth/settings/），
 * 与 exportTimeout 同构：
 * - SFTP 浏览器下载参数（SSE 请求体 timeout + 批量下载 axios timeout）统一
 *   await getSftpTimeoutSec()，不再各自硬编码；
 * - SftpBrowser 工具栏可自由调整并持久化（PUT /auth/settings/）；
 * - 缓存由 stores/userSettings.ts 唯一持有（本模块只保留键位、钳位与回退默认值），
 *   登录/登出的失效由 auth store 调 store.reset() 统一负责。
 */

import { useUserSettingsStore } from '../stores/userSettings'

export const DEFAULT_SFTP_TIMEOUT_SEC = 600
export const MIN_SFTP_TIMEOUT_SEC = 30
export const MAX_SFTP_TIMEOUT_SEC = 3600

/** 钳位到合法范围（30–3600 秒），非法输入回退默认值。 */
export function clampSftpTimeoutSec(sec: number): number {
  if (!Number.isFinite(sec)) return DEFAULT_SFTP_TIMEOUT_SEC
  return Math.min(MAX_SFTP_TIMEOUT_SEC, Math.max(MIN_SFTP_TIMEOUT_SEC, Math.round(sec)))
}

/** 本地写入账号设置（不触发网络请求）。 */
export function setSftpTimeoutSec(sec: number): void {
  useUserSettingsStore().patch({ sftp_download_timeout: clampSftpTimeoutSec(sec) })
}

/**
 * SFTP 下载超时秒数。签名保持不变（调用点一律 await），值取自唯一持有者：
 * 未取过时由 store 单飞拉一次 /auth/settings/，取不到（未设/失败）回退默认 600 秒，
 * 且失败后整页不再重试。
 */
export function getSftpTimeoutSec(): Promise<number> {
  const store = useUserSettingsStore()
  return store
    .ensure()
    .then(() => clampSftpTimeoutSec(Number(store.raw?.sftp_download_timeout)))
}

/** 批量下载等 axios 调用使用的毫秒值。 */
export function getSftpTimeoutMs(): Promise<number> {
  return getSftpTimeoutSec().then((sec) => sec * 1000)
}
