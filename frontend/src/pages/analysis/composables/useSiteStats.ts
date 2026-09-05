import { ref, watch, type Ref } from 'vue'
import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'

export function useSiteStats(
  getSelectedFileId: () => number | null,
  localSelectedParam: Ref<string>,
  rangeType: Ref<string>,
  /** 仅用 Pass 数据(Bin1)：站点统计与直方图口径保持一致 */
  dataOnlyBin1?: Ref<boolean>,
  /** CL 模式的用户自定义限：与 histogram 同口径（后端 resolve 'CL'） */
  customLow?: Ref<number | null>,
  customHigh?: Ref<number | null>,
) {
  const siteStats = ref<any[]>([])
  const siteStatsError = ref('')
  const { run, error } = useAsyncData<any>({ silent: true })

  async function loadSiteStats() {
    const fileId = getSelectedFileId()
    // 未真正发请求的分支也要清错误态，否则切文件/清空参数后旧横幅会一直挂着
    siteStatsError.value = ''
    if (!fileId || !localSelectedParam.value) {
      // 切文件清参数的早退：旧文件的表滞留会误导（与 useQQPlot 早退清态同口径）
      siteStats.value = []
      return
    }
    // 快照守卫：快速连切参数/文件时，慢到的旧请求——含 run() 判过期返回
    // null 的分支——不得写入或清空当前数据，否则刚加载好的新表会被旧响应
    // 走 else 分支清成空（2026-09-05 审查 H1/M1）
    const reqFileId = fileId
    const reqParam = localSelectedParam.value
    const result = await run(() => api.post('/statistics/site_stats/', {
      file_id: fileId,
      param: localSelectedParam.value,
      range_type: rangeType.value,
      // CL 语义三端点统一为「用户自定义限」：不带的话后端按数据极值判定，
      // Site 表 Fail 恒 0、Yield 恒 100%，与同屏直方图矛盾
      custom_low: rangeType.value === 'CL' ? customLow?.value ?? null : null,
      custom_high: rangeType.value === 'CL' ? customHigh?.value ?? null : null,
      data_only_bin1: dataOnlyBin1?.value ?? false,
    }, { silent: true }))
    if (reqFileId !== getSelectedFileId() || reqParam !== localSelectedParam.value) return
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
