/**
 * 主题系统入口
 * 统一导出所有主题配置
 */

export { typography, fontFamily, fontSize, fontWeight, lineHeight } from './typography';
export { spacing } from './spacing';

// 默认导出完整主题对象
import typography from './typography';
import spacing from './spacing';

export const theme = {
  typography,
  spacing,
} as const;

export default theme;
