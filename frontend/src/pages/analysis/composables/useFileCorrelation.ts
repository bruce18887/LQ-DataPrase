import { ref } from 'vue'
import api from '../../../api'
import { datafilesApi } from '../../../api/datafiles'
import { useAsyncData } from '../../../composables/useAsyncData'
import { ElMessage } from 'element-plus'

/**
 * useFileCorrelation — 文件相关性：按序列号对齐两个文件，逐参数对比
 * ATE/Bench 差异（后端 `/analysis/file-correlation/`）。
 */
export function useFileCorrelation() {
  const { loading, data: result, run } = useAsyncData<any>({
    successMsg: '文件相关性分析完成',
  })

  /** 文件选择器选项（全部 DataFile 列表） */
  const files = ref<{ id: number; filename: string }[]>([])
  const filesLoading = ref(false)

  async function loadFiles() {
    filesLoading.value = true
    try {
      const { data } = await datafilesApi.list()
      const list: any[] = Array.isArray(data) ? data : (data?.results ?? [])
      files.value = list.map((f: any) => ({ id: f.id, filename: f.filename }))
    } catch {
      files.value = []
    } finally {
      filesLoading.value = false
    }
  }

  async function loadFileCorrelation(file1: number, file2: number, threshold: number) {
    if (!file1 || !file2) { ElMessage.warning('请选择两个文件'); return }
    await run(() => api.post('/analysis/file-correlation/', {
      file1_id: file1, file2_id: file2, threshold,
    }))
  }

  return { loading, result, files, filesLoading, loadFiles, loadFileCorrelation }
}
