import { ref, type Ref } from 'vue'
import { analysisApi } from '../../../api/analysis'
import { ElMessage } from 'element-plus'

export function useBoxPlot(
  getFileId: () => number | null,
  selectedParams: Ref<string[]>,
  groupBy: Ref<string>
) {
  const loading = ref(false)
  const boxPlotData = ref<any>(null)

  async function loadBoxPlot() {
    const fileId = getFileId()
    if (!fileId || selectedParams.value.length === 0) {
      ElMessage.warning('请至少选择一个参数')
      return
    }

    loading.value = true
    try {
      const response = await analysisApi.getBoxPlot(
        fileId,
        selectedParams.value,
        groupBy.value || undefined
      )
      boxPlotData.value = response.data.results
      ElMessage.success('箱线图数据加载成功')
    } catch (error: any) {
      console.error('Failed to load box plot data:', error)
      ElMessage.error(error.response?.data?.error || '加载箱线图数据失败')
    } finally {
      loading.value = false
    }
  }

  return {
    loading,
    boxPlotData,
    loadBoxPlot,
  }
}
