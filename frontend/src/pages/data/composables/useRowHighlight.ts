import { computed, ref } from 'vue'

/**
 * 查看数据表格的行高亮状态 + 右键菜单。
 *
 * 键是 ag-grid 的显示行索引：同一排序/筛选下滚动来回不丢；
 * 排序、列筛选、换文件时调用 clear()（行序已变，旧索引不再指向原行）。
 * 交互是右键序列号 → 菜单 → 高亮/取消；不再用左键直接切换。
 */
export function useRowHighlight() {
  const highlightedRows = ref<Set<number>>(new Set())

  const count = computed(() => highlightedRows.value.size)

  // 右键菜单状态（x/y 为右键点 clientX/clientY，由菜单组件做视口夹紧）
  const menuVisible = ref(false)
  const menuX = ref(0)
  const menuY = ref(0)
  const menuRowIndex = ref(-1)
  const menuSerialValue = ref('')

  function isHighlighted(rowIndex: number | null | undefined): boolean {
    return typeof rowIndex === 'number' && highlightedRows.value.has(rowIndex)
  }

  /** 切换一行；返回切换后是否处于高亮态 */
  function toggle(rowIndex: number): boolean {
    if (!Number.isInteger(rowIndex) || rowIndex < 0) return false
    const next = new Set(highlightedRows.value)
    const on = next.has(rowIndex)
    if (on) {
      next.delete(rowIndex)
    } else {
      next.add(rowIndex)
    }
    // 重新赋值而不是原地 mutate：rowClassRules 的闭包读同一个 ref，
    // 原地改 Set 不会触发依赖更新。
    highlightedRows.value = next
    return !on
  }

  function openMenu(rowIndex: number, serialValue: unknown, x: number, y: number) {
    if (!Number.isInteger(rowIndex) || rowIndex < 0) return
    menuRowIndex.value = rowIndex
    menuSerialValue.value = serialValue == null ? '' : String(serialValue)
    menuX.value = x
    menuY.value = y
    menuVisible.value = true
  }

  function closeMenu() {
    menuVisible.value = false
  }

  /** 菜单项：切换当前菜单行并关闭菜单；返回切换后是否高亮 */
  function toggleMenuRow(): boolean {
    const idx = menuRowIndex.value
    const on = toggle(idx)
    closeMenu()
    return on
  }

  function clear() {
    closeMenu()
    if (highlightedRows.value.size) highlightedRows.value = new Set()
  }

  return {
    highlightedRows,
    count,
    isHighlighted,
    toggle,
    clear,
    menuVisible,
    menuX,
    menuY,
    menuRowIndex,
    menuSerialValue,
    openMenu,
    closeMenu,
    toggleMenuRow,
  }
}
