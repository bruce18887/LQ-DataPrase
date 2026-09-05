import { onScopeDispose, watch, type Ref } from 'vue'
import api from '../../../api'
import type { DataFile } from '../../../types'

/**
 * useTabFileParams —— 「一个 tab 选自己的文件、拉自己的参数列表」
 *
 * 参数列表来自 `POST /analysis/histogram/` 的不带 params 快路径（后端只回列名，
 * 不做直方图计算）。列表本身会随该 tab 的筛选开关收缩，所以开关变化要重取；
 * 一次连续勾选合并成一次请求（250ms 防抖），否则每勾一项都全文件重算一遍。
 *
 * 原 `AnalysisPage.onFileChange` 的四条守卫在这里逐 tab 复用：
 *  1. 过期响应守卫：并发时后到的旧文件响应不得覆盖新文件的列表；
 *  2. 参数自愈：预设参数（仪表板跳转写入）仍在新列表里就保留，否则回退首项；
 *  3. 空白列名过滤：某些解析器产出全 NaN 的未命名列，选中它必然 400；
 *  4. 文件被删/列表变更：选中项失效即重置，回落到列表首项。
 */

/** tab 侧需要读写的最小上下文（四个子 store 都满足） */
export interface TabFileCtx {
  fileId: Ref<number | null>
  params: Ref<string[]>
  loading: Ref<boolean>
  /** 晶圆图/相关性各自有参数选择，缺省则只维护列表 */
  selectedParam?: Ref<string>
}

/** 拉列表时携带的筛选载荷（键名 = 后端字段） */
export type TabFilterPayload = {
  ignore_no_limit?: boolean
  ignore_no_test_value?: boolean
  data_only_bin1?: boolean
  only_fail_test_item?: boolean
  only_low_cpk?: boolean
  iqr_multiplier?: number
}

const DEBOUNCE_MS = 250

export function useTabFileParams(opts: {
  ctx: TabFileCtx
  files: Ref<DataFile[]>
  /** 该 tab 的开关现值；不传则按中性值请求（晶圆图：后端不读这些字段） */
  filters?: () => TabFilterPayload
}) {
  const { ctx, files, filters } = opts
  let refreshTimer: ReturnType<typeof setTimeout> | null = null

  async function loadParams() {
    const fileId = ctx.fileId.value
    // 预设参数必须在清空前捕获：仪表板跳转会先把目标参数写进 store
    const preset = ctx.selectedParam?.value || ''
    if (!fileId) {
      ctx.params.value = []
      if (ctx.selectedParam) ctx.selectedParam.value = ''
      return
    }
    ctx.loading.value = true
    // 换文件后旧参数可能不存在于新文件，留着它发请求会 400/500；参数列表也
    // 必须同时清空，否则下拉会短暂提供旧文件的参数
    ctx.params.value = []
    // 先清预设再拉列表：不清的话，`useHistogram`/`useQQPlot` 等会拿着**上一个
    // 文件**的参数先打一次请求（实测 400 no_valid_params + 一个错误 toast），
    // 预设值已在上方记下，响应回来后按新列表重新选中
    if (ctx.selectedParam) ctx.selectedParam.value = ''
    try {
      const { data } = await api.post('/analysis/histogram/', {
        file_id: fileId,
        ...(filters ? filters() : {}),
      })
      // 过期响应守卫：自动加载的首个文件与用户手动选择并发时，慢到的旧响应
      // 不能用自己的列表覆盖新文件的列表
      if (data.file_id !== ctx.fileId.value) return
      const results = data.results as Record<string, unknown>
      ctx.params.value = Object.keys(results || {}).filter((p) => p && p.trim() !== '')
      if (ctx.selectedParam) {
        ctx.selectedParam.value = preset && ctx.params.value.includes(preset)
          ? preset
          : (ctx.params.value[0] ?? '')
      }
    } catch {
      // 错误 toast 由 axios 拦截器统一弹出
    } finally {
      ctx.loading.value = false
    }
  }

  /** 开关变化 → 防抖重取列表（列表本身按开关收缩） */
  function scheduleRefresh() {
    if (refreshTimer) clearTimeout(refreshTimer)
    refreshTimer = setTimeout(() => {
      refreshTimer = null
      loadParams()
    }, DEBOUNCE_MS)
  }

  // 文件：优先跟随用户已选，失效或为空时回落到列表首项
  watch(
    [() => ctx.fileId.value, files],
    ([id, list]) => {
      if (!list.length) {
        if (id !== null) ctx.fileId.value = null
        return
      }
      if (id === null || !list.some((f) => f.id === id)) ctx.fileId.value = list[0].id
    },
    { immediate: true },
  )

  watch(() => ctx.fileId.value, () => {
    loadParams()
  }, { immediate: true })

  if (filters) {
    watch(filters, scheduleRefresh, { deep: true })
  }

  onScopeDispose(() => {
    if (refreshTimer) clearTimeout(refreshTimer)
    refreshTimer = null
  })

  return { loadParams, scheduleRefresh }
}
