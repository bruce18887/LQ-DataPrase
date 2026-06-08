export interface User {
  id: number
  username: string
  email: string
  display_name: string
  role: 'administrator' | 'user' | 'viewer'
}

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
