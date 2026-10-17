/**
 * useAsyncData — 统一异步数据加载 composable
 *
 * 解决 9+ 个 analysis composable 中重复的 loading/error/try-catch/ElMessage 样板。
 * 错误提示由 axios 拦截器统一弹出（见 api/index.ts），这里只负责 loading
 * 状态和 error.value 内联展示数据。
 *
 * 三件事分开，别混：
 * ① **序号守卫**（一直就有）：过期响应不写 data/error，UI 只反映最后一次；
 * ② **中止在途请求**：新请求起来时 abort 上一个。只做 ① 的话，浏览器确实不再用旧响应，
 *    但服务端已经把那一趟算完了（实测 histogram 一次 57ms）——连切 20 个测试项就是
 *    20 次白烧，且这些白烧和新请求抢同一个单进程后端；
 * ③ **突发合并**（不在本文件，见 `useCoalescedCall`）：连点/连切时窗口内只发「第一次 + 最后一次」。
 *    它包在**调用方的加载函数**外面而不是这里——调用方通常在 `await run(...)` 之后还要把响应
 *    摊给图表（`useHistogram` 的 `histogramUpdateView`），合并在 `run` 里会让补发那一趟的
 *    后续处理被截断。
 *
 * 用法：
 * ```ts
 * const { loading, data, run } = useAsyncData<any>({ silent: true })
 * async function load() {
 *   await run((signal) => api.post('/analysis/foo/', { file_id: id }, { signal, silent: true }))
 * }
 * ```
 * fetcher 收到 `signal`（不接这个参数的旧调用方照常工作，只是拿不到中止能力）。
 */
import { ref, type Ref } from 'vue'
import { ElMessage } from 'element-plus'

import { formatError } from '../utils/error'

export interface UseAsyncDataOptions {
  successMsg?: string
  /** If true, suppress the success ElMessage notification */
  silent?: boolean
}

export interface UseAsyncDataReturn<T> {
  loading: Ref<boolean>
  data: Ref<T | null>
  error: Ref<string | null>
  /** Execute an async function with automatic loading/error handling.
   *  The fetcher receives an AbortSignal it should hand to axios.
   *  Optional `transform` maps the raw result to the desired value. */
  run: (
    fetcher: (signal?: AbortSignal) => Promise<any>,
    transform?: (raw: any) => T,
  ) => Promise<T | null>
}

/** 取消是「没有结果」，不是错误：ERR_CANCELED / CanceledError 两种形态都要认。 */
function isCancellation(e: any): boolean {
  return e?.code === 'ERR_CANCELED' || e?.name === 'CanceledError' || e?.name === 'AbortError'
}

export function useAsyncData<T = any>(opts?: UseAsyncDataOptions): UseAsyncDataReturn<T> {
  const loading = ref(false) as Ref<boolean>
  const data = ref<T | null>(null) as Ref<T | null>
  const error = ref<string | null>(null) as Ref<string | null>
  // 请求序号守卫：快速连续触发（切换参数/修改配置）时旧响应可能后到，
  // 只应用最后一次请求 —— 过期响应不写 data/error/successMsg，finally 中
  // 也不清空仍在途的最新请求的 loading。run() 对过期请求返回 null，
  // 调用方按"无结果"处理（与请求失败同语义，都不会污染 UI）。
  let seq = 0
  /** 当前在途请求的中止句柄；每次真正发请求前中止上一个。 */
  let controller: AbortController | null = null

  async function run(
    fetcher: (signal?: AbortSignal) => Promise<any>,
    transform?: (raw: any) => T,
  ): Promise<T | null> {
    controller?.abort()
    const myController = typeof AbortController !== 'undefined' ? new AbortController() : null
    controller = myController
    const mySeq = ++seq
    loading.value = true
    error.value = null
    try {
      const result = await fetcher(myController?.signal)
      if (mySeq !== seq) return null // 过期响应：丢弃
      // Auto-extract .data from axios responses, then apply optional transform
      const raw = (result && typeof result === 'object' && 'data' in result && !Array.isArray(result) && typeof result.data !== 'undefined')
        ? result.data
        : result
      const value = transform ? transform(raw) : (raw as T)
      data.value = value
      if (!opts?.silent && opts?.successMsg) ElMessage.success(opts.successMsg)
      return value
    } catch (e: any) {
      // 自己主动中止的那一趟：不写错误、不弹 toast（拦截器侧另有 isCancel 早退）。
      // 顺序很重要——必须在新请求已经 abort 旧请求之后判，否则过期请求的
      // CanceledError 会被当成真错误显示成「无法连接服务器」。
      if (isCancellation(e)) return null
      if (mySeq !== seq) return null // 过期请求的错误同样丢弃
      // 非中止的失败：toast 由 axios 拦截器统一弹出，这里只记录内联展示用的 error.value。
      error.value = formatError(e)
      return null
    } finally {
      if (mySeq === seq) loading.value = false
    }
  }

  return { loading, data, error, run }
}
