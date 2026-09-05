import { type Ref, ref, watch, computed } from 'vue'
import { analysisApi } from '../../../api/analysis'
import { useAsyncData } from '../../../composables/useAsyncData'

export function useBoxPlot(
  getFileId: () => number | null,
  selectedParam: Ref<string>,
  groupBy: Ref<string>,
  enabled?: Ref<boolean>,
  dataOnlyBin1: Ref<boolean> = ref(false),
  // 敏感度属于调用方那个 tab 自己的状态（不再从全局 store 直读）：
  // 单文件 tab 改敏感度不应造成其他 tab 的图表静默重算。
  iqrMultiplier: Ref<number> = ref(1.5),
) {
  const { loading, data: boxPlotData, error: boxPlotError, run } = useAsyncData<any>({
    silent: true,
  })

  async function loadBoxPlot() {
    const fileId = getFileId()
    // 未真正发请求的分支也要清错误态，避免旧错误文案残留在占位区
    boxPlotError.value = null
    if (!fileId || !selectedParam.value) return
    if (enabled && !enabled.value) return
    await run(
      // 敏感度在**发请求时**实时读 ref（不是挂载时快照，参 2026-09-02 批次 3）
      () => analysisApi.getBoxPlot(fileId, [selectedParam.value], groupBy.value || undefined,
                                   dataOnlyBin1.value, iqrMultiplier.value),
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
  watch(iqrMultiplier, () => { if (selectedParam.value) loadBoxPlot() })
  watch(getFileId, () => { if (getFileId() && selectedParam.value) loadBoxPlot() })
  if (enabled) {
    watch(enabled, (val) => { if (val && selectedParam.value) loadBoxPlot() })
  }

  return { loading, boxPlotData, boxPlotError, stats, loadBoxPlot }
}
