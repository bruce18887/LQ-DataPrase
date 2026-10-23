/**
 * 块缓存预算纯函数：把「驻留多少单元格」变成 ag-grid 无限滚动两个参数的唯一来源。
 *
 * /browse/ 单页最大约 3 MB、千列文件的行对象按列数膨胀，写死的
 * `maxBlocksInCache=20` 在多网格驻留下会把渲染进程推到 OOM。这里按
 * docs/reference/renderer-memory-baseline-2026-10-22.md §6 的实测单价封顶。
 * 无副作用，供 DataBrowserAgGrid（Task 4）接入。
 */

/**
 * 50/500 与 `composables/useIrmSizing.ts:31-32` 的同名本地常量重复是**刻意的**，别"去重"：
 * 那边是设置页可取域（TableSettingsForm 下拉端点），这边是内存钳位域，两者语义不同、
 * 各自独立变化（Task 4 只 import 下面两个函数，不 import 这两个常数）。
 * 这两处同名常数由 `test/backend/test_page_size_bounds.py` 的并集扫描钉住（必须等于后端钳位区间）。
 */
export const BLOCK_SIZE_MIN = 50
export const BLOCK_SIZE_MAX = 500
/**
 * ⚠ 「列数未知时本文件两个函数都完全不介入」（`cols()` 返回 0 ⇒ 各自提前返回设置值 /
 * `MAX_BLOCKS`）：这里不提供任何按某个默认列数估算的回退 —— 对 `effectiveBlockSize`
 * 而言回退会在 `col_count` 还没加载时静默压低所有文件的分页大小。
 *
 * 但也**别把这句读成「列数未知就永远不会封顶」**：驻留那一半的回退住在调用方
 * `composables/useIrmSizing.ts` 的 `retentionColCount`（col_count 未知 ⇒ 用首块 `/browse/`
 * 实际返回的列宽），那是缓存尺寸决策、不改分页语义（2026-10-23 收口评审 A-2）。
 * 两层各由 `test/unit/blockCap.spec.ts` 与 `test/unit/useIrmSizing.spec.ts` 分开钉。
 * 窄文件的参考宽度 142（历史基线形状，见 docs/reference/perf-baseline-2026-10-17.md）
 * 只是单测素材，已从本文件移回 `blockCap.spec.ts` —— 生产源码里不留「注释写着别接线」的夹具。
 */
/** 驻留块数上限：今天 DataBrowserAgGrid 写死的值，窄文件必须保持不变 */
export const MAX_BLOCKS = 20
/** 单块格数上限 = 驻留预算 / 4 ⇒ 最坏情况仍驻留 4 块；推导见 baseline 文档 */
export const CELL_PER_BLOCK_MAX = 355_029
/** 驻留格数预算 = 48 MiB ÷ 3.38e-5 MiB/格（Task 1 探针实测，分母 86,400 格/块） */
export const CELL_RETAIN_BUDGET = 1_420_118

function cols(colCount: number | null | undefined): number {
  return colCount && colCount > 0 ? colCount : 0
}

/**
 * 实际每块行数：用户设置的每页行数，被「单块格数预算」按列数压低。
 * 列数未知 ⇒ 不压（保持设置值），因为压低会静默改变分页语义。
 */
export function effectiveBlockSize(
  settingsPageSize: number,
  colCount: number | null | undefined,
): number {
  const size = Math.max(BLOCK_SIZE_MIN, Math.min(BLOCK_SIZE_MAX, settingsPageSize || BLOCK_SIZE_MIN))
  const c = cols(colCount)
  if (!c) return size
  const byCells = Math.floor(CELL_PER_BLOCK_MAX / c)
  return Math.max(BLOCK_SIZE_MIN, Math.min(size, byCells))
}

/**
 * 缓存块数上限。注意 ag-grid 实际保留 `cap - 1` 块（`purgeBlocksIfNeeded` 的 `blocksToKeep`），
 * 且当前显示块永不驱逐，所以这里给的是上限而非精确驻留数。
 */
export function maxBlocksInCache(
  blockSize: number,
  colCount: number | null | undefined,
): number {
  const c = cols(colCount)
  if (!c) return MAX_BLOCKS
  const cellsPerBlock = Math.max(1, blockSize * c)
  return Math.max(1, Math.min(MAX_BLOCKS, Math.floor(CELL_RETAIN_BUDGET / cellsPerBlock)))
}
