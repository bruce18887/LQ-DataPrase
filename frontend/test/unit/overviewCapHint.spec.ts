import { describe, expect, it } from 'vitest'

import { overviewCapHint } from '../../src/pages/dashboard/utils/overviewCap'

/**
 * B4 前端落地：`/summary/` 的 `test_item_overview` 默认封顶 200 行，响应另带
 * `param_total`（截断前的参数数）与 `top_n`（本次生效上限）。总览页脚原本的
 * 「共 N 项」是**行级过滤后**的行数，跟封顶是两回事，所以封顶得单独说清，
 * 否则 1728 列那种文件看起来就像「只有 200 个参数」。
 */

describe('overviewCapHint', () => {
  it('没下发 param_total（旧响应/错误分支）→ 空串', () => {
    expect(overviewCapHint({ itemsCount: 200 })).toBe('')
  })

  it('param_total 等于行数 = 后端没截断 → 空串', () => {
    expect(overviewCapHint({ paramTotal: 60, itemsCount: 60, topN: 200 })).toBe('')
  })

  it('异常形状（param_total 比行数还小）也不提示，别编话', () => {
    expect(overviewCapHint({ paramTotal: 10, itemsCount: 60, topN: 200 })).toBe('')
  })

  it('被封顶时报「共几项 / 最多显示几项」', () => {
    expect(overviewCapHint({ paramTotal: 260, itemsCount: 200, topN: 200 }))
      .toBe('参数共 260 项，总览最多显示 200 项')
  })

  it('缺 top_n 时以实际行数当上限，不显示 undefined', () => {
    expect(overviewCapHint({ paramTotal: 260, itemsCount: 200 }))
      .toBe('参数共 260 项，总览最多显示 200 项')
  })
})
