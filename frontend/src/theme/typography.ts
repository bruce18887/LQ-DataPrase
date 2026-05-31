/**
 * 字体排版系统
 * 定义字体家族、大小、粗细和行高
 */

// 字体家族
export const fontFamily = {
  sans: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  mono: '"SF Mono", "Consolas", "Liberation Mono", "Menlo", "Courier New", monospace',
} as const;

// 字体大小
export const fontSize = {
  xs: '0.75rem',      // 12px
  sm: '0.875rem',     // 14px
  base: '1rem',       // 16px
  lg: '1.125rem',     // 18px
  xl: '1.25rem',      // 20px
  '2xl': '1.5rem',    // 24px
  '3xl': '1.875rem',  // 30px
  '4xl': '2.25rem',   // 36px
} as const;

// 字体粗细
export const fontWeight = {
  normal: '400',
  medium: '500',
  semibold: '600',
  bold: '700',
} as const;

// 行高
export const lineHeight = {
  tight: '1.25',
  normal: '1.5',
  relaxed: '1.75',
} as const;

// 导出所有排版配置
export const typography = {
  fontFamily,
  fontSize,
  fontWeight,
  lineHeight,
} as const;

export default typography;
