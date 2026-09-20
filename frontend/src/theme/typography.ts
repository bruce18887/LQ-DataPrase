/**
 * 排版常量（TS 侧）
 *
 * 单一事实来源是 `styles/design-tokens.css`：字体栈与字号九档在那边，本文件只把
 * ECharts 这类「必须给 JS 数值」的消费方接过去，不得自行发明档位。
 * 两边的一致性由 e2e/global/fonts.spec.ts 断言（CSS token ↔ 本文件数值）。
 */

// 与 design-tokens.css 的 --font-sans / --font-mono 完全一致
export const fontFamily = {
  sans: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Noto Sans CJK SC', 'Source Han Sans SC', 'Helvetica Neue', Arial, sans-serif",
  mono: "'SF Mono', 'Cascadia Mono', 'Consolas', 'Liberation Mono', 'Menlo', 'Courier New', monospace",
} as const;

/**
 * 字号九档的 TS 镜像。键名与 --p-fs-<键> 一致（ECharts 的 fontSize 只吃数字，
 * 所以只能镜像值、不能引用 CSS 变量）。改 design-tokens.css 那边必须同步这里，
 * 否则 fonts.spec 的「TS ↔ CSS」用例会红。
 */
export const chartFontSize = {
  micro: 11,
  dense: 12,
  small: 13,
  base: 14,
  lead: 16,
  title: 18,
  headline: 22,
  display: 26,
  hero: 32,
} as const;
