/**
 * SFTP 目录列表的分页状态（B1 前端落地）。
 *
 * 后端 `/sftp/list_files/` 默认一次只给 500 条，响应带 `total`（目录真实条目数）与
 * `truncated`（还有没给的）。排序始终由后端做，前端**只拼接不重排**：一旦本地重排，
 * 「offset = 已加载条数」这个跨页前提就作废，翻页会重复或漏条目。
 */

export interface ListPage {
  items?: Array<Record<string, any>>
  total?: number
  truncated?: boolean
}

export interface ListState {
  rows: Array<Record<string, any>>
  total: number
  hasMore: boolean
}

export function emptyListState(): ListState {
  return { rows: [], total: 0, hasMore: false }
}

/**
 * @param reset 首页/换目录/换排序为 true（整页替换），「加载更多」为 false（追加）
 */
export function applyListPage(prev: ListState, page: ListPage, reset: boolean): ListState {
  const items = Array.isArray(page.items) ? page.items : []
  const rows = reset ? items : prev.rows.concat(items)
  return {
    rows,
    total: typeof page.total === 'number' ? page.total : rows.length,
    hasMore: page.truncated === true,
  }
}

/** 下一页的 offset：后端按同一序列切片，已加载条数就是下一页起点 */
export function nextOffset(state: ListState): number {
  return state.rows.length
}
