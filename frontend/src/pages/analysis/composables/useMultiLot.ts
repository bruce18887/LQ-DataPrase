import { ref, type Ref } from 'vue'
import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'
import { ElMessage } from 'element-plus'

export function useMultiLot(
  selectedFileIds: Ref<number[]>,
  selectedParam: Ref<string>
) {
  const summary = ref<any[]>([])
  const commonParams = ref<string[]>([])
  const { loading, data: lotData, run } = useAsyncData<any>({
    successMsg: '多Lot对比数据加载成功',
    errorMsg: '加载多Lot对比数据失败',
  })

  async function loadMultiLot() {
    if (selectedFileIds.value.length < 2) { ElMessage.warning('请至少选择2个文件'); return }
    if (!selectedParam.value) { ElMessage.warning('请选择参数'); return }
    const result = await run(() => api.post('/analysis/multi_lot/', {
      file_ids: selectedFileIds.value,
      param: selectedParam.value,
    }))
    if (result) {
      summary.value = result.lot_data || []
      commonParams.value = result.common_params || commonParams.value
    }
  }

  return { loading, lotData, summary, commonParams, loadMultiLot }
}
