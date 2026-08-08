import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'

export function useCorrelation(
  getSelectedFileId: () => number | null
) {
  // useAsyncData 内建请求保序守卫：快速切换 X/Y 参数时旧响应不会覆盖新结果
  const { loading: corrLoading, data: corrResult, run } = useAsyncData<any>({
    silent: true,
  })

  async function loadCorrelation(x: string, y: string) {
    const fileId = getSelectedFileId()
    if (!fileId) return
    await run(() => api.post('/analysis/correlation/', {
      file_id: fileId,
      param_x: x,
      param_y: y,
    }))
  }

  return {
    corrLoading,
    corrResult,
    loadCorrelation,
  }
}
