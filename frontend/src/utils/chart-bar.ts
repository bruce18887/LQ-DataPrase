/**
 * 柱状图小百分比显示工具（回归：tiny-fail-bar）
 *
 * 后端把百分比保留到 6 位小数后，0.002%（1/50000）在固定 0-100 的 Y 轴上
 * 仍是亚像素、肉眼不可见。策略：非零柱渲染高度保底 MIN_BAR_HEIGHT_PCT
 * （约 2px），真实值存 data[2] 供 tooltip/标签显示；显示精度自适应，
 * 更小的值（0.001%、0.0001%）也不显示成 "0.00%" 之类的假零。
 */

/** 非零柱最小渲染高度（Y 轴百分比单位的 0.5% ≈ 450px 图表上的 2.25px） */
export const MIN_BAR_HEIGHT_PCT = 0.5

/**
 * 柱值钳制：非零值保底到最小可见高度，零值保持 0（零柱不应出现）。
 * 返回钳制后的渲染值 —— 真实值需另行存放（data[2]）供 tooltip 使用。
 */
export function clampBarValue(v: number): number {
  return v > 0 ? Math.max(v, MIN_BAR_HEIGHT_PCT) : 0
}

/**
 * 自适应精度百分比显示：>=1% 显示 2 位小数；更小值显示到 6 位小数并去尾零。
 * - 0.002 → "0.002"  0.001 → "0.001"  0.00001 → "0.00001"
 * - 不用固定 toFixed(4)：0.00001 会显示成 "0.0000%" 看起来像零
 */
export function formatPercent(v: number): string {
  if (v >= 1) return v.toFixed(2)
  return v.toFixed(6).replace(/0+$/, '').replace(/\.$/, '')
}
