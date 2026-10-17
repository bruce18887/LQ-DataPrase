import { ref, type Ref, type ComputedRef } from 'vue'
import type { GridApi, GridReadyEvent } from 'ag-grid-community'

/**
 * 固定 Bin 列 fail 单元的右键菜单逻辑。
 *
 * 触发条件（与后端 fail 语义 `pd.to_numeric(bin) != 1` 镜像）：
 * 右键落在固定列容器中、列名 == **Bin 列**、且单元格值 Number() != 1。
 * 其余右键路径（表头 / 其他单元格）一律放行，保留浏览器复制菜单。
 *
 * ⚠ Bin 列名必须由调用方显式给（后端 page==1 的 bin_column），不能用
 * 「哪个列被固定了」反推 —— 固定列支持多选后，右键序列列会弹到 Bin 菜单上。
 *
 * @param binCol - 后端权威下发的 Bin 列名（菜单只对它的 fail 单元格生效；它没被固定时
 *                 右键落不进固定列容器，自然不弹）
 * @param displayCols - 当前可见列（排除「隐藏列」与列搜索过滤），决定 fail 列能否被滚动定位
 */
export function useBinCellMenu(opts: {
  binCol: Ref<string>
  displayCols: ComputedRef<string[]>
}) {
  const { binCol, displayCols } = opts

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
    if (!colId || colId !== binCol.value) return false
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
    failCols.value = (node.data.__fail_cells__ ?? []) as string[]
    visible.value = true
    return true
  }

  /**
   * 定位到该行第一个可见的 fail 列并 flash 高亮。
   * 顺序不可反：先垂直再水平滚动（同步渲染目标行/列），随后 flashCells 才能拿到已渲染的 cell ctrl。
   * 仅 bin fail 的行目标列即 bin 列本身 → ensureColumnVisible 是 no-op，只 flash pinned 单元格。
   *
   * 垂直不传 position：菜单是在这一行上右键点出来的，它必然已在视口内，而 ag-grid 传
   * 'middle' 时无条件拉回居中（position 为空才只在行出视口时最小滚动，见
   * ag-grid GridBodyScrollFeature.ensureIndexVisible）。传了就等于每次跳转都把用户
   * 攒的滚动位置甩掉；水平仍用 'middle'——目标 fail 列在数百列文件里通常在屏幕外，
   * 居中才有上下文。
   */
  function goToFailCell(rowIdx: number) {
    const api = gridApi.value
    if (!api) return
    const node = api.getDisplayedRowAtIndex(rowIdx)
    if (!node) return
    close()
    const all = (node.data.__fail_cells__ ?? []) as string[]
    // __fail_cells__ 顺序：测试列在前、bin 列最后 → 第一个可见项即「第一个 fail 测试列」
    const visibleFailCols = all.filter((c) => displayCols.value.includes(c))
    const failCol = visibleFailCols[0] ?? binCol.value

    api.ensureNodeVisible(node)
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
