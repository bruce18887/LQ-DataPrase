import { ref, type Ref } from 'vue'
import api from '../../../api'

export function useSiteStats(
  getSelectedFileId: () => number | null,
  localSelectedParam: Ref<string>,
  rangeType: Ref<string>
) {
  const siteStats = ref<any[]>([])
  const siteStatsError = ref('')

  async function loadSiteStats() {
    const fileId = getSelectedFileId()
    if (!fileId || !localSelectedParam.value) return
    siteStatsError.value = ''
    try {
      const { data } = await api.post('/statistics/site_stats/', {
        file_id: fileId,
        param: localSelectedParam.value,
        range_type: rangeType.value,
      })
      if (data.error) {
        siteStatsError.value = data.error
        siteStats.value = []
      } else {
        siteStats.value = data.site_data || []
      }
    } catch (err: any) {
      siteStatsError.value = err.response?.data?.error || err.message || '请求失败'
      siteStats.value = []
    }
  }

  return {
    siteStats,
    siteStatsError,
    loadSiteStats,
  }
}
