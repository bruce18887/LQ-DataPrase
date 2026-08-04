import { ref, type Ref, type ComputedRef } from 'vue'
import type { GridApi, GridReadyEvent } from 'ag-grid-community'

/**
 * 固定 Bin 列 fail 单元格的右键菜单逻辑。
 *
 * 触发条件（与后端 fail 语义 `pd.to_numeric(bin) != 1` 镜像）：
 * 右键落在固定列容器中、列名 == pinnedCol、且单元格值 Number() != 1。
 * 其余右键路径（表头 / 其他单元格）一律放行，保留浏览器复制菜单。
 *
 * @param pinnedCol - 当前固定（第一列）的列名，菜单只对它的 fail 单元格生效
 * @param displayCols - 当前可见列（排除「隐藏列」与列搜索过滤），决定 fail 列能否被滚动定位
 */
export function useBinCellMenu(opts: {
  pinnedCol: Ref<string>
  displayCols: ComputedRef<string[]>
}) {
  const { pinnedCol, displayCols } = opts

  const gridApi = ref<GridApi | null>(null)

  // 菜单状态（x/y 为右键点 clientX/clientY，由菜单组件做视口夹紧）
  const visible = ref(false)
  const x = ref(0)
  const y = ref(0)
  const rowIndex = ref(-1)
  const binValue = ref<string | number | null>(null)
  const failCols = ref<string[]>([])

  function onGridReady(e: GridReadyEvent) {
    gridApi.value = e.api
  }

  function close() {
    visible.value = false
  }

  /**
   * 处理 body 单元格右键。命中（固定列 fail 单元格）→ preventDefault + 弹出菜单，返回 true；
   * 未命中 → 放行浏览器默认菜单，返回 false。
   */
  function handleBodyContextMenu(e: MouseEvent): boolean {
    close()
    const cell = (e.target as HTMLElement).closest(
      '.ag-pinned-left-cols-container .ag-cell',
    ) as HTMLElement | null
    if (!cell) return false
    const colId = cell.getAttribute('col-id')
    if (!colId || colId !== pinnedCol.value) return false
    const idx = Number(cell.closest('.ag-row')?.getAttribute('row-index'))
    if (!Number.isInteger(idx) || idx < 0) return false
    const node = gridApi.value?.getDisplayedRowAtIndex(idx)
    const value = node?.data?.[colId]
    if (!node || Number(value) === 1) return false // 值 == 1 为 pass，不弹

    e.preventDefault()
    x.value = e.clientX
    y.value = e.clientY
    rowIndex.value = idx
    binValue.value = value ?? null
    failCols.value = JSON.parse(node.data.__fail_cells__ ?? '[]') as string[]
    visible.value = true
    return true
  }

  /**
   * 定位到该行第一个可见的 fail 列并 flash 高亮。
   * 顺序不可反：先垂直再水平滚动（同步渲染目标行/列），随后 flashCells 才能拿到已渲染的 cell ctrl。
   * 仅 bin fail 的行目标列即 bin 列本身 → ensureColumnVisible 是 no-op，只 flash pinned 单元格。
   */
  function goToFailCell(rowIdx: number) {
    const api = gridApi.value
    if (!api) return
    const node = api.getDisplayedRowAtIndex(rowIdx)
    if (!node) return
    close()
    const all = JSON.parse(node.data.__fail_cells__ ?? '[]') as string[]
    // __fail_cells__ 顺序：测试列在前、bin 列最后 → 第一个可见项即「第一个 fail 测试列」
    const visibleFailCols = all.filter((c) => displayCols.value.includes(c))
    const failCol = visibleFailCols[0] ?? pinnedCol.value

    api.ensureNodeVisible(node, 'middle')
    api.ensureColumnVisible(failCol, 'middle')
    if (visibleFailCols.length) {
      // 同一 tick 内 ensure* 已同步渲染目标单元格
      api.flashCells({ rowNodes: [node], columns: [failCol] })
    } else {
      // 所有 fail 列都被隐藏 → 整行 flash（传隐藏列会 warning 且不闪）
      api.flashCells({ rowNodes: [node] })
    }
  }

  return {
    gridApi,
    visible,
    x,
    y,
    rowIndex,
    binValue,
    failCols,
    onGridReady,
    close,
    handleBodyContextMenu,
    goToFailCell,
  }
}
