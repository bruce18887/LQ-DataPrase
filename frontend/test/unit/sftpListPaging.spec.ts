import { describe, expect, it } from 'vitest'

import {
  applyListPage,
  emptyListState,
  nextOffset,
  type ListState,
} from '../../src/pages/sftp/listPaging'

/**
 * B1 前端落地：`/sftp/list_files/` 默认只给 500 条，响应带 `total` / `truncated`。
 * 「加载更多」用 `offset = 已加载条数` 向后端要下一页——排序由后端做，
 * 前端只拼接，绝不在本地重排（本地重排会让跨页的 offset 语义失效）。
 */

function page(items: Array<{ name: string }>, total: number, truncated: boolean) {
  return { items, total, truncated }
}

describe('applyListPage', () => {
  it('首页是替换而不是追加（换目录/换排序后旧条目必须消失）', () => {
    const prev: ListState = { rows: [{ name: 'old.csv' }], total: 1, hasMore: false }
    const next = applyListPage(prev, page([{ name: 'a.csv' }], 501, true), true)
    expect(next.rows.map((r) => r.name)).toEqual(['a.csv'])
    expect(next.total).toBe(501)
    expect(next.hasMore).toBe(true)
  })

  it('追加页把新条目接在尾部，跨页顺序跟随后端', () => {
    const first = applyListPage(emptyListState(), page([{ name: 'a' }, { name: 'b' }], 3, true), true)
    const second = applyListPage(first, page([{ name: 'c' }], 3, false), false)
    expect(second.rows.map((r) => r.name)).toEqual(['a', 'b', 'c'])
    expect(second.hasMore, '最后一页 truncated=false ⇒ 按钮该消失').toBe(false)
  })

  it('offset 恒等于已加载条数（后端按同一序列切片，不重不漏）', () => {
    const first = applyListPage(emptyListState(), page(new Array(500).fill({ name: 'x' }), 501, true), true)
    expect(nextOffset(first)).toBe(500)
    const second = applyListPage(first, page([{ name: 'y' }], 501, false), false)
    expect(nextOffset(second)).toBe(501)
  })

  it('缺字段的坏响应不炸：items 回退空、total 回退已加载数、hasMore 回退 false', () => {
    const first = applyListPage(emptyListState(), page([{ name: 'a' }], 2, false), true)
    const broken = applyListPage(first, {}, false)
    expect(broken.rows).toHaveLength(1)
    expect(broken.total, '后端没回 total 才准退化成本地行数，否则一律跟随后端').toBe(1)
    expect(broken.hasMore, '没给 truncated 就当没有下一页，别放个按了没反应的按钮').toBe(false)
  })
})

describe('emptyListState', () => {
  it('空态是 hasMore=false，未连接时不该出现「加载更多」', () => {
    expect(emptyListState()).toEqual({ rows: [], total: 0, hasMore: false })
  })
})
