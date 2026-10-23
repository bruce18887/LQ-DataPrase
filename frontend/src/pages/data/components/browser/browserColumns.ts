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

/**
 * ── ag-grid 的三块自包含选项（2026-10-23 收口评审 C 项从 `DataBrowserAgGrid.vue` 搬来）──
 * 搬动理由只有容量：那个 .vue 贴在 600 行硬上限上（项目约定），这里已经是网格列/样式配置的
 * 归属地。**纯搬迁，一个字节的行为都没改**：`defaultColDef` 与 `rowClassRules` 在组件里仍然
 * 只构造一次（身份稳定是承重的 —— ag-grid 对这两块 prop 的变化会重算列/重绘行），
 * 主题与高亮状态一律用 getter/回调现读，闭包语义与搬迁前逐字相同。
 */

/**
 * `defaultColDef`：`isDark` 传取值函数而不是布尔，`cellStyle` 每次求值时现读主题
 * （红/橙两档各有一套 light/night 取值，见上面那四个常量）。
 */
export function buildBrowserDefaultColDef(isDark: () => boolean) {
  return {
    editable: false,
    sortable: true,
    resizable: true,
    // 服务端列过滤（方案 A）：apply/reset 按钮——避免每敲一键就触发整页重载（官方推荐服务端场景）
    filterParams: { buttons: ['apply', 'reset'] },
    wrapHeaderText: true,
    autoHeaderHeight: true,
    // 红/橙规则住在本文件（T2 纯函数）；这里只注入主题
    cellStyle: (params: any) => browserCellStyle(params, isDark()),
  }
}

/** 工具栏「列宽」下拉 → ag-grid `autoSizeStrategy`（`none` = undefined，交给列自带宽） */
export function buildBrowserAutoSizeStrategy(mode: string) {
  if (mode === 'fitCellContents') {
    return { type: 'fitCellContents', skipHeader: false } as any
  }
  if (mode === 'fitGridWidth') {
    return { type: 'fitGridWidth' } as any
  }
  return undefined
}

/**
 * 斑马行 + 右键高亮行；`isHighlighted` 由组件的 `useRowHighlight` 传入（状态不搬，只搬规则表）。
 * 参数类型沿用 `useRowHighlight.isHighlighted(rowIndex: number | null | undefined)` ——
 * IRM 滚动窗口外的行 `node.rowIndex` 会是 undefined，收窄成 `number` 就是改行为。
 */
export function buildBrowserRowClassRules(
  isHighlighted: (rowIndex: number | null | undefined) => boolean,
) {
  return {
    'row-even': (params: any) => params.node.rowIndex % 2 === 0,
    'row-odd': (params: any) => params.node.rowIndex % 2 !== 0,
    'row-highlight': (params: any) => isHighlighted(params.node.rowIndex),
  }
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
