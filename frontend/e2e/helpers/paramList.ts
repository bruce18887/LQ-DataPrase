import type { Page, Request } from '@playwright/test'
import {
  decideCaptured,
  entryFromFastResponse,
  explainCapture,
  PARAM_LIST_SCOPES,
  parseFastRequest,
  resolveScope,
  shouldAcceptCapture,
  type CapturedEntry,
  type FastReqInfo,
  type ParamListScope,
} from './paramListCore'

/**
 * 参数全集的捕获器（Playwright 接线层）。
 * **判定全在 `paramListCore.ts`**，本文件只管事件与状态存放 —— 那样守卫才能由
 * `frontend/test/unit/paramListGuard.spec.ts` 用假事件序列钉住（T2，不开浏览器），
 * 而不是只靠 e2e 全量池那最贵的一档。
 *
 * 为什么需要：迁 `el-select-v2` 后 DOM 里只有虚拟窗口那约 8 行，
 * 「数 `.el-select-dropdown__item` 条数」不再等于「列表有多少项」。
 * 而产品自己拿全集的路径就在那儿 —— `useTabFileParams.ts:79-82` 发一次
 * **不带 `params`** 的 POST /analysis/histogram/，用 `Object.keys(results)` 当参数全集。
 *
 * ⚠ 同源/异源要说准（2026-11-13 Task 5 订正；本文件旧写「判据与实现异源」，Task 4 之后
 * 那句是反的）：本 helper 读**同一个响应**、同一个 `Object.keys(results)`、同一条
 * `trim()` 过滤 ⇒ 在「有哪些参数」这一维上与产品**同源**，它钉的是「产品收到的数据里
 * 有什么」，不是「下拉里画出了什么」。真正异源的是 `paramListGuard.spec.ts` 钉的那三条
 * 竞态守卫（假事件序列，见 paramListCore.ts 顶部那条纪律）。
 * 「下拉真的把这些项渲染出来了、并且够得着」这一维响应答不出来，唯一兜它的是
 * `e2e/analysis/param-dropdown-full-list.spec.ts`（footer 计数 / 搜到末项 / 滚到底末项进窗口）。
 *
 * 过滤条件与前端逐字一致（`p && p.trim() !== ''`）：后端 `analysis_views.py:139`
 * 回的是 `{p: {} for p in params}`，脏列名在前端就被丢掉，捕获侧不能把它放回来。
 *
 * 三条必须有的守卫（2026-11-13 复审把前两条钉成 Critical，逐条在核心文件里有单测）：
 * 1. **序号**：镜像产品 `useTabFileParams.ts:60,85` 的 mySeq/loadSeq。序号打在 request
 *    事件（发出顺序，严格单调）上；响应到达顺序不保证等于发出顺序，而 handler 里
 *    `await json()` 之后连到达顺序都不保证了。缺这条时 F1 快路径的 json() 晚 resolve
 *    一步就把 DA35 的列表回写成旧文件的（outlier-handling:346 红：selectParam 拿
 *    SOFT_BIN 去过滤只有 Index_No 系列名的下拉，15s 挑不中）。
 * 2. **比 seq，不比 file_id**：同 `file_id=1` 而 body 加 `only_fail_test_item:true` 是
 *    真实数据形状（快路径名单由 `ignore_no_limit` / `filter_test_items(only_fail_test_item,
 *    only_low_cpk, ignore_no_test_value, iqr_multiplier…)` / `filter_bin1_rows` 逐层决定，
 *    `analysis_views.py:91-140`；`column_profile.py:83-107` 还会在行收窄后**再筛一次空列**，
 *    名单会变），而 `useTabFileParams.ts:131-133` → `scheduleRefresh`（250ms 防抖）→ `:79`
 *    重发快路径就是 **file_id 不变、seq 变**。旧实现比 fileId ⇒ 守卫放行 ⇒ 返回上一个
 *    口径的列表且 `poll(length>0)` 立刻通过、一次都不等，把「Fail∩低CPK ≤ Fail」与
 *    「全 Pass 文件列表保持不变」两条断言变成恒真（复审当时指的行号是
 *    chart-filter-switches:121 与 :282，现在那两条各自多了一道快路径等待）。
 * 3. **结算态**：任何快路径响应（200 与 400/500、含 0 项）都落一条捕获，读判定只认
 *    「这一发结算了吗」，不再拿「结果非空」当就绪信号 —— 一发 400 不该把 `listParams`
 *    锁死 15s；当前口径真返回 `results:{}` 时也不该回吐上一份列表（那与
 *    chart-filter-switches:114 注释的「允许为空」直接契约冲突）。
 *
 * tab 归属（复审 I-4）：快路径是 **tab 级**的（三个 tab 各自发、file_id 还各不相同），
 * 所以捕获按 `(page, scope)` 分桶。单文件与相关性两个 tab 的请求体键集逐字相同、
 * 产品没在请求里留 tab 身份 ⇒ 那两者**无从自动区分**，改由用例经
 * `setActiveAnalysisTab` 显式声明（切 tab **之前**声明）；晶圆图不传 filters，
 * 可由请求体自动归属（前提见 paramListCore.resolveScope 的注释）。
 * 注：Node API 没有 Request.timestamp()（Python 才有），所以序号自己按事件计数。
 */

export type { ParamListScope }

interface ScopeState {
  /** 本 scope 已发出的快路径请求数（= 下一条的序号，也用于超时诊断） */
  seqCounter: number
  lastFast: FastReqInfo | null
  captured: CapturedEntry | null
}

type SentMeta = FastReqInfo & { scope: ParamListScope }

const states = new WeakMap<Page, Map<ParamListScope, ScopeState>>()
const installed = new WeakSet<Page>()
/** 用例声明的「当前所在 tab」；缺省 'single'（首屏唯一非 lazy 的 pane，AnalysisPage.vue:8-25） */
const declaredScope = new WeakMap<Page, ParamListScope>()
const sentMeta = new WeakMap<Request, SentMeta>()

function bucket(page: Page, scope: ParamListScope): ScopeState | null {
  return states.get(page)?.get(scope) ?? null
}

function bucketOf(page: Page, scope: ParamListScope): ScopeState {
  let byScope = states.get(page)
  if (!byScope) {
    byScope = new Map()
    states.set(page, byScope)
  }
  let st = byScope.get(scope)
  if (!st) {
    st = { seqCounter: 0, lastFast: null, captured: null }
    byScope.set(scope, st)
  }
  return st
}

/** 在 page 上装一次响应监听。必须在导航**之前**装，否则错过首次列表请求（见 nav.ts gotoApp）。 */
export function attachParamListCapture(page: Page): void {
  if (installed.has(page)) return
  installed.add(page)
  bucketOf(page, 'single')
  page.on('request', (req) => {
    // 带 params 的是「算某参数」的请求（其 results 只有被算的那几项，不是全集）；
    // 列表请求体是 {file_id, ...filters()}，见 useTabFileParams.ts:79-82。
    // 逐字判据在 paramListCore.parseFastRequest，不是 substring 侥幸。
    const probe = parseFastRequest(req.url(), req.method(), req.postData())
    if (!probe) return
    const scope = resolveScope(probe, declaredScope.get(page) ?? 'single')
    const st = bucketOf(page, scope)
    const meta: SentMeta = { seq: st.seqCounter + 1, fileId: probe.fileId, scope }
    st.seqCounter = meta.seq
    // 最后一次**发出**的快路径请求（本 scope 当前该等的那一发）
    st.lastFast = { seq: meta.seq, fileId: meta.fileId }
    sentMeta.set(req, meta)
  })
  page.on('response', (response) => {
    void (async () => {
      const meta = sentMeta.get(response.request())
      if (!meta) return
      let json: unknown
      try {
        json = await response.json()
      } catch {
        // 非 JSON / 响应已销毁：仍然**结算**这一发（keys 为空），
        // 不把上一份列表留在原地冒充现值。
        json = undefined
      }
      const st = bucketOf(page, meta.scope)
      const entry = entryFromFastResponse({ seq: meta.seq, fileId: meta.fileId }, response.status(), json)
      // 检查与写入之间隔着 await json()，resolve 后要复核序号，
      // 否则更晚发出的请求可能已被过期响应的迟到 resolve 覆盖。
      if (shouldAcceptCapture(st.captured, entry)) st.captured = entry
    })()
  })
}

/**
 * 声明「用例现在操作的是哪个 tab」；此后**带筛选字段的**快路径请求都归给它。
 * **必须在点 tab 之前调用**：wafer/correlation/multi 三个 pane 是 `lazy`
 * （AnalysisPage.vue:13-23），一挂载就发自己的列表请求，声明晚了那一发会记错桶。
 */
export function setActiveAnalysisTab(page: Page, scope: ParamListScope): void {
  declaredScope.set(page, scope)
  bucketOf(page, scope)
}

/**
 * 取「当前这一发已结算」的参数全集（保持后端返回顺序）。
 * `null` = 这一发还没结算（响应在途 / 本 scope 没发过 / 监听装晚了）——调用方必须
 * 轮询或显式失败，**不能**当「列表真的为空」。空数组则是合法的「当前口径 0 项」。
 */
export function capturedParamList(page: Page, scope: ParamListScope = 'single'): string[] | null {
  const st = bucket(page, scope)
  if (!st) return null
  return decideCaptured(st.captured, st.lastFast)
}

/** 未就绪时的诊断串（已就绪以 `settled` 开头）。四个成因分得开，见 paramListCore.explainCapture。 */
export function explainParamListCapture(page: Page, scope: ParamListScope = 'single'): string {
  const byScope = states.get(page)
  const st = bucket(page, scope)
  const counts = {} as Record<ParamListScope, number>
  for (const s of PARAM_LIST_SCOPES) counts[s] = byScope?.get(s)?.seqCounter ?? 0
  return explainCapture(scope, st?.captured ?? null, st?.lastFast ?? null, counts)
}

