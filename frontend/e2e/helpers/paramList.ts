import type { Page, Request } from '@playwright/test'

/**
 * 参数全集的捕获器。
 *
 * 为什么需要：迁 `el-select-v2` 后 DOM 里只有虚拟窗口那约 8 行，
 * 「数 `.el-select-dropdown__item` 条数」不再等于「列表有多少项」。
 * 而产品自己拿全集的路径就在那儿 —— `useTabFileParams.ts:79-87` 发一次
 * **不带 `params`** 的 POST /analysis/histogram/，用 `Object.keys(results)` 当参数全集。
 * 本 helper 挂同一个响应，取同一个键，判据与实现异源（DOM 是渲染，响应是数据源）。
 *
 * 过滤条件与前端逐字一致（`p && p.trim() !== ''`）：后端 `analysis_views.py:139`
 * 回的是 `{p: {} for p in params}`，脏列名在前端就被丢掉，捕获侧不能把它放回来。
 *
 * 两条必须有的过期守卫（都是 2026-11-13 实测 flake 教出来的，不是防御性装饰）：
 * 1. **序号**：镜像产品 useTabFileParams.ts:60,85 的 mySeq/loadSeq。序号打在
 *    request 事件（发出顺序，严格单调）上；响应到达顺序不保证等于发出顺序，
 *    而 handler 里 await json() 之后连到达顺序都不保证了。缺这条时 F1 快路径的
 *    json() 晚 resolve 一步就把 DA35 的列表回写成旧文件的（outlier-handling:346
 *    红：selectParam 拿 SOFT_BIN 去过滤只有 Index_No 系列名的下拉，15s 挑不中）。
 * 2. **file_id 对齐**：`capturedParamList` 只在「捕获所属文件 == 最后一次列表
 *    请求所属文件」时给值，否则给空数组。旧 DOM 实现打开下拉数选项，天然要等
 *    新文件的列表渲染出来才返回；纯读捕获会把这一等丢掉 —— pickTabFileAndWaitCompute
 *    等的是计算**请求发出**，而带旧参数的首发计算可能 400（先清预设前的竞态），
 *    于是列表响应还没处理就返回了（chart-filter-switches:71 红：allParams 读到
 *    旧文件 41 项，Fail 收缩后的 80 项反而「不少于全量」）。等待由 listParams
 *    的轮询补回来。
 * 注：Node API 没有 Request.timestamp()（Python 才有），所以序号自己按事件计数。
 */

interface FastReq {
  seq: number
  fileId: number | null
}

const captured = new WeakMap<Page, { fileId: number | null; keys: string[] }>()
const installed = new WeakSet<Page>()
const sentMeta = new WeakMap<Request, FastReq>()
const seqCounter = new WeakMap<Page, number>()
// 最后一次**发出**的快路径请求（产品当前正在等的列表口径）
const lastFast = new WeakMap<Page, FastReq>()
const acceptedSeq = new WeakMap<Page, number>()

function fastReqProbe(req: Request): { fileId: number | null } | null {
  if (!req.url().includes('/analysis/histogram/') || req.method() !== 'POST') return null
  // 带 params 的是「算某参数」的请求，其 results 只有被算的那几项，不是全集。
  // 列表请求体是 {file_id, ...filters()}（useTabFileParams.ts:79-82），键名表里
  // 根本没有 params —— 这里不是 substring 侥幸，是对着那个请求体确认过的。
  const body = req.postData() ?? ''
  if (body.includes('"params"')) return null
  try {
    const parsed = JSON.parse(body) as { file_id?: number }
    return { fileId: typeof parsed.file_id === 'number' ? parsed.file_id : null }
  } catch {
    return { fileId: null }
  }
}

/** 在 page 上装一次响应监听。必须在导航**之前**装，否则错过首次列表请求。 */
export function attachParamListCapture(page: Page): void {
  if (installed.has(page)) return
  installed.add(page)
  seqCounter.set(page, 0)
  page.on('request', (req) => {
    const probe = fastReqProbe(req)
    if (!probe) return
    const seq = (seqCounter.get(page) ?? 0) + 1
    seqCounter.set(page, seq)
    const meta: FastReq = { seq, fileId: probe.fileId }
    sentMeta.set(req, meta)
    lastFast.set(page, meta)
  })
  page.on('response', (response) => {
    void (async () => {
      const req = response.request()
      const meta = sentMeta.get(req)
      if (!meta) return
      if (response.status() !== 200) return
      try {
        const json = (await response.json()) as { results?: Record<string, unknown> }
        const keys = Object.keys(json?.results ?? {}).filter((p) => p && p.trim() !== '')
        // 检查与写入之间隔着 await json()，resolve 后要复核序号，
        // 否则更晚发出的请求可能已被过期响应的迟到 resolve 覆盖。
        if (keys.length > 0 && meta.seq >= (acceptedSeq.get(page) ?? 0)) {
          captured.set(page, { fileId: meta.fileId, keys })
          acceptedSeq.set(page, meta.seq)
        }
      } catch {
        /* 非 JSON / 响应已销毁：保持上一次捕获值，不抛 */
      }
    })()
  })
}

/**
 * 取捕获到的参数全集（保持后端返回顺序）。
 * 空数组 = 还没捕获，或捕获仍属于**上一个**文件（新文件的列表请求在途）——
 * 调用方必须轮询/显式失败，不能当「列表真的为空」。
 */
export function capturedParamList(page: Page): string[] {
  const want = lastFast.get(page)
  const got = captured.get(page)
  if (!want || !got) return []
  if (got.fileId !== want.fileId) return []
  return got.keys
}
