import { ref } from 'vue'
import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'

/**
 * useMultiFile — 多文件分析数据加载
 *
 * 调用 `/analysis/multi_lot/`：
 *  - loadCommonParams(fileIds, ignoreNoLimit, rangeType)：无 param，取所选文件的
 *    共有测试项（列名相同的交集；ignoreNoLimit 时只保留各文件都带 limit 的项）
 *    + 文件名。合并请求优化：后端在同一响应中顺带返回**首个公共参数**的分布
 *    （lot_data/bin_centers/global 统计），免去前端串行第二次请求。
 *    必须携带当前 range_type：否则后端默认 S4，而下拉可能显示 RDL/S6——
 *    「先切范围类型再选文件 / URL 恢复上次 mf_range」场景下初始图表与下拉
 *    不一致，切换看起来不生效（2026-08-13 回归）。
 *  - loadDistribution(fileIds, param)：带 param，取每文件分布（含 per-file limit）。
 *
 * ``lotParam`` 记录 lotData 对应的参数——前端据此跳过「合并请求已含该参数
 * 分布」时的重复请求。
 */
export function useMultiFile() {
  const commonParams = ref<string[]>([])
  const fileNames = ref<{ file_id: number; filename: string }[]>([])
  const lotParam = ref('')

  const { loading: paramsLoading, run: runParams } = useAsyncData<any>({ silent: true })
  const { loading, data: lotData, run: runDist } = useAsyncData<any>()

  async function loadCommonParams(fileIds: number[], ignoreNoLimit: boolean,
                                  rangeType: string = 'RDL') {
    if (fileIds.length < 2) {
      commonParams.value = []
      fileNames.value = []
      lotData.value = null
      lotParam.value = ''
      return
    }
    const result = await runParams(() => api.post('/analysis/multi_lot/', {
      file_ids: fileIds,
      ignore_no_limit: ignoreNoLimit,
      range_type: rangeType,
    }))
    if (result) {
      commonParams.value = result.common_params || []
      fileNames.value = result.file_names || []
      if (result.lot_data && result.bin_centers) {
        // 合并响应：分布数据随 common params 一起到达
        lotData.value = result
        lotParam.value = result.param || ''
      } else {
        lotData.value = null
        lotParam.value = ''
      }
    }
    return result?.param || ''
  }

  async function loadDistribution(fileIds: number[], param: string,
                                    rangeType: string = 'S4') {
    if (fileIds.length < 2 || !param) {
      lotData.value = null
      lotParam.value = ''
      return
    }
    await runDist(() => api.post('/analysis/multi_lot/', {
      file_ids: fileIds,
      param,
      range_type: rangeType,
    }))
    if (lotData.value?.param) lotParam.value = lotData.value.param
  }

  return { loading, paramsLoading, commonParams, fileNames, lotData, lotParam, loadCommonParams, loadDistribution }
}
