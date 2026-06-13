import { type Ref, watch, computed } from 'vue'
import { analysisApi } from '../../../api/analysis'
import { useAsyncData } from '../../../composables/useAsyncData'

export function useBoxPlot(
  getFileId: () => number | null,
  selectedParam: Ref<string>,
  groupBy: Ref<string>,
  enabled?: Ref<boolean>,
) {
  const { loading, data: boxPlotData, run } = useAsyncData<any>({
    errorMsg: '加载箱线图数据失败',
  })

  async function loadBoxPlot() {
    const fileId = getFileId()
    if (!fileId || !selectedParam.value) return
    if (enabled && !enabled.value) return
    await run(
      () => analysisApi.getBoxPlot(fileId, [selectedParam.value], groupBy.value || undefined),
      (d: any) => d.results ?? d,
    )
  }

  /** 当前参数的统计信息 */
  const stats = computed(() => {
    if (!boxPlotData.value || !selectedParam.value) return null
    const paramData = boxPlotData.value[selectedParam.value]
    return paramData?.overall ?? null
  })

  // Auto-load on dependency change (same pattern as useHistogram)
  watch(selectedParam, () => loadBoxPlot())
  watch(groupBy, () => { if (selectedParam.value) loadBoxPlot() })
  watch(getFileId, () => { if (getFileId() && selectedParam.value) loadBoxPlot() })
  if (enabled) {
    watch(enabled, (val) => { if (val && selectedParam.value) loadBoxPlot() })
  }

  return { loading, boxPlotData, stats, loadBoxPlot }
}
