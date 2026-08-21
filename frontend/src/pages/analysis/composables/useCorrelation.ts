import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'

/** 数据筛选开关载荷（与 histogram 5 开关同口径，2026-08-20） */
export interface CorrelationFilterFlags {
  ignore_no_limit?: boolean
  ignore_no_test_value?: boolean
  data_only_bin1?: boolean
  only_fail_test_item?: boolean
  only_low_cpk?: boolean
  iqr_multiplier?: number
}

export function useCorrelation(
  getSelectedFileId: () => number | null
) {
  // useAsyncData 内建请求保序守卫：快速切换 X/Y 参数时旧响应不会覆盖新结果
  const { loading: corrLoading, data: corrResult, run } = useAsyncData<any>({
    silent: true,
  })

  async function loadCorrelation(x: string, y: string,
                                 flags: CorrelationFilterFlags = {}) {
    const fileId = getSelectedFileId()
    if (!fileId) return
    await run(() => api.post('/analysis/correlation/', {
      file_id: fileId,
      param_x: x,
      param_y: y,
      ...flags,
    }))
  }

  return {
    corrLoading,
    corrResult,
    loadCorrelation,
  }
}
