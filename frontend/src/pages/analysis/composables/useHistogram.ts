import { ref, watch, computed, type Ref } from 'vue'
import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'
import { useThemeStore } from '../../../stores/theme'

export function useHistogram(
  getSelectedFileId: () => number | null,
  localSelectedParam: Ref<string>,
  ignoreNoLimit: Ref<boolean>,
  rangeType: Ref<string>,
  customLow: Ref<number | null>,
  customHigh: Ref<number | null>,
  iqrMultiplier: Ref<number> = ref(1.5)
) {
  const histResult = ref<any>(null)
  const statCards = ref<{ label: string; value: string; color?: string }[]>([])
  const rangeTableData = ref<any[]>([])
  const { loading: histLoading, run } = useAsyncData<any>({ silent: true })

  const themeStore = useThemeStore()
  const isDark = computed(() => themeStore.currentTheme === 'night')
  const clrs = computed<Record<string, string>>(() => {
    if (isDark.value) {
      return { green: '#14b8a6', orange: '#fcd34d', darkorange: '#fb923c', red: '#fb7185', gray: '#9CA3AF' }
    }
    return { green: '#4CAF50', orange: '#FF9800', darkorange: '#FF5722', red: '#F44336', gray: '#9E9E9E' }
  })

  async function loadHistogram() {
    const fileId = getSelectedFileId()
    if (!fileId || !localSelectedParam.value) return
    const result = await run(() => api.post('/analysis/histogram/', {
      file_id: fileId,
      params: [localSelectedParam.value],
      ignore_no_limit: ignoreNoLimit.value,
      range_type: rangeType.value,
      custom_low: rangeType.value === 'CL' ? customLow.value : null,
      custom_high: rangeType.value === 'CL' ? customHigh.value : null,
      iqr_multiplier: iqrMultiplier.value,
    }))
    if (result?.results) histogramUpdateView(result.results as Record<string, any>)
  }

  let lastResults: Record<string, any> | null = null

  function histogramUpdateView(results: Record<string, any>) {
    lastResults = results
    const r = results[localSelectedParam.value]
    if (!r) return
    histResult.value = r
    // Use filtered statistics when outliers are present
    const hasOutliers = r.outlier_info?.has_outliers === true
    const displayMean = hasOutliers && r.filtered_mean != null ? r.filtered_mean : r.mean
    const displayStd = hasOutliers && r.filtered_std != null ? r.filtered_std : r.std
    const displayMin = hasOutliers && r.filtered_data_min != null ? r.filtered_data_min : r.data_min
    const displayMax = hasOutliers && r.filtered_data_max != null ? r.filtered_data_max : r.data_max

    const rangeVal = displayMax != null && displayMin != null ? displayMax - displayMin : null
    // Always use displayMean/displayStd for sigma calculations (filtered when outliers present)
    const s3min = displayMean != null && displayStd != null ? displayMean - 3 * displayStd : null
    const s3max = displayMean != null && displayStd != null ? displayMean + 3 * displayStd : null
    const s6min = displayMean != null && displayStd != null ? displayMean - 6 * displayStd : null
    const s6max = displayMean != null && displayStd != null ? displayMean + 6 * displayStd : null
    statCards.value = [
      { label: 'N', value: r.total_count?.toLocaleString() ?? '-' },
      { label: 'Mean', value: displayMean?.toFixed(4) ?? '-' },
      { label: 'Median', value: r.median?.toFixed(4) ?? '-' },
      { label: 'STD', value: displayStd?.toFixed(4) ?? '-' },
      { label: 'Min', value: displayMin?.toFixed(4) ?? '-' },
      { label: 'Max', value: displayMax?.toFixed(4) ?? '-' },
      { label: 'Range', value: rangeVal != null ? rangeVal.toFixed(4) : '-' },
      { label: 'CPK', value: r.filtered_cpk != null ? `${r.filtered_cpk.toFixed(4)} (filtered)` : (r.cpk != null ? `${r.cpk.toFixed(4)} (${r.cpk_level})` : '-'), color: clrs.value[r.cpk_color] ?? undefined },
      { label: '3σ', value: s3min != null && s3max != null ? `[${s3min.toFixed(4)}, ${s3max.toFixed(4)}]` : '-' },
      { label: '6σ', value: s6min != null && s6max != null ? `[${s6min.toFixed(4)}, ${s6max.toFixed(4)}]` : '-' },
    ]
    const s4min = (displayMean || 0) - 4 * (displayStd || 0); const s4max = (displayMean || 0) + 4 * (displayStd || 0)
    const unit = r.unit || ''
    const cutSuffix = hasOutliers ? ' (cut)' : ''
    const rdlGap = r.upper_limit != null && r.lower_limit != null ? ((r.upper_limit - r.lower_limit) / 25).toFixed(5) : '-'
    const drGap = displayMax != null && displayMin != null ? ((displayMax - displayMin) / 25).toFixed(5) : '-'
    const s3Gap = s3min != null && s3max != null ? ((s3max - s3min) / 25).toFixed(5) : '-'
    const s4Gap = s4max != null && s4min != null ? ((s4max - s4min) / 25).toFixed(5) : '-'
    const s6Gap = s6min != null && s6max != null ? ((s6max - s6min) / 25).toFixed(5) : '-'
    rangeTableData.value = [
      { label: 'RowDataLimit', low: r.lower_limit?.toFixed(5) ?? '-', high: r.upper_limit?.toFixed(5) ?? '-', gap: rdlGap, unit },
      { label: `Data Range${cutSuffix}`, low: displayMin?.toFixed(5) ?? '-', high: displayMax?.toFixed(5) ?? '-', gap: drGap, unit },
      { label: 'CustomLimit', low: displayMin?.toFixed(5) ?? '-', high: displayMax?.toFixed(5) ?? '-', gap: drGap, unit },
      { label: `3 Sigma${cutSuffix}`, low: s3min?.toFixed(5) ?? '-', high: s3max?.toFixed(5) ?? '-', gap: s3Gap, unit },
      { label: `4 Sigma${cutSuffix}`, low: s4min?.toFixed(5) ?? '-', high: s4max?.toFixed(5) ?? '-', gap: s4Gap, unit },
      { label: `6 Sigma${cutSuffix}`, low: s6min?.toFixed(5) ?? '-', high: s6max?.toFixed(5) ?? '-', gap: s6Gap, unit },
    ]
  }

  watch(isDark, () => {
    if (lastResults) histogramUpdateView(lastResults)
  })

  watch(localSelectedParam, () => loadHistogram())
  watch(ignoreNoLimit, () => loadHistogram())
  watch(rangeType, () => loadHistogram())
  watch([customLow, customHigh], () => { if (rangeType.value === 'CL') loadHistogram() })
  watch(iqrMultiplier, () => loadHistogram())
  watch(getSelectedFileId, () => { if (getSelectedFileId() && localSelectedParam.value) loadHistogram() })

  return { histResult, statCards, rangeTableData, loadHistogram, histLoading }
}
