import { ref } from 'vue'
import type { AxiosRequestConfig } from 'axios'

import api from '../../../api'
import { downloadBlob, extractFilenameFromContentDisposition } from '../../../utils/download'
import { getExportTimeoutMs } from '../../../utils/exportTimeout'

export function useExport(
  getSelectedFileId: () => number | null
) {
  const exporting = ref(false)

  async function exportSigmaLimit(
    sigma: number,
    options?: { onlyValidLimits?: boolean; data_only_bin1?: boolean },
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
        data_only_bin1: options?.data_only_bin1 ?? false,
      }, { responseType: 'blob', timeout: await getExportTimeoutMs(), ...requestConfig })
      const fname = extractFilenameFromContentDisposition(resp.headers?.['content-disposition']) || `sigma_limit_${sigma}sigma.xlsx`
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
        // 超时秒数由系统设置「导出超时」控制；...requestConfig 保持在后，
        // 调用方可按需覆盖（如 silent 标记）
        timeout: await getExportTimeoutMs(),
        ...requestConfig,
      })
      const fname = extractFilenameFromContentDisposition(resp.headers?.['content-disposition']) || `batch_charts.${format === 'pptx' ? 'pptx' : 'xlsx'}`
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
