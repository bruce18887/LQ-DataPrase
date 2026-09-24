import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import api from '../../../api'
import { batchApi } from '../../../api/batch'
import { downloadBlob, extractFilenameFromContentDisposition } from '../../../utils/download'
import { getExportTimeoutMs } from '../../../utils/exportTimeout'

/**
 * 批次良率 Tab 的导出动作。抽出为 composable 是为了给 BatchYieldTab.vue 减负
 * （组件已超过 300 行最佳实践）。
 */
export function useBatchExport(getBatchData: () => any) {
  const exporting = ref(false)

  /** 导出批次良率 HTML 报告（自包含，含内联图表）。 */
  async function exportHtmlReport(batchName: string) {
    if (!batchName) return
    exporting.value = true
    try {
      const resp = await api.post(
        '/batch-report/batch_html_report/',
        { batch_name: batchName },
        { responseType: 'blob', timeout: await getExportTimeoutMs() },
      )
      // 文件名优先解析后端模板渲染的 Content-Disposition，缺失时兜底
      const fname = extractFilenameFromContentDisposition(resp.headers?.['content-disposition'])
        ?? `Batch_Report_${batchName}.html`
      downloadBlob(resp.data as Blob, fname)
    } catch (err) {
      console.error('[useBatchExport] html report failed:', err)
      throw err
    } finally {
      exporting.value = false
    }
  }

  /** Excel 导出（沿用既有占位实现，未变更行为）。 */
  async function exportExcel() {
    if (!getBatchData()) return
    exporting.value = true
    try {
      await batchApi.generateReport(
        (getBatchData().phases || []).map((_: any, i: number) => i)
      )
      ElMessage.info('导出功能开发中')
    } finally {
      exporting.value = false
    }
  }

  return { exporting, exportExcel, exportHtmlReport }
}
