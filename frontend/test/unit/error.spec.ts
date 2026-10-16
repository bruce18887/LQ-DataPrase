import { describe, expect, it } from 'vitest'

import { ERROR_CODE_MAP, formatError, parseBlobError } from '../../src/utils/error'

describe('ERROR_CODE_MAP', () => {
  it('键为 snake_case 机器码，值为非空中文提示', () => {
    for (const [code, text] of Object.entries(ERROR_CODE_MAP)) {
      expect(code).toMatch(/^[a-z][a-z0-9_]*$/)
      expect(text.length).toBeGreaterThan(0)
      expect(/[一-龥]/.test(text)).toBe(true)
    }
  })

  it('后端在用的高频守卫码都有映射（漏加会让界面裸显英文码）', () => {
    for (const code of ['no_valid_params', 'no_site_column', 'no_data', 'no_serial_column']) {
      expect(ERROR_CODE_MAP[code]).toBeTruthy()
    }
  })
})

describe('formatError', () => {
  const resp = (data: unknown) => ({ response: { data } })

  it('非对象错误回退 fallback', () => {
    expect(formatError(null)).toBe('请求失败')
    expect(formatError('boom')).toBe('请求失败')
    expect(formatError('boom', '自定义')).toBe('自定义')
  })

  it('无 response 视为连接层错误而不是「请求失败」', () => {
    expect(formatError({ message: 'Network Error' })).toBe('无法连接服务器，请检查网络')
  })

  it('提取优先级 message > detail > code', () => {
    expect(formatError(resp({ message: '甲', detail: '乙', code: 'no_data' }))).toBe('甲')
    expect(formatError(resp({ detail: '乙', code: 'no_data' }))).toBe('乙')
    expect(formatError(resp({ code: 'no_data' }))).toBe('没有数据')
  })

  it('未知码原样返回；遗留 error 键不再参与取值（后端已统一为 code）', () => {
    expect(formatError(resp({ code: 'brand_new_code' }))).toBe('brand_new_code')
    expect(
      formatError({ message: '上游挂了', response: { data: { error: 'no_data' } } }),
    ).toBe('上游挂了')
  })

  it('字段校验形态取第一条并带上字段名', () => {
    expect(formatError(resp({ filename: ['该字段不能为空。'] }))).toBe('filename: 该字段不能为空。')
  })

  it('data 为空对象时退回 err.message', () => {
    expect(formatError({ message: '上游挂了', response: { data: {} } })).toBe('上游挂了')
  })
})

describe('parseBlobError', () => {
  const blobResp = (body: string) => ({
    response: { data: new Blob([body], { type: 'application/json' }) },
  })

  it('blob 包着的 JSON 错误体能解出文案', async () => {
    expect(await parseBlobError(blobResp(JSON.stringify({ message: '磁盘满' })))).toBe('磁盘满')
    expect(
      await parseBlobError(blobResp(JSON.stringify({ code: 'no_valid_files' }))),
    ).toBe('没有有效文件')
  })

  it('非 blob / 非 JSON / 无文案一律 null，交回 formatError 兜底', async () => {
    expect(await parseBlobError({ response: { data: 'text' } })).toBeNull()
    expect(await parseBlobError(blobResp('<html>502</html>'))).toBeNull()
    expect(await parseBlobError(blobResp(JSON.stringify({ detail: '' })))).toBeNull()
    expect(await parseBlobError(undefined)).toBeNull()
  })
})
