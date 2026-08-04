import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'
import { ElMessage } from 'element-plus'

export function useCorrelationMatrix(getFileId: () => number | null) {
  const { loading, data: matrixData, run } = useAsyncData<any>()

  async function loadCorrelationMatrix(params?: string[]) {
    const fileId = getFileId()
    if (!fileId) { ElMessage.warning('请先选择数据文件'); return }
    const body: Record<string, any> = { file_id: fileId }
    if (params && params.length > 0) body.params = params
    await run(() => api.post('/statistics/correlation_matrix/', body))
  }

  return { loading, matrixData, loadCorrelationMatrix }
}
