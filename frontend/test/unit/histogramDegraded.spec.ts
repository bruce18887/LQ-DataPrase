import { describe, expect, it } from 'vitest'

import { histogramDegradedHint } from '../../src/pages/analysis/histogramDegraded'

/**
 * 后端 `/analysis/histogram/` 的每个参数结果恒带 `degraded: string[]`
 * （apps/analysis/services/data_services/histogram.py:370）：KDE 计算撞
 * `MemoryError` 时由服务侧 append `'kde_curve'` / `'filtered_kde_curve'`，
 * 正常为空数组。这里的判据只有两条：空/缺省不出提示；任何非空都出同一句
 * （未知 reason 也按同一句——文案讲的是「KDE 曲线被省略」，不含具体分支）。
 */
const HINT = '内存紧张，已省略 KDE 曲线'

describe('histogramDegradedHint', () => {
  it('空数组 / null / undefined 不出提示', () => {
    expect(histogramDegradedHint([])).toBeNull()
    expect(histogramDegradedHint(null)).toBeNull()
    expect(histogramDegradedHint(undefined)).toBeNull()
  })

  it('已知的两条 KDE 降级原因都出提示', () => {
    expect(histogramDegradedHint(['kde_curve'])).toBe(HINT)
    expect(histogramDegradedHint(['filtered_kde_curve'])).toBe(HINT)
  })

  it('未知 reason 与多条原因同样出同一句（文案不枚举分支）', () => {
    expect(histogramDegradedHint(['some_future_reason'])).toBe(HINT)
    expect(histogramDegradedHint(['kde_curve', 'filtered_kde_curve'])).toBe(HINT)
  })
})
