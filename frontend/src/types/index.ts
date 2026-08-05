export interface User {
  id: number
  username: string
  email: string
  display_name: string
  role: 'administrator' | 'user' | 'viewer'
}

export type ExportTypeKey =
  | 'to_excel' | 'to_csv' | 'sigma_limit' | 'html_report'
  | 'batch_charts' | 'batch_report' | 'buyoff' | 'gage'

export interface UserSettings {
  page_size: number
  chart_height: number
  table_height: number
  chart_dpi: number
  cpk_a_threshold: number
  cpk_b_threshold: number
  cpk_c_threshold: number
  chart_engine: string
  chart_renderer: 'svg' | 'canvas'
  export_filename_templates: Record<ExportTypeKey, string>
}

export interface DataFile {
  id: number
  filename: string
  format_type: string
  file_type: string
  batch_name: string
  sub_batch?: string
  row_count: number
  col_count: number
  program_name: string
  product_code?: string
  status: string
  created_at: string
  tags?: string[]
}

export interface DashboardMetrics {
  total_rows: number
  pass_count: number
  yield_pct: number
  format: string
}

export interface BinStat {
  bin: number | string
  count: number
  percentage: number
}

export interface SiteYield {
  site: string
  yield: string
  pass: number
  total: number
}

export interface FailTestItem {
  name: string
  fail_count: number
  percentage: number
}

/** 仪表板「测试项总览」：合并 CPK 参数表与 Fail 测试项明细（一行一个测试项） */
export interface TestItemOverview {
  name: string
  data_count: number
  mean: number | null
  std: number | null
  min: number | null
  max: number | null
  lsl: number | null
  usl: number | null
  cpk: number | null
  cpk_level: string | null
  cpk_color: string | null
  unit: string
  fail_count: number
  percentage: number
}
