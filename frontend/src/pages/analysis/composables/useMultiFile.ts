import { ref } from 'vue'
import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'

/**
 * useMultiFile — 多文件分析数据加载
 *
 * 两段式调用 `/analysis/multi_lot/`：
 *  - loadCommonParams(fileIds, ignoreNoLimit)：无 param，取所选文件的共有测试项
 *    （列名相同的交集；ignoreNoLimit 时只保留各文件都带 limit 的项）+ 文件名。
 *  - loadDistribution(fileIds, param)：带 param，取每文件分布（含 per-file limit）。
 */
export function useMultiFile() {
  const commonParams = ref<string[]>([])
  const fileNames = ref<{ file_id: number; filename: string }[]>([])

  const { loading: paramsLoading, run: runParams } = useAsyncData<any>({ silent: true })
  const { loading, data: lotData, run: runDist } = useAsyncData<any>({
    errorMsg: '加载多文件分布数据失败',
  })

  async function loadCommonParams(fileIds: number[], ignoreNoLimit: boolean) {
    if (fileIds.length < 2) {
      commonParams.value = []
      fileNames.value = []
      return
    }
    const result = await runParams(() => api.post('/analysis/multi_lot/', {
      file_ids: fileIds,
      ignore_no_limit: ignoreNoLimit,
    }))
    if (result) {
      commonParams.value = result.common_params || []
      fileNames.value = result.file_names || []
    }
  }

  async function loadDistribution(fileIds: number[], param: string,
                                    rangeType: string = 'S4') {
    if (fileIds.length < 2 || !param) {
      lotData.value = null
      return
    }
    await runDist(() => api.post('/analysis/multi_lot/', {
      file_ids: fileIds,
      param,
      range_type: rangeType,
    }))
  }

  return { loading, paramsLoading, commonParams, fileNames, lotData, loadCommonParams, loadDistribution }
}
