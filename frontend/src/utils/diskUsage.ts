// frontend/src/utils/diskUsage.ts
/**
 * 磁盘占用的全部派生文案（批2 · 第 5 项）。
 *
 * 为什么单独成一个 utils 文件：chip 的那一句、浮层的几行、差值行都是**会被用户读成
 * 承诺**的文案，判据该由 T2（`test/unit/diskUsage.spec.ts`）钉住，而不是散在模板里
 * 只能靠 e2e 兜。组件里只做渲染，不算字符串。
 *
 * 与 `utils/format.ts` 的 `formatSize` 的关系：**故意不复用**。两个理由都各有测试钉着：
 * 1. `formatSize(0)` 返回 `'--'` 是 `format.spec.ts:23-25` 的既有契约（那边「没大小」与
 *    「0 字节」同形无妨），但「空目录 0 字节」是本功能的合法状态，chip 必须说成 `0 B`。
 * 2. `formatSize` 最高只到 MB；GB 档要加就得动既有调用点的显示（2026-11-14 现数：
 *    导入 utils 版的 7 个文件、共 9 处调用；sftp 那 3 个文件各有同名本地函数，不受影响），
 *    不属本批范围。
 */
import type { FileUsage } from '../api/datafiles'

const KiB = 1024
const MiB = 1024 * KiB
const GiB = 1024 * MiB

/** 根下第一段目录名 → 中文标签。未知键原样显示（不藏数据）。 */
const TYPE_LABELS: Record<string, string> = {
  single: '单文件',
  batch: '批次',
  '': '根目录散文件',
}

/**
 * 边界（三个数都是本轮现量，非推测）：
 * - 只会喂非负整数。实测 `usageBytesText(-1073741824)` = `'-1073741824 B'`（负数进不了
 *   KB/MB/GB 任何一档，因为每档比较只卡上界）、`usageBytesText(1023.6)` = `'1023.6 B'`。
 *   今天的载荷造不出这两态（`bytes` 来自 `st_size`、`diff` 来自 `abs()`），故不钉负数断言；
 *   但下一个消费者是 Task 9 的修复对话框，带符号差值正是有人会往里传的东西 —— 到时先加判据再喂。
 * - GB 是**故意的天花板**。实测 `usageBytesText(1024 ** 4)` = `'1024.00 GB'`，即 6 TiB 目录
 *   读成 `6144.00 GB`。别加 TB 档：sftp 的三个本地 `formatSize`（SftpBrowser.vue:510 /
 *   SftpStatsBar.vue:52 / SftpFileTable.vue:207）同样封到 GB 为止，四处保持一个顶。
 */
export function usageBytesText(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return '--'
  if (bytes < KiB) return `${bytes} B`
  if (bytes < MiB) return `${(bytes / KiB).toFixed(1)} KB`
  if (bytes < GiB) return `${(bytes / MiB).toFixed(1)} MB`
  return `${(bytes / GiB).toFixed(2)} GB`
}

export function usageChipText(usage: FileUsage | null): string | null {
  if (!usage) return null
  return `磁盘占用 ${usageBytesText(usage.bytes)} · ${usage.file_count.toLocaleString()} 个文件`
}

export interface UsageRow {
  label: string
  sizeText: string
  countText: string
}

export function usageBreakdownRows(usage: FileUsage | null): UsageRow[] {
  if (!usage) return []
  // by_type 不加 `?? {}`：后端四个环节都保证键必在（_scan_tree 先置 {} 并无条件返回、
  // _compute_usage 逐字复制、视图无 serializer 过滤、缓存进程内不重新序列化），
  // FileUsage 里它又是必填字段。仓规：不为不可能的状态写兜底（详见 storage_usage.py）。
  return Object.entries(usage.by_type)
    .sort((a, b) => b[1].bytes - a[1].bytes)
    .map(([key, bucket]) => ({
      // own-property 查表，不要退回 `TYPE_LABELS[key] ?? key`：`??` 只挡 null/undefined，
      // 而一级目录名可以是 constructor/toString/hasOwnProperty/__proto__（_scan_tree 按路径
      // 第一段建桶），这几个键会从原型取到 Function/Object.prototype 并原样递成 label，
      // UsageRow.label 标 string 骗过 TS、静默显示「function toString(){…}」。
      // 同一条纪律的先例与理由见 utils/audit.ts:24-29 —— 本仓第二次踩，勿再抄第三遍。
      label: Object.hasOwn(TYPE_LABELS, key) ? TYPE_LABELS[key] : key,
      sizeText: usageBytesText(bucket.bytes),
      countText: `${bucket.count.toLocaleString()} 个文件`,
    }))
}

export function usageOutsideLine(usage: FileUsage | null): string | null {
  if (!usage || usage.db_outside_root_count <= 0) return null
  return `另有 ${usage.db_outside_root_count.toLocaleString()} 条记录的文件不在数据目录内（${usageBytesText(usage.db_outside_root_bytes)}）`
}

/**
 * 只陈述事实、不带按钮（计划订正③）：产品里没有任何路径会回写 file_size，
 * 所以「重新扫描」修不好这一行，写成动作就是谎话。
 */
export function usageMismatchLine(usage: FileUsage | null): string | null {
  if (!usage || !usage.mismatch_over_threshold) return null
  return `清单与磁盘不一致（差 ${usageBytesText(usage.mismatch_diff_bytes)}）：清单里的文件大小是导入当时的快照，此后不刷新`
}

/**
 * 返回浮层「统计时间」那一行的 **value**，不带前缀：那一行的 label 由调用方
 * （Task 7 的 `el-descriptions-item label="统计时间"`）给，值再自带前缀就读成
 * 「统计时间：统计时间 2026-11-14 …」。
 * 不对称的是 `usageMismatchLine` —— 它没有 label 可挂，所以自带整句。
 *
 * 这里也**故意不复用 `utils/format.ts` 的 `formatTime`**（两个理由都现量过）：
 * 1. `formatTime` 是 MM-DD HH:mm 短形态，实测 `formatTime('2026-11-14T23:07:08+00:00')`
 *    = `'11/15 07:07'` —— 没有年份，作为「统计时间」绝对值会跨年读错。
 * 2. `formatTime` 内部 `TIME_FMT.format(new Date(val))`，实测 `formatTime('not-a-date')`
 *    抛 `RangeError: Invalid time value`；下面那道 `Number.isNaN` 守卫就是为了不把它冒到界面。
 */
export function usageScannedText(usage: FileUsage | null): string | null {
  if (!usage || !usage.scanned_at) return null
  const date = new Date(usage.scanned_at)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleString('zh-CN', { hour12: false })
}
