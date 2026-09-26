import { describe, expect, it } from 'vitest'

import { formatSize, formatTime, truncateMiddle } from '../../src/utils/format'

describe('truncateMiddle', () => {
  it('不超上限时原样返回，空串与 0 长度不抛错', () => {
    expect(truncateMiddle('abc', 10)).toBe('abc')
    expect(truncateMiddle('', 10)).toBe('')
  })

  it('超长时保留首尾、中间省略号，总长不超过 max', () => {
    const out = truncateMiddle('aaaaaaaaaa1234567890bb', 12)
    expect(out).toBe('aaaaa…890bb')
    expect(out.length).toBeLessThanOrEqual(12)
  })

  it('奇数上限时头比尾多一个字符', () => {
    expect(truncateMiddle('aaaaaaaaaa1234567890bb', 11)).toBe('aaaaa…90bb')
  })
})

describe('formatSize', () => {
  it('0 与空值显示为占位符而非 0 B', () => {
    expect(formatSize(0)).toBe('--')
    expect(formatSize(Number.NaN)).toBe('--')
  })

  it('档位边界按 1024 进位且保留一位小数', () => {
    expect(formatSize(1023)).toBe('1023 B')
    expect(formatSize(1024)).toBe('1.0 KB')
    expect(formatSize(1536)).toBe('1.5 KB')
    expect(formatSize(1024 * 1024)).toBe('1.0 MB')
    expect(formatSize(1024 * 1024 - 1)).toBe('1024.0 KB')
  })
})

describe('formatTime', () => {
  it('空值返回空串', () => {
    expect(formatTime('')).toBe('')
  })

  // 不断精确文案：zh-CN 的月日分隔符与时段标记随 ICU 版本变化（Node/Chromium 不一致）。
  it('输出 MM-DD HH:mm 形态', () => {
    expect(formatTime('2026-09-26T03:07:00')).toMatch(/\d{2}\D\d{2}\s*\d{1,2}:\d{2}/)
  })
})
