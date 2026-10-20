import { describe, expect, it } from 'vitest'
import {
  TEXT_CHAR_LIMIT,
  describeExportError,
  describeWeightError,
} from '../../src/pages/weight/composables/weightErrorText'

const withData = (data: unknown) => ({ response: { data } }) as never

describe('describeWeightError', () => {
  it('把后端结构化 detail 组织成带行号的一句话', () => {
    expect(describeWeightError(withData({
      code: 'weight_length_mismatch',
      detail: { line: 2, name: 'WT0002', declared: 2, actual: 1 },
    }))).toBe('第 2 行 WT0002：声明长度 2，实际数值 1')
  })

  it('坏数值给行号与原串', () => {
    const msg = describeWeightError(withData({
      code: 'weight_bad_number', detail: { line: 7, token: '1.0.0' },
    }))
    expect(msg).toContain('第 7 行')
    expect(msg).toContain('1.0.0')
  })

  it('no_declaration 没有 detail，句子只能在前端组', () => {
    expect(describeWeightError(withData({ code: 'no_declaration' }))).toContain('double')
  })

  it('未知错误回落到 message，而不是 undefined', () => {
    expect(describeWeightError(new Error('boom'))).toBe('boom')
  })

  it('上限常量与后端一致（2_000_000）', () => {
    expect(TEXT_CHAR_LIMIT).toBe(2_000_000)
  })
})

describe('describeExportError', () => {
  it('Blob 里的 JSON 错误体也能解成同一套文案', async () => {
    const body = { code: 'weight_too_large', detail: { which: 'declarations', limit: 2000 } }
    const blob = new Blob([JSON.stringify(body)], { type: 'application/json' })
    const msg = await describeExportError({ response: { data: blob } })
    expect(msg).toContain('declarations')
    expect(msg).toContain('2000')
  })

  it('Blob 解不出 JSON 时给通用文案，不抛异常', async () => {
    const blob = new Blob(['<html>502</html>'], { type: 'text/html' })
    await expect(describeExportError({ response: { data: blob } })).resolves.toBe('导出失败，请稍后重试')
  })

  it('非 Blob 的错误体走原路径（行为一致）', async () => {
    await expect(describeExportError(withData({ code: 'no_declaration' }))).resolves.toContain('double')
  })
})
