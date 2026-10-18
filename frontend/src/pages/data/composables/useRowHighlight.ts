import { computed, ref } from 'vue'

/**
 * 查看数据表格的行高亮状态。
 *
 * 键是 ag-grid 的显示行索引：同一排序/筛选下滚动来回不丢；
 * 排序、列筛选、换文件时调用 clear()（行序已变，旧索引不再指向原行）。
 */
export function useRowHighlight() {
  const highlightedRows = ref<Set<number>>(new Set())

  const count = computed(() => highlightedRows.value.size)

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

  function clear() {
    if (highlightedRows.value.size) highlightedRows.value = new Set()
  }

  return { highlightedRows, count, isHighlighted, toggle, clear }
}
