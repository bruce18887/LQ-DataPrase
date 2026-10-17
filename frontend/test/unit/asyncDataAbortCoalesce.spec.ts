import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// useAsyncData 在模块顶层 import ElMessage；T2 是 node 环境（无 DOM），
// 这里只把它桩掉，让被测的是守卫逻辑而不是 element-plus 的加载。
vi.mock('element-plus', () => ({ ElMessage: { success: vi.fn() } }))

import { useAsyncData } from '../../src/composables/useAsyncData'
import { useCoalescedCall } from '../../src/composables/useCoalescedCall'

/**
 * T2：`useAsyncData` 的中止守卫 + `useCoalescedCall` 的突发合并。
 *
 * useAsyncData 此前**一份测试都没有**（只被 e2e 间接压到），而这次要改的正是
 * 「过期那一趟到底发没发出去」「被中止的算不算错误」这类在浏览器里看不见的行为。
 * 下面每组断言都自带旧实现对照组：旧实现只有 seq 守卫（丢响应不丢请求），
 * 所以「signal 被 abort」「CanceledError 不写 error」在旧实现下必然失败，不是空断言。
 */

type Recorded = { signal?: AbortSignal; n: number }

/** 可控 fetcher：记录每次收到的 signal，手动 resolve/reject。 */
function makeGate() {
  const calls: Recorded[] = []
  const resolvers: Array<(v: any) => void> = []
  const rejecters: Array<(e: any) => void> = []
  const fetcher = (signal?: AbortSignal) =>
    new Promise<any>((resolve, reject) => {
      calls.push({ signal, n: calls.length + 1 })
      resolvers.push(resolve)
      rejecters.push(reject)
    })
  return { calls, resolvers, rejecters, fetcher }
}

/** axios 在 abort 时抛的形状。 */
const cancelError = () =>
  Object.assign(new Error('canceled'), { code: 'ERR_CANCELED', name: 'CanceledError' })

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers() })

describe('useAsyncData 中止在途请求', () => {
  it('新 run 起来时，上一个在途请求的 signal 被 abort', async () => {
    const gate = makeGate()
    const { run } = useAsyncData<any>({ silent: true })

    void run(gate.fetcher)
    await vi.advanceTimersByTimeAsync(0)
    expect(gate.calls).toHaveLength(1)
    expect(gate.calls[0].signal?.aborted).toBe(false)

    void run(gate.fetcher)
    await vi.advanceTimersByTimeAsync(0)
    expect(gate.calls).toHaveLength(2)
    // 旧实现到这里仍是 false ⇒ 请求继续占用单进程后端把整列算完
    expect(gate.calls[0].signal?.aborted).toBe(true)
    expect(gate.calls[1].signal?.aborted).toBe(false)
  })

  it('被 abort 那一趟不写 error（否则会显示成「无法连接服务器」）', async () => {
    const gate = makeGate()
    const { run, error, data } = useAsyncData<any>({ silent: true })

    const first = run(gate.fetcher)
    await vi.advanceTimersByTimeAsync(0)
    const second = run(gate.fetcher)
    await vi.advanceTimersByTimeAsync(0)

    gate.rejecters[0](cancelError())
    expect(await first).toBeNull()
    expect(error.value).toBeNull()

    gate.resolvers[1]({ ok: 2 })
    expect(await second).toEqual({ ok: 2 })
    expect(data.value).toEqual({ ok: 2 })
    expect(error.value).toBeNull()
  })

  it('真失败仍然要写 error —— 中止的静默不能顺手吞掉真错误', async () => {
    const gate = makeGate()
    const { run, error } = useAsyncData<any>({ silent: true })

    const p = run(gate.fetcher)
    await vi.advanceTimersByTimeAsync(0)
    gate.rejecters[0](Object.assign(new Error('boom'), {
      response: { status: 500, data: { message: '服务器炸了' } },
    }))
    expect(await p).toBeNull()
    expect(error.value).toBeTruthy()
  })

  it('过期那趟晚到的成功响应不覆盖 data，也不清掉仍在途的 loading', async () => {
    const gate = makeGate()
    const { run, data, loading } = useAsyncData<any>({ silent: true })

    const stale = run(gate.fetcher)
    await vi.advanceTimersByTimeAsync(0)
    const fresh = run(gate.fetcher)
    await vi.advanceTimersByTimeAsync(0)

    gate.resolvers[0]({ tag: 'stale' })
    expect(await stale).toBeNull()
    expect(loading.value).toBe(true)

    gate.resolvers[1]({ tag: 'fresh' })
    expect(await fresh).toEqual({ tag: 'fresh' })
    expect(data.value).toEqual({ tag: 'fresh' })
    expect(loading.value).toBe(false)
  })
})

describe('useCoalescedCall 突发合并（leading + trailing）', () => {
  it('孤立的一次调用立即执行——单次切换不加 150ms 延迟', () => {
    const seen: number[] = []
    const call = useCoalescedCall((n: number) => seen.push(n), 150)
    call(1)
    expect(seen).toEqual([1]) // 未 advance 任何时间
  })

  it('窗口内连发 5 次只跑 2 次：第一次立即 + 最后一次到点', () => {
    const seen: number[] = []
    const call = useCoalescedCall((n: number) => seen.push(n), 150)

    call(1)                 // leading
    vi.advanceTimersByTime(20)
    call(2); call(3); call(4)
    vi.advanceTimersByTime(20)
    call(5)
    expect(seen).toEqual([1]) // 中间 2/3/4/5 都不该执行

    vi.advanceTimersByTime(150)
    expect(seen).toEqual([1, 5]) // 补发的是「最后一次」的参数
  })

  it('每来一次新调用就重新计时（连着点不会在半路提前发中间态）', () => {
    const seen: number[] = []
    const call = useCoalescedCall((n: number) => seen.push(n), 150)
    call(1)
    for (let i = 2; i <= 6; i++) {
      vi.advanceTimersByTime(100)   // 每次都短于窗口
      call(i)
    }
    expect(seen).toEqual([1])
    vi.advanceTimersByTime(150)
    expect(seen).toEqual([1, 6])
  })

  it('窗口关掉后再来一次，仍然立即执行（窗口会重新武装）', () => {
    const seen: number[] = []
    const call = useCoalescedCall((n: number) => seen.push(n), 150)
    call(1)
    call(2)
    vi.advanceTimersByTime(150)
    expect(seen).toEqual([1, 2])
    call(3)
    expect(seen).toEqual([1, 2, 3]) // 立即，不等窗口
  })

  it('没有后续调用时不会凭空补发一次', () => {
    const seen: number[] = []
    const call = useCoalescedCall((n: number) => seen.push(n), 150)
    call(1)
    vi.advanceTimersByTime(1000)
    expect(seen).toEqual([1])
  })

  it('参数按最后一次整组传递（不是只换第一个入参）', () => {
    const seen: Array<[number, string]> = []
    const call = useCoalescedCall((n: number, s: string) => seen.push([n, s]), 150)
    call(1, 'a')
    call(2, 'b')
    call(3, 'c')
    vi.advanceTimersByTime(150)
    expect(seen).toEqual([[1, 'a'], [3, 'c']])
  })
})
