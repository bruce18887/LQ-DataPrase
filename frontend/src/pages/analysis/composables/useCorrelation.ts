import { ref } from 'vue'
import api from '../../../api'

export function useCorrelation(
  getSelectedFileId: () => number | null
) {
  const corrLoading = ref(false)
  const corrResult = ref<any>(null)

  async function loadCorrelation(x: string, y: string) {
    const fileId = getSelectedFileId()
    if (!fileId) return
    corrLoading.value = true
    try {
      const { data } = await api.post('/analysis/correlation/', {
        file_id: fileId,
        param_x: x,
        param_y: y,
      })
      corrResult.value = data
    } catch {
      // silently fail
    } finally {
      corrLoading.value = false
    }
  }

  return {
    corrLoading,
    corrResult,
    loadCorrelation,
  }
}
