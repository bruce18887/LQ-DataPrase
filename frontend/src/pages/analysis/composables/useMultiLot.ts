import { ref, type Ref } from 'vue'
import api from '../../../api'
import { ElMessage } from 'element-plus'

export function useMultiLot(
  selectedFileIds: Ref<number[]>,
  selectedParam: Ref<string>
) {
  const loading = ref(false)
  const lotData = ref<any>(null)
  const summary = ref<any[]>([])
  const commonParams = ref<string[]>([])

  async function loadMultiLot() {
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
      const { data } = await api.post('/analysis/multi_lot/', {
        file_ids: selectedFileIds.value,
        param: selectedParam.value
      })
      lotData.value = data
      summary.value = data.lot_data || []
      commonParams.value = data.common_params || commonParams.value
      ElMessage.success('多Lot对比数据加载成功')
    } catch (error: any) {
      console.error('Failed to load multi-lot data:', error)
      ElMessage.error(error.response?.data?.error || '加载多Lot对比数据失败')
    } finally {
      loading.value = false
    }
  }

  return {
    loading,
    lotData,
    summary,
    commonParams,
    loadMultiLot,
  }
}
