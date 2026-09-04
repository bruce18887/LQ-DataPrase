import { type Ref, ref, watch } from 'vue'
import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'
import { useAnalysisStore } from '../../../stores/analysis'

export function useQQPlot(
  getFileId: () => number | null,
  selectedParam: Ref<string>,
  enabled?: Ref<boolean>,
  dataOnlyBin1: Ref<boolean> = ref(false),
) {
  const analysisStore = useAnalysisStore()
  const { loading: qqLoading, data: qqResult, error: qqError, run } = useAsyncData<any>({
    silent: true,
  })

  async function loadQQPlot() {
    const fileId = getFileId()
    // 未真正发请求的分支也要清错误态，避免旧错误文案残留在占位区
    qqError.value = null
    if (!fileId || !selectedParam.value) {
      qqResult.value = null
      return
    }
    if (enabled && !enabled.value) {
      qqResult.value = null
      return
    }

    await run(() => api.post('/analysis/qqplot/', {
      file_id: fileId,
      param: selectedParam.value,
      data_only_bin1: dataOnlyBin1.value,
      // 敏感度在**发请求时**实时读 store，不是挂载时快照——2026-09-02
      // 批次 3 修的就是「快照导致改了敏感度仍按 1.5 发请求」。后端
      // qqplot 此前忽略该字段（写死 1.5），现已贯穿到 detect_outliers_iqr。
      iqr_multiplier: analysisStore.iqrMultiplier,
    }))
  }

  // Auto-load when the selected parameter changes
  watch(selectedParam, () => loadQQPlot())
  // 敏感度变化 → 重发（与 useHistogram 的 watch(iqrMultiplier) 同口径）：
  // 否则用户调完敏感度，直方图的异常值集合变了而 QQ 图滞留旧值。
  watch(() => analysisStore.iqrMultiplier, () => loadQQPlot())
  // Row-level filter change: reload with the narrowed frame (same pattern
  // as useHistogram). loadQQPlot is a no-op when not enabled.
  watch(dataOnlyBin1, () => loadQQPlot())

  // Auto-load when the enabled state changes
  if (enabled) {
    watch(enabled, (val) => {
      if (val) {
        loadQQPlot()
      } else {
        qqResult.value = null
      }
    })
  }

  return { qqLoading, qqResult, qqError, loadQQPlot }
}
