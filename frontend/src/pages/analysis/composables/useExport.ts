import { ref } from 'vue'
import type { AxiosRequestConfig } from 'axios'

import api from '../../../api'

function extractFilename(contentDisposition: string | null | undefined): string | null {
  if (!contentDisposition) return null
  const match = contentDisposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/)
  return match ? decodeURIComponent(match[1]) : null
}

export function useExport(
  getSelectedFileId: () => number | null
) {
  const exporting = ref(false)

  function downloadBlob(data: Blob, filename: string) {
    const url = window.URL.createObjectURL(data)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    window.URL.revokeObjectURL(url)
  }

  async function exportSigmaLimit(
    sigma: number,
    options?: { onlyValidLimits?: boolean },
    requestConfig?: AxiosRequestConfig,
  ) {
    const fileId = getSelectedFileId()
    if (!fileId) return
    exporting.value = true
    try {
      const resp = await api.post('/export/sigma_limit/', {
        file_id: fileId,
        sigma,
        only_valid_limits: options?.onlyValidLimits ?? true,
      }, { responseType: 'blob', ...requestConfig })
      const fname = extractFilename(resp.headers?.['content-disposition']) || `sigma_limit_${sigma}sigma.xlsx`
      downloadBlob(resp.data as Blob, fname)
    } catch (err) {
      console.error('[useExport] sigma_limit failed:', err)
      throw err
    } finally {
      exporting.value = false
    }
  }

  async function exportBatchCharts(
    params: string[],
    format: string,
    options?: Record<string, any>,
    requestConfig?: AxiosRequestConfig,
  ) {
    const fileId = getSelectedFileId()
    if (!fileId) return
    exporting.value = true
    try {
      const resp = await api.post('/export/batch_charts/', {
        file_id: fileId,
        params,
        format,
        ...(options || {}),
      }, {
        responseType: 'blob',
        timeout: 300000, // 5 min for large batch exports
        ...requestConfig,
      })
      const fname = extractFilename(resp.headers?.['content-disposition']) || `batch_charts.${format === 'pptx' ? 'pptx' : 'xlsx'}`
      downloadBlob(resp.data as Blob, fname)
    } catch (err) {
      console.error('[useExport] batch_charts failed:', err)
      throw err
    } finally {
      exporting.value = false
    }
  }

  return {
    exporting,
    exportSigmaLimit,
    exportBatchCharts,
  }
}
