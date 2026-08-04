import { ref, type Ref } from 'vue'
import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'

export function useSiteStats(
  getSelectedFileId: () => number | null,
  localSelectedParam: Ref<string>,
  rangeType: Ref<string>
) {
  const siteStats = ref<any[]>([])
  const siteStatsError = ref('')
  const { run } = useAsyncData<any>({ silent: true })

  async function loadSiteStats() {
    const fileId = getSelectedFileId()
    if (!fileId || !localSelectedParam.value) return
    siteStatsError.value = ''
    const result = await run(() => api.post('/statistics/site_stats/', {
      file_id: fileId,
      param: localSelectedParam.value,
      range_type: rangeType.value,
    }, { silent: true }))
    if (result?.error) {
      siteStatsError.value = result.error
      siteStats.value = []
    } else {
      siteStats.value = result?.site_data || []
    }
  }

  return { siteStats, siteStatsError, loadSiteStats }
}
