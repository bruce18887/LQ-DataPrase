import { describe, expect, it } from 'vitest'

import { collectAllPages, type PagePayload } from '../../src/utils/paging'

/**
 * T2：分页取全的判据内核（`src/utils/paging.ts`）。
 *
 * 之所以抽出来测：本仓有页面「没有翻页控件却只读第一页」（UserManagement 曾如此，
 * DRF 默认 PAGE_SIZE=20），后果是第 21 条起既不可达、又不参与页面自己算的 KPI。
 * 要在浏览器里复现得先种 >20 条数据，而三种响应形态与「next 自指」的护栏在纯函数里
 * 秒级就能钉住 ⇒ T3 不再补这类组合。
 */

const paged = <T>(results: T[], next: string | null): PagePayload<T> => ({ results, next })

describe('collectAllPages', () => {
  it('跟着 next 把两页取完，并按顺序拼接', async () => {
    const seen: string[] = []
    const fake = async (url: string): Promise<PagePayload<number>> => {
      seen.push(url)
      return url === '/x/' ? paged([1, 2], '/x/?page=2') : paged([3], null)
    }
    const r = await collectAllPages(fake, '/x/')
    expect(r.rows).toEqual([1, 2, 3])
    expect(r.pages).toBe(2)
    expect(r.truncated).toBe(false)
    // 对照组：第二页确实被请求过（少了这条，「只取一页」也能全绿）
    expect(seen).toEqual(['/x/', '/x/?page=2'])
  })

  it('裸数组（后端未分页）只请求一次就是全量', async () => {
    let calls = 0
    const r = await collectAllPages<number>(async () => {
      calls++
      return [1, 2, 3]
    }, '/y/')
    expect(r.rows).toEqual([1, 2, 3])
    expect(calls).toBe(1)
    expect(r.truncated).toBe(false)
  })

  it('next 自指的坏响应被 maxPages 护栏拦住，并标 truncated', async () => {
    let calls = 0
    const r = await collectAllPages<number>(async () => {
      calls++
      return paged([1], '/z/')
    }, '/z/', 3)
    expect(calls).toBe(3)
    expect(r.truncated, '被护栏截断时必须让调用方知道，否则统计值静默偏小').toBe(true)
    expect(r.rows).toEqual([1, 1, 1])
  })

  it('缺 results 的分页对象不抛错，按空页处理', async () => {
    const r = await collectAllPages<number>(
      async () => ({ next: null }) as PagePayload<number>,
      '/w/',
    )
    expect(r.rows).toEqual([])
    expect(r.pages).toBe(1)
  })

  it('fetchPage 返回 null（坏响应）时停止翻页而不抛', async () => {
    let calls = 0
    const r = await collectAllPages<number>(async () => {
      calls++
      return null
    }, '/n/')
    expect(calls).toBe(1)
    expect(r.rows).toEqual([])
    expect(r.truncated).toBe(false)
  })
})
