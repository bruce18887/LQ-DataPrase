import { ref, watch, type Ref } from 'vue'
import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'

export function useSiteStats(
  getSelectedFileId: () => number | null,
  localSelectedParam: Ref<string>,
  rangeType: Ref<string>,
  /** 仅用 Pass 数据(Bin1)：站点统计与直方图口径保持一致 */
  dataOnlyBin1?: Ref<boolean>,
) {
  const siteStats = ref<any[]>([])
  const siteStatsError = ref('')
  const { run, error } = useAsyncData<any>({ silent: true })

  async function loadSiteStats() {
    const fileId = getSelectedFileId()
    if (!fileId || !localSelectedParam.value) return
    siteStatsError.value = ''
    const result = await run(() => api.post('/statistics/site_stats/', {
      file_id: fileId,
      param: localSelectedParam.value,
      range_type: rangeType.value,
      data_only_bin1: dataOnlyBin1?.value ?? false,
    }, { silent: true }))
    // HTTP 4xx/5xx → useAsyncData 的 error ref 置位（此前只处理 200+body.error，
    // 非 200 时表格静默空白无提示）
    if (error.value) {
      siteStatsError.value = error.value
      siteStats.value = []
    } else if (result?.error) {
      siteStatsError.value = result.error
      siteStats.value = []
    } else {
      siteStats.value = result?.site_data || []
    }
  }

  if (dataOnlyBin1) watch(dataOnlyBin1, () => loadSiteStats())

  return { siteStats, siteStatsError, loadSiteStats }
}
