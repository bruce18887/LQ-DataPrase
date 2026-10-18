import { computed, ref } from 'vue'
import type { AxiosRequestConfig } from 'axios'

import api from '../../../api'
import { downloadBlob, extractFilenameFromContentDisposition } from '../../../utils/download'
import { getExportTimeoutMs } from '../../../utils/exportTimeout'
import { useJobExport, type JobRunResult } from '../../../composables/useJobExport'

export function useExport(
  getSelectedFileId: () => number | null
) {
  /** 同步导出（sigma_limit）自己的在飞标记；`exporting` 是给界面的合并值。 */
  const exportingSync = ref(false)
  const job = useJobExport()
  // 界面上「导出中」要同时盖住两条路径：sigma_limit 仍是同步 blob，
  // batch_charts 已改成提交-轮询（它的在飞时间是轮询时长，不再是单个请求时长）。
  const exporting = computed(() => exportingSync.value || job.exporting.value)
  const batchProgress = job.progress

  async function exportSigmaLimit(
    sigma: number,
    options?: { onlyValidLimits?: boolean; data_only_bin1?: boolean },
    requestConfig?: AxiosRequestConfig,
  ) {
    const fileId = getSelectedFileId()
    if (!fileId) return
    exportingSync.value = true
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
      exportingSync.value = false
    }
  }

  async function exportBatchCharts(
    params: string[],
    format: string,
    options?: Record<string, any>,
    callOptions?: { silent?: boolean },
  ): Promise<JobRunResult> {
    const fileId = getSelectedFileId()
    if (!fileId) return { ok: false, reason: 'submit-error', message: '未选择文件' }
    // 走作业：请求线程只付「提交」这一发，渲染在常驻进程池的子进程里跑，
    // 界面靠 batchProgress 显示进度。旧的 `timeout: getExportTimeoutMs()` 在这里
    // 已经没有意义（不再有长 blob 请求），所以「导出超时」这条文案改由
    // reason==='gave-up' 承担 —— 调用方必须跟着改，否则那个分支是死代码。
    return job.run('export_batch_charts', {
      file_id: fileId,
      params,
      format,
      ...(options || {}),
    }, { silent: callOptions?.silent })
  }

  return {
    exporting,
    /** 只有 batch_charts 这条作业路径为真；界面用它决定进度条显示与否
     *  （不能用 `exporting` —— sigma_limit 仍是同步在飞，那时显示的是上一次作业的残留值）。 */
    batchActive: job.exporting,
    batchProgress,
    exportSigmaLimit,
    exportBatchCharts,
  }
}
