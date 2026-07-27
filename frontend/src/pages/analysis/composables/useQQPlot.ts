import { type Ref, watch } from 'vue'
import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'

export function useQQPlot(
  getFileId: () => number | null,
  selectedParam: Ref<string>,
  enabled?: Ref<boolean>,
) {
  const { loading: qqLoading, data: qqResult, run } = useAsyncData<any>({
    silent: true,
  })

  async function loadQQPlot() {
    const fileId = getFileId()
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
    }))
  }

  // Auto-load when the selected parameter changes
  watch(selectedParam, () => loadQQPlot())

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

  return { qqLoading, qqResult, loadQQPlot }
}
