import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'
import { ElMessage } from 'element-plus'

export function useFileCorrelation() {
  const { loading, data: result, run } = useAsyncData<any>({
    successMsg: '文件相关性分析完成',
    errorMsg: '文件相关性分析失败',
  })

  async function loadFileCorrelation(file1: number, file2: number, threshold: number) {
    if (!file1 || !file2) { ElMessage.warning('请选择两个文件'); return }
    await run(() => api.post('/analysis/file-correlation/', { file1_id: file1, file2_id: file2, threshold }))
  }

  return { loading, result, loadFileCorrelation }
}
