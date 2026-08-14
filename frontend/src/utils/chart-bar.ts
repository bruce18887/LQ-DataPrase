/**
 * 图表显示工具（柱状图小百分比 / 轴刻度 / 站点色板）
 *
 * 柱状图小百分比（回归：tiny-fail-bar）：后端把百分比保留到 6 位小数后，
 * 0.002%（1/50000）在固定 0-100 的 Y 轴上仍是亚像素、肉眼不可见。策略：
 * 非零柱渲染高度保底 MIN_BAR_HEIGHT_PCT（约 2px），真实值存 data[2] 供
 * tooltip/标签显示；显示精度自适应，更小的值（0.001%、0.0001%）也不
 * 显示成 "0.00%" 之类的假零。
 *
 * 轴刻度 formatAxisValue 与站点色板 SITE_COLORS_8（直方图基准，2026-08-13
 * 风格统一：所有分析图表共用同一套视觉 token）。
 */

/** 非零柱最小渲染高度（Y 轴百分比单位的 0.5% ≈ 450px 图表上的 2.25px） */
export const MIN_BAR_HEIGHT_PCT = 0.5

/**
 * 多系列 bar 分组偏移的边缘 pad：同一 value xAxis 上 N 个 bar 系列会被 ECharts
 * 分组错位排列（每系列柱宽 + barGap 间距），最左系列的第 0 点柱体（x=xAxis.min）
 * 与最右系列的最后点柱体（x=xAxis.max）会被挤出绘图区并被整根 clip 丢弃（回归：
 * edge-clip，8 site + AllSite 时实测最右柱右缘超界 13.6px@20% 柱宽）。调用方应将
 * 该量加到 xAxis.min/max 两端（数据单位）。
 *
 * 经验公式（实测拟合保守化）：超界 ≈ (N-1)/2 × 1.22 × 柱宽 - band/2，
 * 取 pad = max(0, (N-1) × gap × pct/100 - gap/4)，对 20%~100% 柱宽恒有余量。
 * 副作用：pad 会略微缩小 band 像素宽（20% 柱宽约 -4%，100% 约 -37%），
 * 不改变柱数据语义、markLine 位置与 outlier clip 过滤。
 */
export function getBarGroupPad(seriesCount: number, binGap: number, barWidthPercent: number): number {
  return Math.max(0, (seriesCount - 1) * binGap * (barWidthPercent / 100) - binGap / 4)
}

/**
 * 多系列柱组的最大柱宽上限（% of band）：N 系列柱组总宽 = w×(N-(N-1)×overlap)，
 * 必须 ≤ bin 宽（band），否则柱组横跨 bin 边界——贴限 bin（右边界 = USL）的
 * pass 柱会被画到 USL 右侧，看起来像超限（回归：limit-line-cross，用户报告 Vth）。
 * 上限 = floor(87/(N-(N-1)×overlap/100))%，柱组 ≤ 0.87×band 留余量。
 * overlapPercent = 柱体重合度 0-100（barGap 负值实现）：0 = 完全并排（旧行为），
 * 100 = 完全重合（单根柱视觉，柱宽自由）。调用方：
 * effectiveBarWidth = min(barWidthPercent, getMaxBarWidthPercent(N, overlapPercent))。
 */
export function getMaxBarWidthPercent(seriesCount: number, overlapPercent = 0): number {
  const denom = seriesCount - (seriesCount - 1) * (overlapPercent / 100)
  // floor 到整数：与柱宽 slider step=1 的刻度对齐（避免 9.66 之类非整数）
  return seriesCount > 1 && denom > 0 ? Math.floor(87 / denom) : 100
}

/**
 * 柱值钳制：非零值保底到最小可见高度，零值保持 0（零柱不应出现）。
 * 返回钳制后的渲染值 —— 真实值需另行存放（data[2]）供 tooltip 使用。
 */
export function clampBarValue(v: number): number {
  return v > 0 ? Math.max(v, MIN_BAR_HEIGHT_PCT) : 0
}

/**
 * 自适应精度百分比显示：默认 2 位小数（0.01% 精度）；仅当值小于 0.01%
 * 时逐级扩展小数位（0.00x% 格式），再小则以此类推，最多 6 位（后端
 * round 精度上限）。
 * - 0.12 → "0.12"  0.05 → "0.05"  0.005 → "0.005"  0.0005 → "0.0005"
 * - 不用固定 toFixed(6)：0.123305 会显示成 "0.123305"（6 位数字太多）；
 *   也不用固定 toFixed(4)：0.00001 会显示成 "0.0000%" 看起来像零
 */
export function formatPercent(v: number): string {
  if (v <= 0) return '0'
  let decimals = 2
  while (v < 10 ** -decimals && decimals < 6) decimals++
  return v.toFixed(decimals).replace(/0+$/, '').replace(/\.$/, '')
}

/**
 * 智能轴刻度格式（自 MultiFileChart 上提，2026-08-13 全图表统一）：
 * - 整数原样（10 → "10"）
 * - 非整数最多 4 位小数并去尾零（10.5 → "10.5"、12.34567 → "12.3457"）
 * - 避免浮点精度导致刻度过长（如 0.30000000000000004），也不像固定
 *   toFixed(4) 那样显示无意义的尾零（10.4500 → "10.45"）
 */
export function formatAxisValue(v: number): string {
  if (Number.isInteger(v)) return v.toString()
  const s = v.toFixed(4)
  return s.replace(/\.?0+$/, '')
}

/**
 * 站点系列 8 色板（直方图基准色，Site 1-8 逐一对应；2026-08-13 风格统一
 * 后所有分析图表共用；超过 8 个站点时按 % length 循环取色）
 *
 * 双主题：light 用 Tol muted（为 CVD 色盲设计，浅底安全）；night 用经
 * Machado 2009 色盲模拟验证的变体（protan/deutan ΔE≥15，深底对比度≥3）。
 * 用 getSiteColors8(isDark) 获取，勿直接引用常量（历史消费者已迁移）。
 */
export const SITE_COLORS_8_LIGHT: readonly string[] = [
  '#0077BB', '#EE7733', '#009988', '#CC3311',
  '#33BBEE', '#EE3377', '#BBBBBB', '#648FFF',
]
export const SITE_COLORS_8_NIGHT: readonly string[] = [
  '#ff9f43', '#4facfe', '#38ef7d', '#fdd835',
  '#f472b6', '#00f2fe', '#b45309', '#ffffff',
]
/** 按主题返回站点 8 色板 */
export function getSiteColors8(isDark: boolean): readonly string[] {
  return isDark ? SITE_COLORS_8_NIGHT : SITE_COLORS_8_LIGHT
}
// 兼容旧引用（浅色主题值）；新代码请使用 getSiteColors8
export const SITE_COLORS_8: readonly string[] = SITE_COLORS_8_LIGHT
