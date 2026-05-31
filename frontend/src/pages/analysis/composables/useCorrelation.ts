import { ref } from 'vue'
import api from '../../../api'

export function useCorrelation(
  getSelectedFileId: () => number | null
) {
  const corrLoading = ref(false)
  const corrResult = ref<any>(null)
  const corrPearsonR = ref<number | null>(null)
  const corrAxisMode = ref('data')

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
      corrPearsonR.value = data.pearson_r
    } catch {
      // silently fail
    } finally {
      corrLoading.value = false
    }
  }

  return {
    corrLoading,
    corrResult,
    corrPearsonR,
    corrAxisMode,
    loadCorrelation,
  }
}
