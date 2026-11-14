/**
 * 重复项保留选择的全部派生逻辑与文案（批3a · 第 3 项）。
 *
 * 与批2 的 `utils/diskUsage.ts` 同一条分工理由：会被用户读成**承诺**的句子
 * （「本批处理前 50 组」「按选择删除 3 个」）必须在 T2 钉住，组件只做渲染。
 * 这条卡片上的承诺尤其贵 —— 它后面是不可撤销的物理删除（设计 §5.5 已否掉 `.trash`）。
 *
 * 三件事在这里，不在组件里：
 * 1. 每组保留谁的裁决（改选值 / 默认 id 最小 / 策略 + 并列裁决 id 最小）；
 * 2. 「应用到未改选的 N 组」只碰未改选的那些；
 * 3. 上行载荷 `keep_ids` == 已展示每组的保留项，与服务端白名单同源那条边界。
 */
import type { DuplicateGroup } from '../api/datafiles'
import { usageBytesText } from './diskUsage'

export type KeepStrategy = 'earliest' | 'latest'

/** 两颗策略，不多写第三颗：组内 `file_size` 恒等（分组键含它），「体积最大」永远选不出别的东西。 */
export const STRATEGY_LABELS: Record<KeepStrategy, string> = {
  earliest: '最早导入',
  latest: '最新导入',
}

/**
 * 与后端 `_group_key` 同形状（`(filename, file_size)`），但必须是字符串：前端只拿 GET 的
 * `duplicate_groups`，没有别的可用身份。`|` 分隔不引入碰撞 —— 右段恒为数字，
 * 两个不同的 (filename, size) 拼出同一串需要文件名里吃掉一个 `|` 且大小仍是同一个数。
 */
export function groupKey(group: DuplicateGroup): string {
  return `${group.filename}|${group.file_size}`
}

/** 默认保留项 = `files[0].id`：后端 `files` 按 id 升序（`_group_duplicates` 的 order_by('id')）。 */
export function defaultKeepId(group: DuplicateGroup): number {
  return group.files[0].id
}

/**
 * 策略裁决。并列裁决**天然落在 id 最小**，不需要额外分支：`files` 按 id 升序是后端契约
 * （`_group_duplicates` 的 `order_by('id')`，Task 3 有一条 T1 钉住它），reduce 从 `files[0]`
 * 起步、只在**严格**更早/更晚时换人 ⇒ `created_at` 相同的组里首条就是 id 最小的那条。
 * 「相同 created_at 时再比一次 id」那种写法是给已经排好序的数组重复排序，
 * 而且会误导下一个人以为顺序不可靠。
 */
export function strategyKeepId(group: DuplicateGroup, strategy: KeepStrategy): number {
  let best = group.files[0]
  for (const f of group.files) {
    const better = strategy === 'earliest'
      ? f.created_at < best.created_at
      : f.created_at > best.created_at
    if (better) best = f
  }
  return best.id
}

export function keepIdForGroup(group: DuplicateGroup, choice: Map<string, number>): number {
  const chosen = choice.get(groupKey(group))
  return chosen === undefined ? defaultKeepId(group) : chosen
}

/** 返回**新** Map（调用方直接赋给 ref，Vue 侧不依赖 Map 的深改追踪）。 */
export function applyStrategyToUntouched(
  groups: DuplicateGroup[],
  choice: Map<string, number>,
  strategy: KeepStrategy,
): Map<string, number> {
  const next = new Map(choice)
  for (const group of groups) {
    const key = groupKey(group)
    if (!next.has(key)) next.set(key, strategyKeepId(group, strategy))
  }
  return next
}

/** 已展示每组的保留项全量上行（含未改选的默认值）。服务端据此逐组裁决，见 `_resolve_keep_selection`。 */
export function resolveKeepIds(groups: DuplicateGroup[], choice: Map<string, number>): number[] {
  return groups.map((group) => keepIdForGroup(group, choice))
}

/**
 * 汇总只算已展示组 —— 与按钮要删的东西严格同范围，否则数字就是在骗人。
 * 形参里没有 `choice`，不是漏了：每组恒删 `len - 1` 个，**改选保留谁不改变删除数量**，
 * 只改变删走的那一份（那一份由 `resolveKeepIds` 承重）。加一个不参与计算的参数
 * 只会让下一个人以为它参与。
 */
export function deleteSummary(groups: DuplicateGroup[]): { count: number; bytes: number } {
  let count = 0
  let bytes = 0
  for (const group of groups) {
    const doomed = group.files.length - 1
    count += doomed
    bytes += doomed * group.file_size
  }
  return { count, bytes }
}

export function deleteSummaryText(groups: DuplicateGroup[]): string {
  const { count, bytes } = deleteSummary(groups)
  return `按选择删除 ${count} 个（${usageBytesText(bytes)}）`
}

/** 超过切片才出这句话（MaintenanceCard 的空串即不渲染）。 */
export function truncatedNoteText(totalCount: number, displayedCount: number): string {
  if (totalCount <= displayedCount) return ''
  return `共 ${totalCount} 组重复，本批处理前 ${displayedCount} 组，`
    + `另有 ${totalCount - displayedCount} 组未处理 —— 重新检查后可继续。`
}

/** 删除回执的尾巴。0 时说空话比说「另有 0 组」好读。 */
export function remainingGroupsNote(remaining: number | undefined): string {
  if (!remaining || remaining <= 0) return ''
  return `，另有 ${remaining} 组未处理`
}

/**
 * 故意不复用 `utils/format.ts` 的 `formatTime`：那是 MM-DD HH:mm 短形态，
 * 实测 `formatTime('2026-11-14T23:07:08+00:00')` = `'11/15 07:07'` —— 没有年份，
 * 而这张卡要分「两次导入」的先后，样本实测差两个月、跨年时短形态会读反。
 * 同一条理由的第二份实现见 `diskUsage.ts:usageScannedText`（那边还带 `hour12:false` 的
 * 等价变异说明）；第三份出现时把它们并起来。
 */
export function dupImportText(value: string): string {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return date.toLocaleString('zh-CN', { hour12: false })
}
