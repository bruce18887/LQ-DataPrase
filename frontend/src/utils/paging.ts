/**
 * 分页取全的判据内核（IO 壳由调用方给 fetchPage）。
 *
 * 为什么要有这一层：DRF 默认 PAGE_SIZE=20（config/settings/base.py:214-215），而有些
 * 管理页**没有翻页控件**——只读第一页会让后面的记录既不可达、又不参与页面自己算的
 * 统计（UserManagement 的 total/active/locked/admins 就是按取回的数组算的）。
 * 「跟着 next 走」这件事在浏览器里要凑 >20 条数据才测得动，抽成纯函数后
 * 三种响应形态与护栏都能在 T2 秒级钉住。
 */

/** 一页的两种可能形态：DRF 分页对象，或未分页的裸数组 */
export type PagePayload<T> = { results?: T[]; next?: string | null } | T[]

/**
 * @param fetchPage 取一页；入参是下一页的绝对/相对 URL（首轮为 firstUrl）
 * @param maxPages 护栏：坏响应把 `next` 指回自己时会无限翻页
 */
export async function collectAllPages<T>(
  fetchPage: (url: string) => Promise<PagePayload<T> | null | undefined>,
  firstUrl = '',
  maxPages = 50,
): Promise<{ rows: T[]; pages: number; truncated: boolean }> {
  const rows: T[] = []
  let url: string | null = firstUrl
  let pages = 0
  let truncated = false
  while (url && pages < maxPages) {
    const data = await fetchPage(url)
    pages++
    if (data == null) break
    if (Array.isArray(data)) {
      // 裸数组 = 后端未分页，一次就是全量
      rows.push(...data)
      url = null
      continue
    }
    rows.push(...(data.results ?? []))
    url = data.next ?? null
  }
  // 还有 next 却被护栏拦下 ⇒ 数据没取完，调用方须知道（别让统计静默偏小）
  if (url && pages >= maxPages) truncated = true
  return { rows, pages, truncated }
}
