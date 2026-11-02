import { describe, expect, it } from 'vitest'

import { matrixCapSuffix } from '../../src/pages/analysis/composables/matrixCapHint'

/**
 * B2 前端落地：`correlation_matrix` 的参数集封顶 50（`CORRELATION_PARAM_LIMIT`），
 * 响应带 `total_params`（本来会算的全部）与 `truncated`。矩阵是 N×N，用户点「全选」
 * 捞到 180 项时后端只会算前 50 项——卡片上必须说清，否则用户以为算的是全部。
 */

describe('matrixCapSuffix', () => {
  it('无响应 / 未截断 → 空串', () => {
    expect(matrixCapSuffix(null)).toBe('')
    expect(matrixCapSuffix(undefined)).toBe('')
    expect(matrixCapSuffix({ truncated: false, total_params: 12, params: ['a', 'b'] })).toBe('')
  })

  it('截断时报「取了几项 / 本应几项」', () => {
    const data = { truncated: true, total_params: 180, params: new Array(50).fill('p') }
    expect(matrixCapSuffix(data)).toBe('参数超上限，已按列序取前 50 项（本应 180 项）')
  })

  it('拿不到「实取几项」时宁可不提示（不编一个数糊弄用户）', () => {
    expect(matrixCapSuffix({ truncated: true, total_params: 180 })).toBe('')
  })

  it('缺 total_params 时不说谎（后端形状变了就该没提示，而不是编一个数）', () => {
    expect(matrixCapSuffix({ truncated: true, params: ['a', 'b'] })).toBe('')
  })
})
