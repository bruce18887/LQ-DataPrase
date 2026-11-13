/**
 * 参数全集捕获守卫的**纯核**（无 Playwright、无 DOM，T2 可直接驱动）。
 *
 * 为什么要把判定抽出来：这两条竞态守卫原先只由 e2e 全量池兜（`docs/reference/testing-gates.md`
 * 里最贵的那一档，~9min），而回归症状毫不可读（「另一个文件的列表混进来了」）。
 * 判定住在这里 ⇒ `frontend/test/unit/paramListGuard.spec.ts` 用假事件序列就能钉住；
 * `paramList.ts` 只剩 Playwright 事件接线。
 *
 * **判据异源纪律**：单测钉的是「守卫怎么判」，不是「守卫在真浏览器里挡住了那个 flake」——
 * 后者仍由 e2e 兜（chart-filter-switches / outlier-handling），别在这里假装验了浏览器行为。
 *
 * 三个概念必须分清（2026-11-13 复审 C-1/C-2 的根因就是把它们搅在一起）：
 * - **发出**（lastFast）：这一发快路径请求已经离开浏览器；
 * - **结算**（captured.seq 与之对齐）：这一发的响应处理完了，无论结果是几项、什么状态码；
 * - **非空**（keys.length）：只是本次结算的结果特征，**不参与**「能不能读」的判定。
 * 旧实现拿「fileId 相等」当结算、拿「keys 非空」当结算，于是同文件换口径
 * （`useTabFileParams.ts:131-133` 防抖重发，file_id 不变 seq 变）直接放行脏值。
 */

/**
 * 会自己发「不带 params 的快路径」拉参数全集的分析页 tab。
 * **没有 'multi'**：多文件 tab 不接 `useTabFileParams`（它自己拼合并请求），
 * 所以那边没有可捕获的全集响应，`listParams` 也就无处声明 scope。
 */
export type ParamListScope = 'single' | 'wafer' | 'correlation'

export const PARAM_LIST_SCOPES: ParamListScope[] = ['single', 'wafer', 'correlation']

/** 参数全集端点（不带 params 的那一发走它） */
export const FAST_PATH_URL = '/analysis/histogram/'

/** 带筛选字段的请求体键名（与 `useTabFileParams.ts:30-37` TabFilterPayload 同一份） */
const FILTER_KEYS = [
  'ignore_no_limit',
  'ignore_no_test_value',
  'data_only_bin1',
  'only_fail_test_item',
  'only_low_cpk',
  'iqr_multiplier',
]

/** 一次「发出」的元信息：序号打在 request 事件上（发出顺序，严格单调） */
export interface FastReqInfo {
  seq: number
  fileId: unknown
}

/** 一次「结算」的捕获：比 FastReqInfo 多状态码与键表 */
export interface CapturedEntry extends FastReqInfo {
  status: number
  keys: string[]
}

/**
 * 这个请求是不是「不带 params 的参数全集快路径」？
 * 带 params 的是算某参数的请求，其 results 只有被算的那几项，不是全集
 * （列表请求体是 `{file_id, ...filters()}`，见 `useTabFileParams.ts:79-82`）。
 * 体缺失（postData() === null）时**不**当快路径：那种请求无从区分列表与计算，
 * 误当列表会静默给出脏值，判成「没发过」反而会在超时消息里喊出来。
 */
export function parseFastRequest(
  url: string,
  method: string,
  body: string | null,
): { fileId: unknown; hasFilters: boolean } | null {
  if (!url.includes(FAST_PATH_URL) || method !== 'POST' || body === null) return null
  if (body.includes('"params"')) return null
  try {
    const parsed = JSON.parse(body) as Record<string, unknown>
    return {
      fileId: parsed.file_id ?? null,
      hasFilters: FILTER_KEYS.some((k) => body.includes(`"${k}"`)),
    }
  } catch {
    // 体读不懂也要算一发快路径：宁可给空集，也不要把这一发凭空抹掉。
    return { fileId: null, hasFilters: false }
  }
}

/**
 * 这一发属于哪个 tab？
 * 快路径是 **tab 级**的（`SingleParamTab.vue:321`、`WaferMapPanel.vue:106`、
 * `CorrelationToolsTab.vue:210` 各发一份，file_id 还各不相同），所以捕获必须分桶。
 * 只有晶圆图能靠请求体自动归属：它拉列表**不传 filters**（`WaferMapPanel.vue:105-109`），
 * 而单文件与相关性两个 tab 的 filters() 键集逐字相同（各 6 个键），产品没在请求里
 * 留 tab 身份 ⇒ 那两者只能由用例显式声明（`setActiveAnalysisTab`）。
 * ⚠ 若哪天晶圆图也开始传筛选字段，这条推断必须删掉，别让它悄悄变成假判据。
 */
export function resolveScope(probe: { hasFilters: boolean }, declared: ParamListScope): ParamListScope {
  return probe.hasFilters ? declared : 'wafer'
}

/** 空白列名的过滤条件与前端逐字一致（`useTabFileParams.ts:87`：`p && p.trim() !== ''`） */
export function paramKeysFromResults(results: unknown): string[] {
  if (!results || typeof results !== 'object' || Array.isArray(results)) return []
  return Object.keys(results).filter((p) => p && p.trim() !== '')
}

/**
 * 把一次快路径响应折成捕获条目。
 * 「结算」与「结果非空」在这里彻底分开：**任何**状态码都产出一条条目（含 0 项），
 * 非 200 就是空集 —— 这与产品侧一致（axios 非 2xx 抛错，`useTabFileParams.ts:93`
 * 的 catch 让 params 保持清空）。旧实现 `status() !== 200` 直接 return，
 * 于是一发 400 能把 `listParams` 的轮询锁死满 15s，还顺手把上一份列表留在原地当现值。
 */
export function entryFromFastResponse(meta: FastReqInfo, status: number, json: unknown): CapturedEntry {
  const results = status === 200 ? (json as { results?: unknown } | null)?.results : undefined
  return { seq: meta.seq, fileId: meta.fileId, status, keys: paramKeysFromResults(results) }
}

/**
 * 乱序保护：更晚发出的响应不得被更早发出的迟到响应覆盖。
 * 比较的是**序号**而不是到达顺序 —— handler 里 `await json()` 之后连到达顺序都不保证了。
 * 同 seq 允许自更新（重定向链会为一个请求发多次 response 事件）。
 * 这里**没有** `keys.length > 0` 那道闸：它把空集当「没捕获」，净负价值（复审 C-2）。
 */
export function shouldAcceptCapture(prev: CapturedEntry | null, incoming: CapturedEntry): boolean {
  return prev === null || incoming.seq >= prev.seq
}

/**
 * 读判定：当前这一发结算了就给键表，否则给 null（= 还没结算，调用方必须轮询）。
 * 只比 seq，**不比 fileId** —— 同文件换口径时 fileId 恒等，比它等于没守卫（复审 C-1）。
 */
export function decideCaptured(captured: CapturedEntry | null, lastFast: FastReqInfo | null): string[] | null {
  if (!lastFast || !captured) return null
  if (captured.seq !== lastFast.seq) return null
  return captured.keys
}

/**
 * 给 `expect.poll` 用的诊断串。**已结算**时以 `settled` 开头（poll 的匹配前缀），
 * 未结算时把复审点名的四个量一次打全：captured.seq / lastFast.seq / 两侧 fileId / keys 数。
 * 四种成因必须分得开（旧消息只有一句「空到这里=没选文件/监听装晚了/请求没完成」，
 * 后两种「同文件换口径未落地」「当前口径真返回 0 项」根本不报）：
 *  ① 该 tab 没选文件 ② 监听装晚了 ③ 换口径的响应还没回来 ④ 真·空集（这条不算错，走 settled）
 */
export function explainCapture(
  scope: ParamListScope,
  captured: CapturedEntry | null,
  lastFast: FastReqInfo | null,
  sentByScope: Record<ParamListScope, number>,
): string {
  const counts = PARAM_LIST_SCOPES.map((s) => `${s}=${sentByScope[s] ?? 0}`).join(' ')
  if (!lastFast) {
    const others = PARAM_LIST_SCOPES.filter((s) => s !== scope).reduce((n, s) => n + (sentByScope[s] ?? 0), 0)
    return (
      `未发出：scope=${scope} 从未发出快路径请求（各 scope 发出数 ${counts}）。` +
      (others === 0
        ? '所有 scope 都是 0 ⇒ 先查监听是否在 page.goto 之前装（nav.ts gotoApp），即「监听装晚了」。'
        : `其他 scope 发过 ${others} 发 ⇒ 监听在装：要么本 tab 还没选文件，` +
          `要么用例切 tab 时没先调 setActiveAnalysisTab(page, '${scope}')，那一发被记进了别的桶。`)
    )
  }
  const diag = `lastFast.seq=${lastFast.seq}(fileId=${String(lastFast.fileId)})`
  if (!captured) return `未处理：已发出 ${diag}，但一条快路径响应都没处理完（响应在途，或已销毁）`
  const got = `captured.seq=${captured.seq}(fileId=${String(captured.fileId)}), captured.keys=${captured.keys.length}`
  if (captured.seq !== lastFast.seq) {
    const sameFile = captured.fileId === lastFast.fileId
    return (
      `未结算：${diag} 而 ${got} —— 这一发的响应还没处理完` +
      (sameFile
        ? `（fileId 都是 ${String(lastFast.fileId)} ⇒ 同文件换口径（勾选开关触发防抖重发，useTabFileParams.ts:131-133），旧「比 fileId」的守卫正是在这里放行上一个口径的脏值）`
        : '（跨文件切换在途）')
    )
  }
  return captured.status === 200
    ? 'settled'
    : `settled 但本次快路径 status=${captured.status} ⇒ 空集（与产品一致，axios 非 2xx 不落 params；断言据此判红，别再等 15s）`
}
