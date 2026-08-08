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
  iqrMultiplier: Ref<number> = ref(1.5),
  outlierHandling: Ref<'clip' | 'exclude' | 'off'> = ref('off'),
  ignoreNoTestValue: Ref<boolean> = ref(false),
  dataOnlyBin1: Ref<boolean> = ref(false),
  onlyFailTestItem: Ref<boolean> = ref(false),
  onlyLowCpk: Ref<boolean> = ref(false),
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

  // 请求保序由 useAsyncData 内建守卫保证（过期 run() 返回 null 且不落地）
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
      ignore_no_test_value: ignoreNoTestValue.value,
      data_only_bin1: dataOnlyBin1.value,
      only_fail_test_item: onlyFailTestItem.value,
      only_low_cpk: onlyLowCpk.value,
    }, { silent: true }))
    if (result?.results) histogramUpdateView(result.results as Record<string, any>)
  }

  let lastResults: Record<string, any> | null = null

  function histogramUpdateView(results: Record<string, any>) {
    lastResults = results
    const r = results[localSelectedParam.value]
    if (!r) return
    histResult.value = r
    // Only apply filtered statistics when outlier handling is actually enabled.
    const hasOutliers = r.outlier_info?.has_outliers === true
    const useFiltered = hasOutliers && outlierHandling.value !== 'off'
    const displayMean = useFiltered && r.filtered_mean != null ? r.filtered_mean : r.mean
    const displayStd = useFiltered && r.filtered_std != null ? r.filtered_std : r.std
    const displayMin = useFiltered && r.filtered_data_min != null ? r.filtered_data_min : r.data_min
    const displayMax = useFiltered && r.filtered_data_max != null ? r.filtered_data_max : r.data_max

    const rangeVal = displayMax != null && displayMin != null ? displayMax - displayMin : null
    // σ 区间统一来自后端：开异常值处理（useFiltered）时用 filtered_sigma*（与
    // filtered_mean/std 同源），否则用全量 sigma* —— 与图表标记线同一组值，
    // 不再在前端重算（此前卡片用裁剪值、图表线用全量值，同界面互相矛盾）
    const s3min = useFiltered && r.filtered_sigma3_min != null ? r.filtered_sigma3_min : r.sigma3_min
    const s3max = useFiltered && r.filtered_sigma3_max != null ? r.filtered_sigma3_max : r.sigma3_max
    const s6min = useFiltered && r.filtered_sigma6_min != null ? r.filtered_sigma6_min : r.sigma6_min
    const s6max = useFiltered && r.filtered_sigma6_max != null ? r.filtered_sigma6_max : r.sigma6_max
    // CL 模式下后端用 custom 限值重算了 CPK：与 RDL CPK 不同时并排显示
    // 修改前（CPK(RDL)）与修改后（CPK(Custom)）两张卡，否则维持单卡。
    const showCustomCpk =
      rangeType.value === 'CL' &&
      r.custom_cpk != null &&
      r.cpk != null &&
      r.custom_cpk !== r.cpk
    const cpkCards: { label: string; value: string; color?: string }[] = []
    if (showCustomCpk) {
      cpkCards.push(
        { label: 'CPK(RDL)', value: `${r.cpk.toFixed(4)} (${r.cpk_level})`, color: clrs.value[r.cpk_color] ?? undefined },
        { label: 'CPK(Custom)', value: `${r.custom_cpk.toFixed(4)} (${r.custom_cpk_level})`, color: clrs.value[r.custom_cpk_color] ?? undefined },
      )
    } else {
      cpkCards.push({ label: 'CPK', value: r.filtered_cpk != null ? `${r.filtered_cpk.toFixed(4)} (filtered)` : (r.cpk != null ? `${r.cpk.toFixed(4)} (${r.cpk_level})` : '-'), color: clrs.value[r.cpk_color] ?? undefined })
    }
    statCards.value = [
      { label: 'N', value: r.total_count?.toLocaleString() ?? '-' },
      { label: 'Mean', value: displayMean?.toFixed(4) ?? '-' },
      { label: 'Median', value: r.median?.toFixed(4) ?? '-' },
      { label: 'STD', value: displayStd?.toFixed(4) ?? '-' },
      { label: 'Min', value: displayMin?.toFixed(4) ?? '-' },
      { label: 'Max', value: displayMax?.toFixed(4) ?? '-' },
      { label: 'Range', value: rangeVal != null ? rangeVal.toFixed(4) : '-' },
      ...cpkCards,
      { label: '3σ', value: s3min != null && s3max != null ? `[${s3min.toFixed(4)}, ${s3max.toFixed(4)}]` : '-' },
      { label: '6σ', value: s6min != null && s6max != null ? `[${s6min.toFixed(4)}, ${s6max.toFixed(4)}]` : '-' },
    ]
    const s4min = useFiltered && r.filtered_sigma4_min != null ? r.filtered_sigma4_min : r.sigma4_min
    const s4max = useFiltered && r.filtered_sigma4_max != null ? r.filtered_sigma4_max : r.sigma4_max
    const unit = r.unit || ''
    const cutSuffix = useFiltered ? ' (cut)' : ''
    const rdlGap = r.upper_limit != null && r.lower_limit != null ? ((r.upper_limit - r.lower_limit) / 25).toFixed(5) : '-'
    const drGap = displayMax != null && displayMin != null ? ((displayMax - displayMin) / 25).toFixed(5) : '-'
    const s3Gap = s3min != null && s3max != null ? ((s3max - s3min) / 25).toFixed(5) : '-'
    const s4Gap = s4max != null && s4min != null ? ((s4max - s4min) / 25).toFixed(5) : '-'
    const s6Gap = s6min != null && s6max != null ? ((s6max - s6min) / 25).toFixed(5) : '-'
    const customGap = customLow.value != null && customHigh.value != null ? ((customHigh.value - customLow.value) / 25).toFixed(5) : '-'
    rangeTableData.value = [
      { label: 'RowDataLimit', low: r.lower_limit?.toFixed(5) ?? '-', high: r.upper_limit?.toFixed(5) ?? '-', gap: rdlGap, unit },
      { label: `Data Range${cutSuffix}`, low: displayMin?.toFixed(5) ?? '-', high: displayMax?.toFixed(5) ?? '-', gap: drGap, unit },
      { label: 'CustomLimit', low: customLow.value?.toFixed(5) ?? '-', high: customHigh.value?.toFixed(5) ?? '-', gap: customGap, unit },
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
  watch(ignoreNoTestValue, () => loadHistogram())
  watch(dataOnlyBin1, () => loadHistogram())
  watch(onlyFailTestItem, () => loadHistogram())
  watch(onlyLowCpk, () => loadHistogram())
  watch(rangeType, () => loadHistogram())
  watch([customLow, customHigh], () => { if (rangeType.value === 'CL') loadHistogram() })
  watch(iqrMultiplier, () => loadHistogram())
  watch(outlierHandling, () => { if (lastResults) histogramUpdateView(lastResults) })
  watch(getSelectedFileId, () => { if (getSelectedFileId() && localSelectedParam.value) loadHistogram() })

  return { histResult, statCards, rangeTableData, loadHistogram, histLoading }
}
