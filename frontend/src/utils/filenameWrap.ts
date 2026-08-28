/**
 * 文件名自动换行（文件列表 + 批次数据列表共同生效）的模块级缓存。
 *
 * 值来自用户设置 UserSetting.filename_wrap（GET /auth/settings/，默认 true），
 * 与 sftpTimeout/exportTimeout 同构：
 * - 文件列表与批次表格统一 await getFilenameWrap()，不再各自 localStorage；
 * - 设置页「表格设置」可开关并持久化（PUT /auth/settings/）；
 * - auth store 在登录/登出时 reset，防止跨用户串值。
 */

import { authApi } from '../api/auth'

export const DEFAULT_FILENAME_WRAP = true

let cachedWrap: boolean | null = null
let fetchPromise: Promise<boolean> | null = null

/** 本地写入缓存（设置页保存成功后调用，不触发网络请求）。 */
export function setFilenameWrapCache(value: boolean): void {
  cachedWrap = value
}

/** 清空缓存（auth store 登录/登出时调用，防跨用户串值）。 */
export function resetFilenameWrapCache(): void {
  cachedWrap = null
  fetchPromise = null
}

/**
 * 文件名是否自动换行。缓存未命中时单飞拉取一次 /auth/settings/，
 * 失败回退默认开启。
 */
export function getFilenameWrap(): Promise<boolean> {
  if (cachedWrap !== null) return Promise.resolve(cachedWrap)
  if (!fetchPromise) {
    fetchPromise = (async (): Promise<boolean> => {
      let value = DEFAULT_FILENAME_WRAP
      try {
        const { data } = await authApi.getSettings()
        if (typeof data?.filename_wrap === 'boolean') value = data.filename_wrap
      } catch {
        // 请求失败保持默认开启
      }
      cachedWrap = value
      return value
    })()
  }
  return fetchPromise as Promise<boolean>
}
