/**
 * 查看数据 ag-grid 的列定义与单元格着色（纯函数，T2 直接单测）。
 *
 * 着色优先级：红（__fail_cells__：bin!=1 且严格越限）> 橙
 * （__borderline_cells__：bin!=1 且值恰好等于真规格窗端点）> 无。
 * 两套数组都由 /browse/ 与 data 并行下发。
 */

export interface BrowserColMeta {
  unit: string
  min: string
  max: string
}

export interface BrowserRowData {
  __fail_cells__?: string[]
  __borderline_cells__?: string[]
}

export interface BrowserCellStyleParams {
  data?: BrowserRowData | null
  colDef?: { field?: string }
}

export type BrowserCellStyle = Record<string, string> | null

const RED_LIGHT: BrowserCellStyle = {
  backgroundColor: 'var(--error-2)',
  color: '#ffffff',
  fontWeight: 'bold',
}
const RED_DARK: BrowserCellStyle = {
  backgroundColor: '#b91c1c',
  color: '#fecaca',
  fontWeight: 'bold',
}
// 亮橙 + 深字：light/dark 都保持 ≥4.5:1 对比度，同时与红色明确区分
const ORANGE_LIGHT: BrowserCellStyle = {
  backgroundColor: '#f59e0b',
  color: '#451a03',
  fontWeight: 'bold',
}
const ORANGE_DARK: BrowserCellStyle = {
  backgroundColor: '#f9a825',
  color: '#451a03',
  fontWeight: 'bold',
}

export function browserCellStyle(
  params: BrowserCellStyleParams,
  isDark: boolean,
): BrowserCellStyle {
  const field = params.colDef?.field
  if (!params.data || !field) return null
  if ((params.data.__fail_cells__ ?? []).includes(field)) {
    return isDark ? RED_DARK : RED_LIGHT
  }
  if ((params.data.__borderline_cells__ ?? []).includes(field)) {
    return isDark ? ORANGE_DARK : ORANGE_LIGHT
  }
  return null
}

export interface BuildBrowserColumnDefsOptions {
  displayCols: string[]
  colMeta: Record<string, BrowserColMeta>
  numericColumns: string[]
  defaultHiddenCols: string[]
  pinnedCols: string[]
  highlightTriggerCol: string
}

export function buildBrowserColumnDefs(opts: BuildBrowserColumnDefsOptions): any[] {
  const defs: any[] = []
  for (const col of opts.displayCols) {
    const meta = opts.colMeta[col]
    let header = col
    if (meta) {
      const parts = [col]
      if (meta.unit && meta.unit !== '-' && meta.unit !== 'None') {
        parts.push(` (${meta.unit})`)
      }
      if (meta.min !== '' || meta.max !== '') {
        parts.push(` [${meta.min || '-'}, ${meta.max || '-'}]`)
      }
      header = parts.join('')
    }

    const colDef: any = {
      field: col,
      headerName: header,
      // 服务端列过滤（方案 A）：数值列挂 number filter（等/不等/大于/小于/区间），
      // 其余挂 text filter（包含/开头/结尾）——IRM 下 filter 类型必须显式指定
      filter: opts.numericColumns.includes(col) ? 'agNumberColumnFilter' : 'agTextColumnFilter',
    }
    if (opts.defaultHiddenCols.includes(col)) {
      colDef.hide = true
    }
    if (opts.pinnedCols.includes(col)) {
      colDef.pinned = 'left'
    }
    if (opts.highlightTriggerCol && col === opts.highlightTriggerCol) {
      colDef.cellClass = 'row-highlight-trigger'
      colDef.headerTooltip = '右键序列号可高亮/取消高亮该行'
    }
    defs.push(colDef)
  }

  defs.push({
    field: '__fail_cells__',
    headerName: '',
    hide: true,
  })

  return defs
}

export function headerMenuCopyLabel(isSystemCol: boolean): string {
  return isSystemCol ? '复制列名' : '复制测试项名字'
}

export interface BrowserDisplayCols {
  systemCols: string[]
  testCols: string[]
  displayCols: string[]
}

/**
 * 显示列：系统列恒显示且前置；选中测试列非空时只显示选中的，
 * 空集 = 全部测试列。列序保持文件序。
 */
export function resolveDisplayCols(
  allCols: string[],
  systemCols: string[],
  selectedTestCols: string[],
): BrowserDisplayCols {
  const sys: string[] = []
  const tests: string[] = []
  for (const c of allCols) {
    if (systemCols.includes(c)) sys.push(c)
    else tests.push(c)
  }
  const shown = selectedTestCols.length
    ? tests.filter((c) => selectedTestCols.includes(c))
    : tests
  return { systemCols: sys, testCols: tests, displayCols: [...sys, ...shown] }
}
