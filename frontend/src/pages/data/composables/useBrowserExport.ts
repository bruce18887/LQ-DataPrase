/**
 * 查看数据页的两个导出：Excel 走作业，CSV 仍走同步。
 *
 * 为什么拆开：Excel 是「万行 × 千列、可达数十秒」的那一发，占着请求线程就会让其他人排队
 * （方案 §1 的尾部停摆）；CSV 体量与耗时都低一个量级，暂时留在同步端点，
 * 少一处改动就少一处风险。**两条路径产出的文件名口径完全一致**
 * （都优先解析后端渲染的 Content-Disposition），用户在两个按钮间不会看到不同的命名规则。
 *
 * 抽成 composable 的另一半理由：`DataBrowserAgGrid.vue` 早就超过仓库的 600 行上限，
 * 往里加进度 UI 只会更糟，所以这里是「搬出去 + 换实现」，不是「加一段」。
 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import api from '../../../api'
import {
  downloadBlob,
  extractFilenameFromContentDisposition,
  sanitizeFilename,
} from '../../../utils/download'
import { getExportTimeoutMs } from '../../../utils/exportTimeout'
import { useJobExport } from '../../../composables/useJobExport'

export interface BrowserExportContext {
  /** 当前文件 id（null = 还没选文件，两个按钮此时是 disabled 的）。 */
  fileId: () => number | null
  passfail: () => string
  siteFilter: () => string
  /** 与 IRM getRows 同语义的排序/列过滤模型：看到的行 == 导出的行。 */
  gridModels: () => { sort_model: string; filter_model: string }
  /** 按 id 找回文件名，用于后端没给 Content-Disposition 时的兜底命名。 */
  filenameOf: (id: number) => string | undefined
}

export function useBrowserExport(ctx: BrowserExportContext) {
  const exportingCsv = ref(false)
  const job = useJobExport()
  const exportingExcel = job.exporting
  const excelProgress = job.progress

  /** 兜底名沿用旧口径：源文件名去掉 .csv 再拼后缀（与后端模板不一致时以响应头为准）。 */
  function resolveName(headers: Record<string, string> | undefined,
                      fallback: string, suffix: string): string {
    const parsed = headers
      ? extractFilenameFromContentDisposition(headers['content-disposition'])
      : null
    if (parsed) return parsed
    const id = ctx.fileId()
    const fileName = id ? ctx.filenameOf(id) : undefined
    if (fileName) return sanitizeFilename(`${fileName.replace(/\.csv$/i, '')}${suffix}`)
    return fallback
  }

  async function exportExcel(): Promise<void> {
    const id = ctx.fileId()
    if (!id) return
    const ok = await job.run('export_excel', {
      file_id: id,
      passfail: ctx.passfail(),
      site_filter: ctx.siteFilter(),
      ...ctx.gridModels(),
    })
    if (ok) ElMessage.success('下载完成')
  }

  async function exportCsv(): Promise<void> {
    const id = ctx.fileId()
    if (!id) return
    exportingCsv.value = true
    try {
      const resp = await api.post(
        '/export/to_csv/',
        {
          file_id: id,
          passfail: ctx.passfail(),
          site_filter: ctx.siteFilter(),
          ...ctx.gridModels(),
        },
        // 大文件导出可达数十秒，必须放宽超时（全局 30s 会 abort → Broken pipe）；
        // 秒数由系统设置「导出超时」控制（默认 600s）
        { responseType: 'blob', timeout: await getExportTimeoutMs() },
      )
      downloadBlob(
        resp.data as Blob,
        resolveName(resp.headers as Record<string, string>, 'export.csv', '_data.csv'),
      )
      ElMessage.success('下载完成')
    } catch {
      // 错误 toast 由 axios 拦截器统一弹出
    } finally {
      exportingCsv.value = false
    }
  }

  return { exportingExcel, exportingCsv, excelProgress, exportExcel, exportCsv }
}
