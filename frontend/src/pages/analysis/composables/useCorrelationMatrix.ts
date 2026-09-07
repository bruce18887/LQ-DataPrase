import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'
import { ElMessage } from 'element-plus'
import type { CorrelationFilterFlags } from './useCorrelation'

export function useCorrelationMatrix(getFileId: () => number | null) {
  const { loading, data: matrixData, run } = useAsyncData<any>()

  async function loadCorrelationMatrix(params?: string[],
                                       flags: CorrelationFilterFlags = {},
                                       method: string = 'pearson') {
    const fileId = getFileId()
    if (!fileId) { ElMessage.warning('请先选择数据文件'); return }
    const body: Record<string, any> = { file_id: fileId, ...flags }
    if (params && params.length > 0) body.params = params
    // 后端 correlation_matrix 支持 pearson/spearman/kendall（statistics_views
    // 校验非法值 400）；UI 于 2026-09-06 参照原型补暴露方法下拉
    body.method = method
    await run(() => api.post('/statistics/correlation_matrix/', body))
  }

  return { loading, matrixData, loadCorrelationMatrix }
}
