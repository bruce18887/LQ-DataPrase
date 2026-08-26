export interface User {
  id: number
  username: string
  email: string
  display_name: string
  role: 'administrator' | 'user' | 'viewer'
}

export type ExportTypeKey =
  | 'to_excel' | 'to_csv' | 'sigma_limit' | 'html_report'
  | 'batch_charts' | 'batch_report' | 'buyoff' | 'gage' | 'file_correlation'

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
  export_timeout: number
  default_hidden_columns: string[]
}

/** 系统设置页完整设置项（GET/PUT /auth/settings/ 的载荷）。 */
export interface SettingsData {
  page_size: number
  chart_height: number
  table_height: number
  chart_dpi: number
  cpk_a_threshold: number
  cpk_b_threshold: number
  cpk_c_threshold: number
  chart_engine: string
  chart_renderer: 'svg' | 'canvas'
  aggrid_header_font_size: number
  recent_files: Array<{ id: number; name: string; accessed_at: string }>
  max_recent_files: number
  histogram_label_offset: number
  export_filename_templates: Record<ExportTypeKey, string>
  export_timeout: number
  /** 默认隐藏列（记录级列名）：导出 Excel 与查看数据 ag-grid 共用 */
  default_hidden_columns: string[]
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
  /** 文件字节数（DataFileListSerializer 已返回，FileSelect 富信息行展示用） */
  file_size?: number
  /** 源文件磁盘修改时间 */
  source_mtime?: string | null
  format_type_display?: string
  status_display?: string
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

export interface StageYield {
  stage: string
  file_count: number
  total: number
  pass_count: number
  fail_count: number
  yield_pct: number
}

export interface PhaseSummary {
  phase: string
  stage: string
  file_count: number
  total: number
  pass_count: number
  fail_count: number
  yield_pct: number
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

/** 文件相关性对比：LSL/USL Diff 标红规则（A: 差值全为0才pass 默认 / B: B的limit不更紧才pass） */
export type DiffRule = 'zero' | 'wider'

/** 文件相关性对比：单个序列的 ATE/Bench/Delta/%Diff 单元格 */
export interface FileCorrelationCell {
  serial: number
  ate: number | null
  bench: number | null
  delta: number | null
  diff_pct: number | null
  fail: boolean
}

/** 文件相关性对比：单个测试项行（模板风格：limit 列 + 每序列数据块） */
export interface FileCorrelationRow {
  param: string
  unit: string
  lsl_a: number | null
  usl_a: number | null
  lsl_b: number | null
  usl_b: number | null
  lsl_diff: number | null
  usl_diff: number | null
  lsl_fail: boolean
  usl_fail: boolean
  compared: number
  fail_count: number
  pass_rate: number
  max_diff: number
  cells: FileCorrelationCell[]
}

/** 文件相关性对比：汇总统计 */
export interface FileCorrelationTotals {
  params: number
  serials: number
  paired_cells: number
  fail_cells: number
  overall_pass_rate: number
}

/** 文件相关性对比：后端 /analysis/file_correlation/ 完整响应 */
export interface FileCorrelationResult {
  file1_name: string
  file2_name: string
  serials: number[]
  limits_only: boolean
  truncated: boolean
  params: string[]
  rows: FileCorrelationRow[]
  totals: FileCorrelationTotals
}

/** 文件相关性对比请求选项（与后端 FileCorrelationConfig 一一对应） */
export interface FileCorrelationOptions {
  threshold: number
  diffRule: DiffRule
  maxSerials: number
  ignoreNoLimit: boolean
  ignoreNoData: boolean
}
