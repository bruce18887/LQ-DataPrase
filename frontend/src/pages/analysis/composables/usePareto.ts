import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

export function usePareto(
  getFileId: () => number | null
) {
  const loading = ref(false)
  const paretoData = ref<any>(null)

  async function loadPareto() {
    const fileId = getFileId()
    if (!fileId) {
      ElMessage.warning('请先选择数据文件')
      return
    }

    loading.value = true
    try {
      // TODO: 替换为实际API调用
      // const response = await api.post('/analysis/pareto/', { file_id: fileId })
      // paretoData.value = response.data

      // Mock data for now
      const categories = ['Test_Item_1', 'Test_Item_2', 'Test_Item_3', 'Test_Item_4', 'Test_Item_5']
      const values = [150, 80, 45, 30, 20]
      const total = values.reduce((sum, val) => sum + val, 0)

      const cumulative: number[] = []
      let cumulativeSum = 0
      values.forEach(val => {
        cumulativeSum += val
        cumulative.push((cumulativeSum / total) * 100)
      })

      paretoData.value = { categories, values, cumulative }
      ElMessage.success('Pareto数据加载成功')
    } catch (error: any) {
      console.error('Failed to load Pareto data:', error)
      // 错误 toast 由 axios 拦截器统一弹出
    } finally {
      loading.value = false
    }
  }

  // Auto-load when fileId changes
  watch(getFileId, (newFileId) => {
    if (newFileId) {
      loadPareto()
    } else {
      paretoData.value = null
    }
  }, { immediate: true })

  return {
    loading,
    paretoData,
    loadPareto,
  }
}
