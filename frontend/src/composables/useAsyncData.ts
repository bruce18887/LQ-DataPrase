/**
 * useAsyncData — 统一异步数据加载 composable
 *
 * 解决 9+ 个 analysis composable 中重复的 loading/error/try-catch/ElMessage 样板。
 * 错误提示由 axios 拦截器统一弹出（见 api/index.ts），这里只负责 loading
 * 状态和 error.value 内联展示数据。
 *
 * 用法：
 * ```ts
 * const { loading, data, run } = useAsyncData<any>({ successMsg: '加载成功' })
 * async function load() {
 *   if (!fileId) { ElMessage.warning('请选择文件'); return }
 *   await run(() => api.post('/analysis/foo/', { file_id: fileId }))
 * }
 * ```
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
   *  Optional `transform` maps the raw result to the desired value. */
  run: (fetcher: () => Promise<any>, transform?: (raw: any) => T) => Promise<T | null>
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

  async function run(fetcher: () => Promise<any>, transform?: (raw: any) => T): Promise<T | null> {
    const mySeq = ++seq
    loading.value = true
    error.value = null
    try {
      const result = await fetcher()
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
      if (mySeq !== seq) return null // 过期请求的错误同样丢弃
      // 错误 toast 由 axios 拦截器统一弹出（api/index.ts），这里只记录
      // 内联展示用的 error.value。
      error.value = formatError(e)
      return null
    } finally {
      if (mySeq === seq) loading.value = false
    }
  }

  return { loading, data, error, run }
}
