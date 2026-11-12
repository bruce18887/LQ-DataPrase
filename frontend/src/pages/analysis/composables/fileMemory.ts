/**
 * 分析页文件选择的「按 tab 记忆」（2026-11-12 用户需求：记住上次选择，而非默认最新）。
 *
 * 写侧只在**用户交互**落盘（AnalysisFilePicker 的 @change，el-select change 仅用户触发，
 * 程序化 v-model / 自动回退首项都不触发）——否则「先访问分析页→再上传新文件→重进」会被
 * 旧记忆钉死，且破坏依赖「默认最新」的既有 e2e。读侧在 useTabFileParams 回退分支与
 * MultiFileTab 挂载恢复消费。
 *
 * 跨账号安全（R5）：文件按 owner 过滤，记忆 id 不在新账号列表里 → pickFallbackFile 回退最新；
 * 后端每个请求也校验归属，故无需登出清键。存储走 safeStorage（Electron 磁盘满/权限异常不白屏）。
 */
import { safeGetItem, safeSetItem, safeRemoveItem } from '../../../utils/safeStorage'

const KEY_PREFIX = 'analysis.lastFile.'

/** 用户选定后落盘；null/undefined/空数组 = 清除记忆（下次回到默认最新）。 */
export function rememberFile(scope: string, value: number | number[] | null | undefined): void {
  const key = KEY_PREFIX + scope
  if (value === null || value === undefined || (Array.isArray(value) && value.length === 0)) {
    safeRemoveItem(key)
    return
  }
  safeSetItem(key, JSON.stringify(value))
}

/** 单选 tab 读记忆：非法/缺席返回 null。 */
export function recallFileId(scope: string): number | null {
  const raw = safeGetItem(KEY_PREFIX + scope)
  if (raw === null) return null
  try {
    const v = JSON.parse(raw)
    return typeof v === 'number' && Number.isFinite(v) ? v : null
  } catch {
    return null
  }
}

/** 多文件 tab 读记忆：只保留有限数字 id；非法/缺席返回 []。 */
export function recallFileIds(scope: string): number[] {
  const raw = safeGetItem(KEY_PREFIX + scope)
  if (raw === null) return []
  try {
    const v = JSON.parse(raw)
    return Array.isArray(v) ? v.filter((n): n is number => typeof n === 'number' && Number.isFinite(n)) : []
  } catch {
    return []
  }
}

/** 回退决策（纯函数，T2 承载）：记忆仍在列表里就用它，否则回退列表首项（最新）。 */
export function pickFallbackFile<T extends { id: number }>(list: T[], remembered: number | null): number | null {
  if (!list.length) return null
  if (remembered !== null && list.some((f) => f.id === remembered)) return remembered
  return list[0].id
}