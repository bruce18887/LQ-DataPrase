/**
 * 块缓存预算纯函数：把「驻留多少单元格」变成 ag-grid 无限滚动两个参数的唯一来源。
 *
 * /browse/ 单页最大约 3 MB、千列文件的行对象按列数膨胀，写死的
 * `maxBlocksInCache=20` 在多网格驻留下会把渲染进程推到 OOM。这里按
 * docs/reference/renderer-memory-baseline-2026-10-22.md §6 的实测单价封顶。
 * 无副作用，供 DataBrowserAgGrid（Task 4）接入。
 */

export const BLOCK_SIZE_MIN = 50
export const BLOCK_SIZE_MAX = 500
/** 列数未知时按历史基线宽度处理（142 列，见 docs/reference/perf-baseline-2026-10-17.md） */
export const DEFAULT_COL_COUNT = 142
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
