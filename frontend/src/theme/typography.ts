/**
 * 排版常量（TS 侧）
 *
 * 单一事实来源是 `styles/design-tokens.css`：字体栈与字号档位在那边，本文件只把
 * ECharts 这类「必须给 JS 数值」的消费方接过去，不得自行发明档位。
 * 两边的一致性由 e2e/global/fonts.spec.ts 断言（CSS token ↔ 本文件数值）。
 */

// 与 design-tokens.css 的 --font-sans / --font-mono 完全一致
export const fontFamily = {
  sans: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Noto Sans CJK SC', 'Source Han Sans SC', 'Helvetica Neue', Arial, sans-serif",
  mono: "'SF Mono', 'Cascadia Mono', 'Consolas', 'Liberation Mono', 'Menlo', 'Courier New', monospace",
} as const;

// ECharts 的 fontSize 只吃数值，所以这里用 px 数字而非 token 里的 rem 档位。
// 每个值都必须等于注释标出的那档 --p-fs-*（design-tokens.css:40-41）。
export const chartFontSize = {
  axis: 11,   // --p-fs-xs
  body: 12,   // --p-fs-sm
  title: 16,  // --p-fs-lg
} as const;
