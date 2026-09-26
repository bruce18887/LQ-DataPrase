import { describe, expect, it } from 'vitest'

import { minMax } from '../../src/utils/minmax'

describe('minMax', () => {
  it('常规数组取到端点', () => {
    expect(minMax([3, 1, 2])).toEqual([1, 3])
    expect(minMax([7])).toEqual([7, 7])
  })

  it('空数组与 Math.min(...[]) 语义一致（调用方保证非空）', () => {
    expect(minMax([])).toEqual([Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])
  })

  it('NaN 被跳过而不污染端点', () => {
    expect(minMax([1, Number.NaN, 5])).toEqual([1, 5])
    expect(minMax([Number.NaN])).toEqual([Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])
  })

  // 这个函数存在的唯一理由：Math.min(...arr) 在 11 万+ 元素时爆调用栈（见文件头注释）。
  it('20 万元素不再触发 RangeError', () => {
    const values = Array.from({ length: 200_000 }, (_, i) => i)
    expect(() => minMax(values)).not.toThrow()
    expect(minMax(values)).toEqual([0, 199_999])
  })
})
