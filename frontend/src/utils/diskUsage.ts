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
  return Object.entries(usage.by_type ?? {})
    .sort((a, b) => b[1].bytes - a[1].bytes)
    .map(([key, bucket]) => ({
      label: TYPE_LABELS[key] ?? key,
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
 */
export function usageScannedText(usage: FileUsage | null): string | null {
  if (!usage || !usage.scanned_at) return null
  const date = new Date(usage.scanned_at)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleString('zh-CN', { hour12: false })
}
