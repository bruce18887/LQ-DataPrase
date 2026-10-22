/**
 * 文件名自动换行（文件列表 + 批次数据列表共同生效）的读取入口。
 *
 * 值来自用户设置 UserSetting.filename_wrap（GET /auth/settings/，默认 true），
 * 与 sftpTimeout/exportTimeout 同构：
 * - 文件列表与批次表格统一 await getFilenameWrap()，不再各自 localStorage；
 * - 设置页「表格设置」可开关并持久化（PUT /auth/settings/）；
 * - 缓存由 stores/userSettings.ts 唯一持有（本模块只保留键位与回退默认值），
 *   登录/登出的失效由 auth store 调 store.reset() 统一负责。
 */

import { useUserSettingsStore } from '../stores/userSettings'

export const DEFAULT_FILENAME_WRAP = true

/** 本地写入账号设置（设置页保存成功后调用，不触发网络请求）。 */
export function setFilenameWrapCache(value: boolean): void {
  useUserSettingsStore().patch({ filename_wrap: value })
}

/**
 * 文件名是否自动换行。签名保持不变（调用点一律 await），值取自唯一持有者：
 * 未取过时由 store 单飞拉一次 /auth/settings/，取不到（非布尔/失败）回退默认开启，
 * 且失败后整页不再重试。
 */
export function getFilenameWrap(): Promise<boolean> {
  const store = useUserSettingsStore()
  return store.ensure().then(() => {
    const v = store.raw?.filename_wrap
    return typeof v === 'boolean' ? v : DEFAULT_FILENAME_WRAP
  })
}
