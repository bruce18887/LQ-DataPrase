import type { Ref } from 'vue'
import type { GridApi } from 'ag-grid-community'

/**
 * 查看数据表格的统一右键路由：
 * 表头 → 表头菜单；序列号单元格 → 行高亮菜单；Bin fail 单元格 → 定位菜单；
 * 其余单元格放行浏览器原生菜单。
 */
export function useGridContextMenus(opts: {
  allCols: Ref<string[]>
  highlightTriggerCol: Ref<string>
  gridApi: Ref<GridApi | null>
  closeBinMenu: () => void
  closeHeaderMenu: () => void
  closeRowHighlightMenu: () => void
  openHeaderMenu: (col: string, e: MouseEvent) => void
  openRowHighlightMenu: (rowIndex: number, serialValue: unknown, x: number, y: number) => void
  handleBodyContextMenu: (e: MouseEvent) => boolean
}) {
  function onGridContextMenu(e: MouseEvent) {
    opts.closeBinMenu()
    opts.closeHeaderMenu()
    opts.closeRowHighlightMenu()

    const header = (e.target as HTMLElement).closest('.ag-header-cell')
    if (header) {
      e.preventDefault()
      const col = header.getAttribute('col-id')
      if (!col || !opts.allCols.value.includes(col)) return
      opts.openHeaderMenu(col, e)
      return
    }

    // 行高亮触发列（序列列）优先于 Bin fail 菜单；两者列名不同，不会同时命中
    const cell = (e.target as HTMLElement).closest('.ag-cell') as HTMLElement | null
    if (cell && opts.highlightTriggerCol.value
        && cell.getAttribute('col-id') === opts.highlightTriggerCol.value) {
      const idx = Number(cell.closest('.ag-row')?.getAttribute('row-index'))
      if (Number.isInteger(idx) && idx >= 0) {
        e.preventDefault()
        const node = opts.gridApi.value?.getDisplayedRowAtIndex(idx)
        opts.openRowHighlightMenu(
          idx,
          node?.data?.[opts.highlightTriggerCol.value] ?? '',
          e.clientX,
          e.clientY,
        )
        return
      }
    }

    opts.handleBodyContextMenu(e)
  }

  return { onGridContextMenu }
}
