/**
 * safeStorage — localStorage 安全读写封装
 *
 * 问题背景：Electron 环境下 userData 目录权限异常或磁盘满时
 * localStorage.getItem/setItem 会抛 DOMException（QuotaExceededError /
 * SecurityError），若发生在 store 初始化阶段会直接导致白屏。
 *
 * 方案：统一走 safeGetItem / safeSetItem，内部 try/catch 静默降级，
 * DEV 模式下 console.warn 方便开发排查。不再在各文件各写一份 try/catch
 * （此前 useZoom.ts setItem 有 try/catch 而同文件 getItem 无，auth.ts /
 * theme.ts / sftp.ts 均无保护——散落且不一致）。
 */

const isDev = import.meta.env.DEV

/**
 * 安全读取 localStorage，异常时返回 null（等同 key 不存在）。
 */
export function safeGetItem(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch (e) {
    if (isDev) console.warn(`[safeStorage] getItem("${key}") failed:`, e)
    return null
  }
}

/**
 * 安全写入 localStorage，异常时静默忽略（不影响应用功能）。
 */
export function safeSetItem(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch (e) {
    if (isDev) console.warn(`[safeStorage] setItem("${key}") failed:`, e)
  }
}

/**
 * 安全移除 localStorage 条目，异常时静默忽略。
 */
export function safeRemoveItem(key: string): void {
  try {
    localStorage.removeItem(key)
  } catch (e) {
    if (isDev) console.warn(`[safeStorage] removeItem("${key}") failed:`, e)
  }
}
