import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'
import { ElMessage } from 'element-plus'

export function useCorrelationMatrix(getFileId: () => number | null) {
  const { loading, data: matrixData, run } = useAsyncData<any>({
    successMsg: '相关性矩阵计算完成',
    errorMsg: '相关性矩阵计算失败',
  })

  async function loadCorrelationMatrix() {
    const fileId = getFileId()
    if (!fileId) { ElMessage.warning('请先选择数据文件'); return }
    await run(() => api.post('/analysis/correlation_matrix/', { file_id: fileId }))
  }

  return { loading, matrixData, loadCorrelationMatrix }
}
