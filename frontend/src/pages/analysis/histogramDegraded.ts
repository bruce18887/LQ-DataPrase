/**
 * KDE 内存降级的界面提示文案（单一事实源）。
 *
 * 后端 `/analysis/histogram/` 的每个参数结果恒带 `degraded: string[]`
 * （apps/analysis/services/data_services/histogram.py:370）：`compute_histogram_stats`
 * 只捕获 KDE 的 `MemoryError`，撞上时把 `'kde_curve'`（全量曲线）或
 * `'filtered_kde_curve'`（IQR 裁剪曲线）append 进去，正常为空数组。
 * 换句话说「曲线没画出来」不是失败，而是服务端主动保住了其余统计量 ——
 * 界面要讲清楚的只有这一件事，不需要枚举是哪一条曲线。
 *
 * 未知 reason 也出同一句：判据是「非空即有降级」，将来后端加新的降级通道
 * （仍属「某条曲线被省掉」）时前端不必同步改文案。
 */
export const KDE_DEGRADED_HINT = '内存紧张，已省略 KDE 曲线'

/** 非空原因数组 → 提示文案；空 / 缺省（含非数组脏值）→ null（不出提示）。 */
export function histogramDegradedHint(reasons: string[] | null | undefined): string | null {
  if (!Array.isArray(reasons) || reasons.length === 0) return null
  return KDE_DEGRADED_HINT
}
