import { ref } from 'vue'
import api from '../../../api'
import { ElMessage } from 'element-plus'

export function useCorrelationMatrix(
  getFileId: () => number | null
) {
  const loading = ref(false)
  const matrixData = ref<any>(null)

  async function loadCorrelationMatrix() {
    const fileId = getFileId()
    if (!fileId) {
      ElMessage.warning('请先选择数据文件')
      return
    }

    loading.value = true
    try {
      const { data } = await api.post('/analysis/correlation_matrix/', {
        file_id: fileId
      })
      matrixData.value = data
      ElMessage.success('相关性矩阵计算完成')
    } catch (error: any) {
      console.error('Failed to calculate correlation matrix:', error)
      ElMessage.error(error.response?.data?.error || '相关性矩阵计算失败')
    } finally {
      loading.value = false
    }
  }

  return {
    loading,
    matrixData,
    loadCorrelationMatrix,
  }
}
