import { type Ref, ref, watch } from 'vue'
import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'

export function useQQPlot(
  getFileId: () => number | null,
  selectedParam: Ref<string>,
  enabled?: Ref<boolean>,
  dataOnlyBin1: Ref<boolean> = ref(false),
) {
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
    }))
  }

  // Auto-load when the selected parameter changes
  watch(selectedParam, () => loadQQPlot())
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
