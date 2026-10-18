/**
 * T2：/browse/ 的传输格式 zip。
 *
 * headers + data（行值数组）+ fail_cells/borderline_cells（并行数组）
 * → ag-grid 行对象。两条数组都必须与 data 等长地对齐；缺行时退化为 []，
 * 不能让某一行的缺失把后面的行列错位。
 */
import { describe, expect, it } from 'vitest'

import { zipBrowserRows } from '../../src/pages/data/components/browser/browserRows'

describe('zipBrowserRows', () => {
  it('按 headers 把行值转成对象，并挂上红/橙并行数组', () => {
    const rows = zipBrowserRows({
      headers: ['A', 'B', 'Bin'],
      data: [
        [1, 2, 1],
        [3, 4, 7],
      ],
      fail_cells: [[], ['Bin']],
      borderline_cells: [['A'], []],
    })
    expect(rows).toHaveLength(2)
    expect(rows[0]).toEqual({ A: 1, B: 2, Bin: 1, __fail_cells__: [], __borderline_cells__: ['A'] })
    expect(rows[1]).toEqual({ A: 3, B: 4, Bin: 7, __fail_cells__: ['Bin'], __borderline_cells__: [] })
  })

  it('缺数组/缺行时每行仍有空数组，不污染列值', () => {
    const rows = zipBrowserRows({
      headers: ['A'],
      data: [[1], [2]],
      fail_cells: [['A']],
    })
    expect(rows[0].__fail_cells__).toEqual(['A'])
    expect(rows[1].__fail_cells__).toEqual([])
    expect(rows[0].__borderline_cells__).toEqual([])
    expect(rows[1].__borderline_cells__).toEqual([])
  })
})
