import { ref, type Ref } from 'vue'
import { analysisApi } from '../../../api/analysis'
import { ElMessage } from 'element-plus'

export function useParameterTrend(
  selectedFileIds: Ref<number[]>,
  selectedParam: Ref<string>
) {
  const loading = ref(false)
  const trendData = ref<any>(null)

  async function loadParameterTrend() {
    if (selectedFileIds.value.length < 2) {
      ElMessage.warning('请至少选择2个文件')
      return
    }

    if (!selectedParam.value) {
      ElMessage.warning('请选择参数')
      return
    }

    loading.value = true
    try {
      const response = await analysisApi.getParamTrend(
        selectedFileIds.value,
        selectedParam.value
      )
      trendData.value = response.data
      ElMessage.success('参数趋势数据加载成功')
    } catch (error: any) {
      console.error('Failed to load parameter trend data:', error)
      ElMessage.error(error.response?.data?.error || '加载参数趋势数据失败')
    } finally {
      loading.value = false
    }
  }

  return {
    loading,
    trendData,
    loadParameterTrend,
  }
}
