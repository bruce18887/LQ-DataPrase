/**
 * 图标映射
 * 从 @element-plus/icons-vue 导入并映射常用图标
 */

import {
  Odometer,
  Folder,
  TrendCharts,
  Setting,
  DataAnalysis,
  Connection,
  User,
} from '@element-plus/icons-vue';

// 图标映射对象
export const icons = {
  dashboard: Odometer,      // 仪表盘
  data: Folder,             // 数据管理
  analysis: TrendCharts,    // 数据分析
  settings: Setting,        // 设置
  batch: DataAnalysis,      // 批量处理
  sftp: Connection,         // SFTP 连接
  users: User,              // 用户管理
} as const;

export default icons;
