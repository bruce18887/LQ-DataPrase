import { type Ref } from 'vue'
import { analysisApi } from '../../../api/analysis'
import { useAsyncData } from '../../../composables/useAsyncData'
import { ElMessage } from 'element-plus'

export function useBoxPlot(
  getFileId: () => number | null,
  selectedParams: Ref<string[]>,
  groupBy: Ref<string>
) {
  const { loading, data: boxPlotData, run } = useAsyncData<any>({
    successMsg: '箱线图数据加载成功',
    errorMsg: '加载箱线图数据失败',
  })

  async function loadBoxPlot() {
    const fileId = getFileId()
    if (!fileId || selectedParams.value.length === 0) {
      ElMessage.warning('请至少选择一个参数')
      return
    }
    await run(
      () => analysisApi.getBoxPlot(fileId, selectedParams.value, groupBy.value || undefined),
      (d: any) => d.results ?? d,
    )
  }

  return { loading, boxPlotData, loadBoxPlot }
}
