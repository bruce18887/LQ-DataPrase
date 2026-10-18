/**
 * T2：查看数据的行高亮状态。
 *
 * 键是 ag-grid 的**显示行索引**：同一排序/筛选下滚动来回不丢；
 * 排序、列筛选、换文件时由调用方 clear()（行序已变，旧索引不再指向原行）。
 */
import { describe, expect, it } from 'vitest'

import { useRowHighlight } from '../../src/pages/data/composables/useRowHighlight'

describe('useRowHighlight', () => {
  it('同一行第二次点击取消高亮', () => {
    const h = useRowHighlight()
    expect(h.toggle(3)).toBe(true)
    expect(h.isHighlighted(3)).toBe(true)
    expect(h.count.value).toBe(1)
    expect(h.toggle(3)).toBe(false)
    expect(h.isHighlighted(3)).toBe(false)
    expect(h.count.value).toBe(0)
  })

  it('支持多行同时高亮', () => {
    const h = useRowHighlight()
    h.toggle(0)
    h.toggle(5)
    h.toggle(9)
    expect(h.count.value).toBe(3)
    expect(h.isHighlighted(5)).toBe(true)
  })

  it('clear 清空全部', () => {
    const h = useRowHighlight()
    h.toggle(1)
    h.toggle(2)
    h.clear()
    expect(h.count.value).toBe(0)
    expect(h.isHighlighted(1)).toBe(false)
  })

  it('无效行索引不产生高亮', () => {
    const h = useRowHighlight()
    expect(h.toggle(-1)).toBe(false)
    expect(h.toggle(Number.NaN)).toBe(false)
    expect(h.count.value).toBe(0)
  })
})
