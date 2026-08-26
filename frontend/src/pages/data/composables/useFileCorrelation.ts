import { ref } from 'vue'
import api from '../../../api'
import { datafilesApi } from '../../../api/datafiles'
import { useAsyncData } from '../../../composables/useAsyncData'
import { downloadBlob, extractFilenameFromContentDisposition } from '../../../utils/download'
import { getExportTimeoutMs } from '../../../utils/exportTimeout'
import { ElMessage } from 'element-plus'
import type {
  DataFile,
  FileCorrelationOptions,
  FileCorrelationResult,
} from '../../../types'

/**
 * useFileCorrelation — 文件相关性：按序列号对齐两个文件，逐参数对比
 * ATE/Bench 差异（后端 `/analysis/file_correlation/`），并支持导出模板
 * 布局 xlsx（`/analysis/file_correlation_export/`）。
 */
export function useFileCorrelation() {
  const { loading, data: result, error, run } = useAsyncData<FileCorrelationResult>({
    successMsg: '文件相关性分析完成',
  })

  /** 文件选择器选项（完整 DataFile 对象，FileSelect 富信息行需要 file_size/created_at 等） */
  const files = ref<DataFile[]>([])
  const filesLoading = ref(false)
  /** Excel 导出请求进行中 */
  const exporting = ref(false)
  /** 两文件公共序列（升序；序列勾选器选项） */
  const commonSerials = ref<number[]>([])
  const commonSerialsLoading = ref(false)

  async function loadFiles() {
    filesLoading.value = true
    try {
      const { data } = await datafilesApi.list()
      files.value = Array.isArray(data) ? data : (data?.results ?? [])
    } catch {
      files.value = []
    } finally {
      filesLoading.value = false
    }
  }

  /**
   * 拉取两文件公共序列（序列勾选器数据源，与计算口径一致）。
   * 返回列表供调用方决定默认选中（前 10 颗）。
   */
  async function loadCommonSerials(file1: number, file2: number): Promise<number[]> {
    commonSerialsLoading.value = true
    try {
      const { data } = await api.post('/analysis/file_correlation_serials/', {
        file1_id: file1,
        file2_id: file2,
      })
      const list = Array.isArray(data?.serials) ? data.serials as number[] : []
      commonSerials.value = list
      return list
    } catch (err) {
      console.error('[useFileCorrelation] load common serials failed:', err)
      commonSerials.value = []
      return []
    } finally {
      commonSerialsLoading.value = false
    }
  }

  /** 与后端 FileCorrelationConfig 一一对应的请求体 */
  function buildPayload(file1: number, file2: number, opts: FileCorrelationOptions) {
    return {
      file1_id: file1,
      file2_id: file2,
      threshold: opts.threshold,
      diff_rule: opts.diffRule,
      serials: opts.serials,
      ignore_no_limit: opts.ignoreNoLimit,
      ignore_no_data: opts.ignoreNoData,
    }
  }

  async function loadFileCorrelation(file1: number, file2: number, opts: FileCorrelationOptions) {
    if (!file1 || !file2) { ElMessage.warning('请选择两个文件'); return }
    await run(() => api.post('/analysis/file_correlation/', buildPayload(file1, file2, opts)))
  }

  /** 导出模板布局 xlsx（后端生成，文件名为用户模板渲染） */
  async function exportFileCorrelation(file1: number, file2: number, opts: FileCorrelationOptions) {
    if (!file1 || !file2) { ElMessage.warning('请选择两个文件'); return }
    exporting.value = true
    try {
      const resp = await api.post('/analysis/file_correlation_export/', buildPayload(file1, file2, opts), {
        responseType: 'blob',
        // 两个文件解析 + xlsx 生成可能远超 30s 默认超时，跟随系统设置
        // 「导出超时」（默认 600s）
        timeout: await getExportTimeoutMs(),
      })
      const fname = extractFilenameFromContentDisposition(
        resp.headers?.['content-disposition'],
      ) || `file_correlation_${file1}_${file2}.xlsx`
      downloadBlob(resp.data as Blob, fname)
    } catch (err) {
      console.error('[useFileCorrelation] export failed:', err)
      throw err
    } finally {
      exporting.value = false
    }
  }

  return {
    loading, result, error, files, filesLoading,
    commonSerials, commonSerialsLoading, loadCommonSerials,
    loadFiles, loadFileCorrelation, exporting, exportFileCorrelation,
  }
}
