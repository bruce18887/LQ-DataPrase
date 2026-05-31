import { ref } from 'vue'
import api from '../../../api'
import { ElMessage } from 'element-plus'

export function useFileCorrelation() {
  const loading = ref(false)
  const result = ref<any>(null)

  async function loadFileCorrelation(file1: number, file2: number, threshold: number) {
    if (!file1 || !file2) {
      ElMessage.warning('请选择两个文件')
      return
    }

    loading.value = true
    try {
      const { data } = await api.post('/correlation/analyze/', {
        file1_id: file1,
        file2_id: file2,
        threshold
      })
      result.value = data
      ElMessage.success('文件相关性分析完成')
    } catch (error: any) {
      console.error('Failed to analyze file correlation:', error)
      ElMessage.error(error.response?.data?.error || '文件相关性分析失败')
    } finally {
      loading.value = false
    }
  }

  return {
    loading,
    result,
    loadFileCorrelation,
  }
}
