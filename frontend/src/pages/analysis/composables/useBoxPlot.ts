import { type Ref, ref, watch, computed } from 'vue'
import { analysisApi } from '../../../api/analysis'
import { useAsyncData } from '../../../composables/useAsyncData'
import { useAnalysisStore } from '../../../stores/analysis'

export function useBoxPlot(
  getFileId: () => number | null,
  selectedParam: Ref<string>,
  groupBy: Ref<string>,
  enabled?: Ref<boolean>,
  dataOnlyBin1: Ref<boolean> = ref(false),
) {
  const { loading, data: boxPlotData, error: boxPlotError, run } = useAsyncData<any>({
    silent: true,
  })
  const analysisStore = useAnalysisStore()

  async function loadBoxPlot() {
    const fileId = getFileId()
    // 未真正发请求的分支也要清错误态，避免旧错误文案残留在占位区
    boxPlotError.value = null
    if (!fileId || !selectedParam.value) return
    if (enabled && !enabled.value) return
    await run(
      // 敏感度在**发请求时**实时读 store（不是挂载时快照，参 2026-09-02 批次 3）
      () => analysisApi.getBoxPlot(fileId, [selectedParam.value], groupBy.value || undefined,
                                   dataOnlyBin1.value, analysisStore.iqrMultiplier),
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
  watch(dataOnlyBin1, () => { if (selectedParam.value) loadBoxPlot() })
  // 敏感度变化 → 重发（与 useHistogram 同口径），否则箱线图的 whisker/
  // 异常点会滞留旧值，与同屏直方图矛盾。
  watch(() => analysisStore.iqrMultiplier, () => { if (selectedParam.value) loadBoxPlot() })
  watch(getFileId, () => { if (getFileId() && selectedParam.value) loadBoxPlot() })
  if (enabled) {
    watch(enabled, (val) => { if (val && selectedParam.value) loadBoxPlot() })
  }

  return { loading, boxPlotData, boxPlotError, stats, loadBoxPlot }
}
