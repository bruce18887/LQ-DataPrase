/**
 * T2：表头右键「复制测试项名字」的剪贴板封装。
 *
 * 生产环境（Electron / 浏览器）优先 navigator.clipboard；该 API 失败时
 * 必须回退到临时 textarea（旧内核/权限受限场景），两条路都失败才返回 false。
 * node 环境没有 document，正好能钉住「无 DOM 时不抛错、返回 false」。
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { copyText } from '../../src/pages/data/composables/clipboard'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('copyText', () => {
  it('navigator.clipboard 可用时写入并返回 true', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    await expect(copyText('VID_FIL_RANGE_MIN')).resolves.toBe(true)
    expect(writeText).toHaveBeenCalledWith('VID_FIL_RANGE_MIN')
  })

  it('剪贴板拒绝且无 DOM（回退不可用）时返回 false，不抛错', async () => {
    vi.stubGlobal('navigator', {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    })
    vi.stubGlobal('document', undefined)
    await expect(copyText('X')).resolves.toBe(false)
  })
})
