import { type Ref } from 'vue'
import { analysisApi } from '../../../api/analysis'
import { useAsyncData } from '../../../composables/useAsyncData'
import { ElMessage } from 'element-plus'

export function useParameterTrend(
  selectedFileIds: Ref<number[]>,
  selectedParam: Ref<string>
) {
  const { loading, data: trendData, run } = useAsyncData<any>({
    successMsg: '参数趋势数据加载成功',
    errorMsg: '加载参数趋势数据失败',
  })

  async function loadParameterTrend() {
    if (selectedFileIds.value.length < 2) { ElMessage.warning('请至少选择2个文件'); return }
    if (!selectedParam.value) { ElMessage.warning('请选择参数'); return }
    await run(() => analysisApi.getParamTrend(selectedFileIds.value, selectedParam.value))
  }

  return { loading, trendData, loadParameterTrend }
}
