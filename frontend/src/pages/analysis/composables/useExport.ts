import { ref } from 'vue'
import api from '../../../api'

export function useExport(
  getSelectedFileId: () => number | null
) {
  const exporting = ref(false)
  const correlationMatrix = ref<any>(null)
  const matrixLoading = ref(false)

  async function loadCorrelationMatrix() {
    const fileId = getSelectedFileId()
    if (!fileId) return
    matrixLoading.value = true
    try {
      const { data } = await api.post('/analysis/correlation_matrix/', {
        file_id: fileId,
      })
      correlationMatrix.value = data
    } catch {
      // silently fail
    } finally {
      matrixLoading.value = false
    }
  }

  async function exportSigmaLimit(sigma: number) {
    const fileId = getSelectedFileId()
    if (!fileId) return
    exporting.value = true
    try {
      const { data } = await api.post('/export/sigma_limit/', {
        file_id: fileId,
        sigma,
        only_valid_limits: true,
      }, { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([data]))
      const link = document.createElement('a')
      link.href = url
      link.download = `sigma_limit_${sigma}sigma.xlsx`
      link.click()
      window.URL.revokeObjectURL(url)
    } catch {
      // silently fail
    } finally {
      exporting.value = false
    }
  }

  async function exportBatchCharts(params: string[], format: string) {
    const fileId = getSelectedFileId()
    if (!fileId) return
    exporting.value = true
    try {
      const { data } = await api.post('/export/batch_charts/', {
        file_id: fileId,
        params,
        format,
      }, { responseType: 'blob' })
      const ext = format === 'pptx' ? 'pptx' : 'xlsx'
      const url = window.URL.createObjectURL(new Blob([data]))
      const link = document.createElement('a')
      link.href = url
      link.download = `batch_charts.${ext}`
      link.click()
      window.URL.revokeObjectURL(url)
    } catch {
      // silently fail
    } finally {
      exporting.value = false
    }
  }

  return {
    exporting,
    correlationMatrix,
    matrixLoading,
    loadCorrelationMatrix,
    exportSigmaLimit,
    exportBatchCharts,
  }
}
