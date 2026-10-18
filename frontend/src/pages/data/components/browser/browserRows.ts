import { markRaw } from 'vue'

export interface BrowsePagePayload {
  headers?: string[]
  data?: unknown[][]
  fail_cells?: string[][]
  borderline_cells?: string[][]
}

/**
 * /browse/ 传输格式 zip：headers + data（行值数组）+
 * fail_cells/borderline_cells（并行数组）→ ag-grid 行对象。
 *
 * markRaw 跳过 Vue 深响应式（68k×142 依赖追踪实测 +1.3GB 堆 + 5s 阻塞；
 * 块 ≤100 行成本已低）。
 */
export function zipBrowserRows(d: BrowsePagePayload): Record<string, any>[] {
  const cols = d.headers ?? []
  const vals = d.data ?? []
  const fails = d.fail_cells ?? []
  const borderlines = d.borderline_cells ?? []
  const rows = new Array<Record<string, any>>(vals.length)
  for (let i = 0; i < vals.length; i++) {
    const v = vals[i]
    const o: Record<string, any> = {
      __fail_cells__: fails[i] ?? [],
      __borderline_cells__: borderlines[i] ?? [],
    }
    for (let j = 0; j < cols.length; j++) o[cols[j]] = v[j]
    rows[i] = markRaw(o)
  }
  return rows
}
