import { describe, expect, it } from 'vitest'

import {
  attachParamListCapture,
  capturedParamList,
  explainParamListCapture,
  setActiveAnalysisTab,
} from '../../e2e/helpers/paramList'
import {
  decideCaptured,
  entryFromFastResponse,
  explainCapture,
  paramKeysFromResults,
  parseFastRequest,
  resolveScope,
  shouldAcceptCapture,
  type CapturedEntry,
  type FastReqInfo,
  type ParamListScope,
} from '../../e2e/helpers/paramListCore'

/**
 * T2：参数全集捕获守卫的**判定**（纯核，不开浏览器）。
 *
 * 判据异源纪律：这里钉的是「守卫怎么判」，**不是**「守卫在真浏览器里挡住了那个 flake」——
 * 后者仍由 e2e 兜（chart-filter-switches / outlier-handling）。别在这里假装验了浏览器行为。
 *
 * 每条用例对应的都是 2026-11-13 复审抓出的真实数据形状（同 file_id、body 加
 * only_fail_test_item:true ⇒ lastFast 推进到新 seq 而 fileId 相等 ⇒ 旧的
 * 「比 file_id」守卫放行 ⇒ 返回上一个口径的列表，poll(length>0) 立刻通过）。
 */

const sent = (seq: number, fileId: unknown): FastReqInfo => ({ seq, fileId })
const cap = (seq: number, fileId: unknown, keys: string[], status = 200): CapturedEntry => ({
  seq,
  fileId,
  status,
  keys,
})
const noSent: Record<ParamListScope, number> = { single: 0, wafer: 0, correlation: 0 }

describe('decideCaptured —— 「这一发结算了吗」，不是「文件变了吗」', () => {
  // 复审 C-1 的确定性复现：口径变了（seq 3→4）但 file_id 一直是 1。
  it('同 file_id、seq 推进、新响应未结算 ⇒ null（绝不回吐上一个口径的列表）', () => {
    expect(decideCaptured(cap(3, 1, ['A', 'B', 'C']), sent(4, 1))).toBeNull()
  })

  it('同 file_id、新响应已结算 ⇒ 给新 keys（旧 keys 一律作废）', () => {
    expect(decideCaptured(cap(4, 1, ['A']), sent(4, 1))).toEqual(['A'])
  })

  // 复审 C-2：旧实现有 keys.length>0 那道闸，当前口径返回 results:{} 时
  // 会把上一份列表当结果吐回去，与 chart-filter-switches:114「允许为空」直接冲突。
  it('新响应 0 项且已结算 ⇒ []，不是上一份列表', () => {
    expect(decideCaptured(cap(5, 1, []), sent(5, 1))).toEqual([])
    // 上一份非空也救不回来：判据只有 seq 对齐，没有「非空」偏置。
    expect(decideCaptured(cap(5, 1, []), sent(6, 1))).toBeNull()
  })

  it('换文件后新文件未结算 ⇒ null（旧 file_id 守卫的原有职责不能丢）', () => {
    expect(decideCaptured(cap(2, 7, ['OLD_1', 'OLD_2']), sent(3, 9))).toBeNull()
  })

  it('一条响应都没处理过 ⇒ null', () => {
    expect(decideCaptured(null, sent(1, 1))).toBeNull()
  })

  it('还没发出过快路径请求（没选文件）⇒ null，且不看 captured', () => {
    expect(decideCaptured(cap(1, 1, ['A']), null)).toBeNull()
  })

  // 反向探针：守卫不能退化成「有值就给」。把 seq 对齐判据按位置取数（数组下标）
  // 之类的写法放回来，这一条就红。
  it('反向探针：captured.seq 大于 lastFast.seq 同样不给值（不可能状态不许当通行证）', () => {
    expect(decideCaptured(cap(9, 1, ['A']), sent(8, 1))).toBeNull()
  })
})

describe('shouldAcceptCapture —— 迟到响应不得覆盖新响应', () => {
  // 两条快路径请求乱序 resolve：seq 6 先发先回，seq 5 的慢响应后到。
  it('旧 seq 晚到 ⇒ 不覆盖新 seq 的结果', () => {
    const fresh = cap(6, 1, ['NEW'])
    expect(shouldAcceptCapture(fresh, cap(5, 1, ['OLD']))).toBe(false)
    expect(shouldAcceptCapture(fresh, cap(7, 1, ['NEWER']))).toBe(true)
  })

  it('空列表也要能被写入（拒写空集的闸是净负价值）', () => {
    expect(shouldAcceptCapture(cap(5, 1, ['A', 'B']), cap(6, 1, []))).toBe(true)
  })

  it('同一 seq 重复结算（重定向链 / 二次响应）允许自更新', () => {
    expect(shouldAcceptCapture(cap(6, 1, []), cap(6, 1, ['A']))).toBe(true)
  })

  it('首条捕获无条件接受', () => {
    expect(shouldAcceptCapture(null, cap(1, 1, []))).toBe(true)
  })
})

describe('entryFromFastResponse —— 「结算」与「结果非空」彻底拆开', () => {
  it('200 带 results ⇒ keys 按后端顺序，空白列名丢掉', () => {
    expect(
      entryFromFastResponse(sent(2, 1), 200, { results: { B: {}, '': {}, A: {}, '  ': {} } }).keys
    ).toEqual(['B', 'A'])
  })

  it('200 但 results 为空对象 ⇒ 结算 + keys:[]', () => {
    const e = entryFromFastResponse(sent(7, 1), 200, { results: {} })
    expect(e.keys).toEqual([])
    expect(e.seq).toBe(7)
  })

  // 旧实现 `status() !== 200` 直接 return，一发 400 就把 listParams 锁死 15s。
  it('非 200（400/500）也算结算 ⇒ seq 照样推进，keys 为空', () => {
    const e = entryFromFastResponse(sent(8, 1), 400, { detail: 'no_valid_params' })
    expect(e.seq).toBe(8)
    expect(e.keys).toEqual([])
    expect(decideCaptured(e, sent(8, 1))).toEqual([])
  })

  it('200 但响应体不是 JSON ⇒ 仍是结算的空集，不抛', () => {
    expect(entryFromFastResponse(sent(9, 1), 200, undefined).keys).toEqual([])
    expect(entryFromFastResponse(sent(9, 1), 200, '<html>500</html>').keys).toEqual([])
  })

  it('status 记进条目，供超时诊断区分「后端真给空集」与「这发出错了」', () => {
    expect(entryFromFastResponse(sent(3, 1), 500, null).status).toBe(500)
  })
})

describe('paramKeysFromResults', () => {
  it('过滤条件与前端 useTabFileParams.ts:87 逐字一致', () => {
    expect(paramKeysFromResults({ A: {}, '': {}, 'B': {}, ' ': {} })).toEqual(['A', 'B'])
  })
  it('非对象 / undefined 都当空集，不抛', () => {
    expect(paramKeysFromResults(undefined)).toEqual([])
    expect(paramKeysFromResults(null)).toEqual([])
    expect(paramKeysFromResults('oops')).toEqual([])
    expect(paramKeysFromResults([1, 2])).toEqual([])
  })
})

describe('parseFastRequest —— 快路径 = 不带 params 的那一发', () => {
  it('带 params 的是计算请求，其 results 只有被算的几项 ⇒ 判 null', () => {
    expect(
      parseFastRequest('/analysis/histogram/', 'POST', '{"file_id":1,"params":["A"]}')
    ).toBeNull()
  })

  it('快路径给 fileId 与「是否带筛选字段」', () => {
    expect(parseFastRequest('/analysis/histogram/', 'POST', '{"file_id":1}')).toEqual({
      fileId: 1,
      hasFilters: false,
    })
    expect(
      parseFastRequest('/analysis/histogram/', 'POST', '{"file_id":2,"only_fail_test_item":true}')
    ).toEqual({ fileId: 2, hasFilters: true })
  })

  it('不是这个端点 / 不是 POST ⇒ null', () => {
    expect(parseFastRequest('/analysis/qqplot/', 'POST', '{"file_id":1}')).toBeNull()
    expect(parseFastRequest('/analysis/histogram/', 'GET', '')).toBeNull()
  })

  it('体不是 JSON ⇒ fileId:null 但仍算快路径（不能因为读不懂就放行旧值）', () => {
    expect(parseFastRequest('/analysis/histogram/', 'POST', 'not-json')).toEqual({
      fileId: null,
      hasFilters: false,
    })
    expect(parseFastRequest('/analysis/histogram/', 'POST', null)).toBeNull()
  })
})

describe('resolveScope —— tab 归属（复审 I-4）', () => {
  it('不带筛选字段的快路径只可能是晶圆图 tab（WaferMapPanel 拉列表不传 filters）', () => {
    expect(resolveScope({ hasFilters: false }, 'single')).toBe('wafer')
    expect(resolveScope({ hasFilters: false }, 'correlation')).toBe('wafer')
  })
  it('带筛选字段的归给用例显式声明的 scope（单文件与相关性请求体形状相同，无从自动区分）', () => {
    expect(resolveScope({ hasFilters: true }, 'single')).toBe('single')
    expect(resolveScope({ hasFilters: true }, 'correlation')).toBe('correlation')
  })
})

describe('explainCapture —— 超时消息必须分得清四种成因', () => {
  it('已结算 ⇒ "settled"（poll 的期望值）', () => {
    expect(explainCapture('single', cap(4, 1, ['A']), sent(4, 1), noSent)).toBe('settled')
  })

  // 成因①②：本 scope 一条快路径都没发过 —— 用其他 scope 的计数区分「没选文件」与「监听装晚了」。
  it('本 scope 没发过请求，且任何 scope 都没发过 ⇒ 指向监听/导航时机', () => {
    const msg = explainCapture('single', null, null, noSent)
    expect(msg).toMatch(/未发出/)
    expect(msg).toMatch(/监听装晚了/)
    expect(msg).toMatch(/single=0 wafer=0 correlation=0/)
  })
  it('本 scope 没发过请求，但别的 scope 发过 ⇒ 监听在装，只是该 tab 还没选文件', () => {
    const msg = explainCapture('correlation', null, null, { single: 3, wafer: 0, correlation: 0 })
    expect(msg).toMatch(/single=3/)
    expect(msg).not.toMatch(/监听装晚了/)
  })
  // 漏声明 scope 是 I-4 之后最常见的自伤，消息必须点名（否则下个人只看到「没选文件」）。
  it('同上 ⇒ 消息点名 setActiveAnalysisTab 这条出路', () => {
    expect(explainCapture('correlation', null, null, { single: 3, wafer: 0, correlation: 0 }))
      .toMatch(/setActiveAnalysisTab\(page, 'correlation'\)/)
  })

  // 成因③：同文件换口径未落地（就是 C-1 那条复现）
  it('同 file_id、新 seq 未结算 ⇒ 消息带 seq / fileId / keys.length', () => {
    const msg = explainCapture('single', cap(3, 1, ['A', 'B', 'C']), sent(4, 1), { single: 4, wafer: 0, correlation: 0 })
    expect(msg).toMatch(/未结算/)
    expect(msg).toMatch(/captured\.seq=3/)
    expect(msg).toMatch(/lastFast\.seq=4/)
    expect(msg).toMatch(/fileId 都是 1/)
    expect(msg).toMatch(/captured\.keys=3/)
  })

  // 成因④：当前口径真返回 0 项 —— 结算了，空集是合法结果，交给用例的断言去红
  it('结算且 0 项 ⇒ "settled"（不许把空集当未就绪去死等）', () => {
    expect(explainCapture('single', cap(4, 1, []), sent(4, 1), noSent)).toBe('settled')
  })

  // 非 200 结算 ⇒ 仍以 settled 开头（poll 必须放行，让用例自己的断言去红），
  // 但消息里带上 status，读日志的人分得清「后端真给空集」与「这发出错了」。
  it('非 200 结算 ⇒ 照常放行，但消息带 status', () => {
    const e = entryFromFastResponse(sent(4, 1), 400, { detail: 'x' })
    const msg = explainCapture('single', e, sent(4, 1), noSent)
    expect(msg.startsWith('settled')).toBe(true)
    expect(msg).toMatch(/status=400/)
  })
})

// ---------------------------------------------------------------------------
// 接线层：用**假的事件序列**驱动 paramList.ts 的 request/response handler。
// paramList.ts 只 `import type` Playwright，运行时零依赖 ⇒ 这一档同样不开浏览器。
// 钉的是「事件进来以后状态怎么变」，浏览器里那次真竞态仍归 e2e 兜。
// ---------------------------------------------------------------------------

type Handler = (arg: any) => void

class FakePage {
  private handlers: Record<string, Handler[]> = { request: [], response: [] }

  on(event: string, cb: Handler): void {
    this.handlers[event].push(cb)
  }

  /** 依次跑完该事件的所有 handler，再等 microtask 队列排空（handler 里 await json()） */
  async emit(event: string, arg: unknown): Promise<void> {
    for (const cb of this.handlers[event]) cb(arg)
    await new Promise((r) => setTimeout(r, 0))
  }
}

const FAST_URL = 'http://127.0.0.1:8000/api/analysis/histogram/'

function fakeRequest(body: string | null) {
  return { url: () => FAST_URL, method: () => 'POST', postData: () => body }
}

function fakeResponse(
  req: ReturnType<typeof fakeRequest>,
  status: number,
  json: unknown,
  gate?: Promise<void>,
) {
  return {
    request: () => req,
    status: () => status,
    json: async () => {
      if (gate) await gate
      if (json instanceof Error) throw json
      return json
    },
  }
}

async function attached() {
  const page = new FakePage()
  attachParamListCapture(page as unknown as Parameters<typeof attachParamListCapture>[0])
  return page
}

/**
 * **带筛选字段**的快路径负载形状：`useTabFileParams.ts:79-82` 的 `{file_id, ...filters()}`。
 * 单文件（`SingleParamTab.vue:321-333`）与相关性（`CorrelationToolsTab.vue:200-216`）
 * 两个 tab 的 filters() 键集**逐字相同** —— 这正是 I-4 里「产品没在请求里留 tab 身份、
 * 那两者无从自动区分」的形状证据，所以这个 helper 不叫 singleBody。
 * ⚠ 不带筛选字段的体会被归属到**晶圆图**桶（WaferMapPanel.vue:105-109 拉列表不传 filters），
 * 测带 filters 的桶时必须用这个形状，别手写 `{"file_id":1}`。
 */
function withFiltersBody(fileId: number, filters: Record<string, unknown> = {}): string {
  return JSON.stringify({
    file_id: fileId,
    ignore_no_limit: false,
    ignore_no_test_value: false,
    data_only_bin1: false,
    only_fail_test_item: false,
    only_low_cpk: false,
    iqr_multiplier: 1.5,
    ...filters,
  })
}

/** 晶圆图 tab 的负载：只有 file_id。 */
function waferBody(fileId: number): string {
  return JSON.stringify({ file_id: fileId })
}

/** 发一发并让它的响应结算，返回该请求对象（后续要控制到达顺序时用 gate 延后）。 */
async function send(page: FakePage, body: string | null) {
  const req = fakeRequest(body)
  await page.emit('request', req)
  return req
}

describe('接线层：同 file_id 换口径（复审 C-1 的确定性复现）', () => {
  it('新响应未结算 ⇒ null；结算 ⇒ 新 keys', async () => {
    const page = await attached()
    const first = await send(page, withFiltersBody(1))
    await page.emit('response', fakeResponse(first, 200, { results: { A: {}, B: {}, C: {} } }))
    expect(capturedParamList(page as never)).toEqual(['A', 'B', 'C'])

    // 勾上「仅显示Fail测试项」：file_id 仍是 1，只有 body 与序号变了
    const second = await send(page, withFiltersBody(1, { only_fail_test_item: true }))
    expect(capturedParamList(page as never), '旧实现在这里回吐上一个口径的 3 项').toBeNull()
    expect(explainParamListCapture(page as never)).toMatch(/未结算/)
    expect(explainParamListCapture(page as never)).toMatch(/fileId 都是 1/)

    await page.emit('response', fakeResponse(second, 200, { results: { A: {} } }))
    expect(capturedParamList(page as never)).toEqual(['A'])
  })

  it('当前口径真返回 results:{} ⇒ 空数组，不是上一份列表（复审 C-2 的契约冲突）', async () => {
    const page = await attached()
    const a = await send(page, withFiltersBody(1, { only_fail_test_item: true }))
    await page.emit('response', fakeResponse(a, 200, { results: { KEEP: {} } }))
    const b = await send(page, withFiltersBody(1, { only_fail_test_item: true, only_low_cpk: true }))
    await page.emit('response', fakeResponse(b, 200, { results: {} }))
    expect(capturedParamList(page as never)).toEqual([])
    expect(explainParamListCapture(page as never)).toBe('settled')
  })

  it('一发 400 也要结算，否则 listParams 被锁死 15s', async () => {
    const page = await attached()
    const ok = await send(page, withFiltersBody(1))
    await page.emit('response', fakeResponse(ok, 200, { results: { A: {} } }))
    const bad = await send(page, withFiltersBody(999))
    await page.emit('response', fakeResponse(bad, 400, { detail: 'no_valid_params' }))
    expect(capturedParamList(page as never)).toEqual([])
    expect(explainParamListCapture(page as never)).toMatch(/^settled .*status=400/)
  })

  it('响应体读不出（已销毁 / 非 JSON）⇒ 同样结算成空集，不抛', async () => {
    const page = await attached()
    const req = await send(page, withFiltersBody(1))
    await page.emit('response', fakeResponse(req, 200, new Error('Response has been disposed')))
    expect(capturedParamList(page as never)).toEqual([])
  })

  it('乱序 resolve：旧 seq 的响应晚到也不覆盖新 seq 的结果', async () => {
    const page = await attached()
    const slow = await send(page, withFiltersBody(1))
    const fast = await send(page, withFiltersBody(2))
    let release!: () => void
    const gate = new Promise<void>((r) => {
      release = r
    })
    await page.emit('response', fakeResponse(fast, 200, { results: { NEW_FILE: {} } }))
    expect(capturedParamList(page as never)).toEqual(['NEW_FILE'])
    // 早发出的那一发此刻才回来（json 被 gate 卡住 ⇒ handler 排在最后）
    await page.emit('response', fakeResponse(slow, 200, { results: { OLD_FILE: {} } }, gate))
    release()
    await new Promise((r) => setTimeout(r, 0))
    expect(capturedParamList(page as never)).toEqual(['NEW_FILE'])
  })

  it('带 params 的计算请求完全不进任何桶（不然会把全集算成一项）', async () => {
    const page = await attached()
    await send(page, '{"file_id":1,"params":["A"]}')
    expect(capturedParamList(page as never)).toBeNull()
    expect(explainParamListCapture(page as never)).toMatch(/single=0 wafer=0 correlation=0/)
  })
})

describe('接线层：tab 归属分桶（复审 I-4）', () => {
  it('晶圆图的快路径（不传 filters）自动归 wafer，不污染单文件桶', async () => {
    const page = await attached()
    const single = await send(page, withFiltersBody(1))
    await page.emit('response', fakeResponse(single, 200, { results: { SINGLE_ONLY: {} } }))
    const wafer = await send(page, waferBody(42))
    await page.emit('response', fakeResponse(wafer, 200, { results: { WAFER_ONLY: {} } }))
    expect(capturedParamList(page as never, 'wafer' as ParamListScope)).toEqual(['WAFER_ONLY'])
    expect(capturedParamList(page as never), '单文件桶不能被晶圆图那一发顶掉').toEqual(['SINGLE_ONLY'])
  })

  it('相关性 tab 必须先用 setActiveAnalysisTab 声明，声明后的请求才进它的桶', async () => {
    const page = await attached()
    const early = await send(page, withFiltersBody(1))
    await page.emit('response', fakeResponse(early, 200, { results: { SINGLE_ONLY: {} } }))

    setActiveAnalysisTab(page as never, 'correlation' as ParamListScope)
    const corr = await send(page, withFiltersBody(7, { ignore_no_limit: true }))
    await page.emit('response', fakeResponse(corr, 200, { results: { CORR_ONLY: {} } }))
    expect(capturedParamList(page as never, 'correlation' as ParamListScope)).toEqual(['CORR_ONLY'])
    // 单文件桶停在它自己那一发上（相关性那一发 file_id=7 也没把它顶掉）
    expect(capturedParamList(page as never)).toEqual(['SINGLE_ONLY'])
    // 没声明过时读相关性 ⇒ 报「本 tab 还没选文件」而不是别的 tab 的列表
    const fresh = await attached()
    expect(capturedParamList(fresh as never, 'correlation' as ParamListScope)).toBeNull()
    expect(explainParamListCapture(fresh as never, 'correlation' as ParamListScope)).toMatch(/未发出/)
  })
})
