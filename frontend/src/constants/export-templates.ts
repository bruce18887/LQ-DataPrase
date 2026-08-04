/**
 * 导出文件名模板元数据（单一事实源）。
 *
 * 与后端 apps/common/export_naming.py 的 EXPORT_TEMPLATE_DEFAULTS /
 * EXPORT_TEMPLATE_VARIABLES 一一对应 —— 修改任何一侧必须同步另一侧。
 * 模板不含扩展名；扩展名由导出类型决定，渲染时自动追加。
 */

import type { ExportTypeKey } from '../types'

export interface ExportTemplateMeta {
  /** 设置页展示的中文名 */
  label: string
  /** 默认模板（后端 EXPORT_TEMPLATE_DEFAULTS 同值） */
  default: string
  /** 导出文件扩展名 */
  extension: string
  /** 可用变量（后端 EXPORT_TEMPLATE_VARIABLES 同值） */
  variables: string[]
}

export const EXPORT_TEMPLATE_VARIABLE_LABELS: Record<string, string> = {
  filename: '源文件名（去扩展名）',
  date: '日期 YYYYMMDD',
  time: '时间 HHMMSS',
  datetime: '时间戳 YYYYMMDD_HHMMSS',
  user: '用户名',
  sigma: 'Sigma 级别',
  batch_name: '批次名',
  file_count: '文件数量',
}

export const EXPORT_TEMPLATE_META: Record<ExportTypeKey, ExportTemplateMeta> = {
  to_excel: {
    label: 'Excel 数据导出',
    default: '{filename}_analysis',
    extension: 'xlsx',
    variables: ['filename', 'date', 'time', 'datetime', 'user'],
  },
  to_csv: {
    label: 'CSV 数据导出',
    default: '{filename}_data',
    extension: 'csv',
    variables: ['filename', 'date', 'time', 'datetime', 'user'],
  },
  sigma_limit: {
    label: 'Sigma Limit',
    default: '{filename}_{sigma}sigma_Limit',
    extension: 'xlsx',
    variables: ['filename', 'sigma', 'date', 'time', 'datetime', 'user'],
  },
  html_report: {
    label: 'HTML 报告',
    default: '{filename}_report',
    extension: 'html',
    variables: ['filename', 'date', 'time', 'datetime', 'user'],
  },
  batch_charts: {
    label: '批量图表',
    default: '{filename}_batch_charts',
    extension: 'xlsx',
    variables: ['filename', 'date', 'time', 'datetime', 'user'],
  },
  batch_report: {
    label: '批次报表',
    default: 'Batch_Report_{datetime}',
    extension: 'xlsx',
    variables: ['batch_name', 'file_count', 'date', 'time', 'datetime', 'user'],
  },
  buyoff: {
    label: 'Buyoff 表单',
    default: 'Buyoff_Form_{datetime}',
    extension: 'xlsx',
    variables: ['file_count', 'date', 'time', 'datetime', 'user'],
  },
  gage: {
    label: 'Gage 汇总',
    default: 'Gage_Summary_{datetime}',
    extension: 'xlsx',
    variables: ['file_count', 'date', 'time', 'datetime', 'user'],
  },
}

export const EXPORT_TEMPLATE_KEYS = Object.keys(EXPORT_TEMPLATE_META) as ExportTypeKey[]

/** 预览用样例值（与后端渲染规则一致：未知占位符保留原样） */
export const PREVIEW_SAMPLE_VALUES: Record<string, string> = {
  filename: 'DA35_20260804',
  date: '20260804',
  time: '123456',
  datetime: '20260804_123456',
  user: 'admin',
  sigma: '3',
  batch_name: 'BATCH_001',
  file_count: '5',
}
