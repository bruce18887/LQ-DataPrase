/**
 * 颜色系统 - 工业技术深色专业风格
 * 参考 GitHub Dark, VS Code 设计语言
 */

// 背景色
export const backgrounds = {
  primary: '#0d1117',    // 主背景色 - 最深层
  secondary: '#161b22',  // 次级背景色 - 卡片/面板
  tertiary: '#21262d',   // 三级背景色 - 悬停/激活状态
} as const;

// 边框色
export const borders = {
  default: '#30363d',    // 默认边框色
  muted: '#21262d',      // 弱化边框色
  emphasis: '#6e7681',   // 强调边框色
} as const;

// 文本色
export const text = {
  primary: '#e6edf3',    // 主文本色 - 高对比度
  secondary: '#7d8590',  // 次级文本色 - 中等对比度
  tertiary: '#484f58',   // 三级文本色 - 低对比度/禁用
  inverse: '#0d1117',    // 反色文本 - 用于亮色背景
} as const;

// 品牌色
export const brand = {
  primary: '#58a6ff',    // 主品牌色 - 蓝色
  secondary: '#f78166',  // 次级品牌色 - 橙色
  primaryHover: '#79c0ff',   // 主品牌色悬停
  secondaryHover: '#ffa28b', // 次级品牌色悬停
} as const;

// 语义色
export const semantic = {
  success: '#3fb950',      // 成功 - 绿色
  successEmphasis: '#2ea043',
  warning: '#d29922',      // 警告 - 黄色
  warningEmphasis: '#bb8009',
  error: '#f85149',        // 错误 - 红色
  errorEmphasis: '#da3633',
  info: '#58a6ff',         // 信息 - 蓝色
  infoEmphasis: '#1f6feb',
} as const;

// 导出所有颜色
export const colors = {
  backgrounds,
  borders,
  text,
  brand,
  semantic,
} as const;

export default colors;
