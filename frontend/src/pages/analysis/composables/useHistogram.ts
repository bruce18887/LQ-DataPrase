import { ref, watch, type Ref } from 'vue'
import api from '../../../api'

export function useHistogram(
  getSelectedFileId: () => number | null,
  localSelectedParam: Ref<string>,
  ignoreNoLimit: Ref<boolean>,
  rangeType: Ref<string>,
  customLow: Ref<number | null>,
  customHigh: Ref<number | null>
) {
  const histResult = ref<any>(null)
  const statCards = ref<{ label: string; value: string; color?: string }[]>([])
  const rangeTableData = ref<any[]>([])
  const histLoading = ref(false)

  async function loadHistogram() {
    const fileId = getSelectedFileId()
    if (!fileId || !localSelectedParam.value) return
    histLoading.value = true
    try {
      const { data } = await api.post('/analysis/histogram/', {
        file_id: fileId,
        params: [localSelectedParam.value],
        ignore_no_limit: ignoreNoLimit.value,
        range_type: rangeType.value,
        custom_low: rangeType.value === 'CL' ? customLow.value : null,
        custom_high: rangeType.value === 'CL' ? customHigh.value : null,
      })
      histogramUpdateView(data.results as Record<string, any>)
    } catch {
      // silently fail
    } finally {
      histLoading.value = false
    }
  }

  function histogramUpdateView(results: Record<string, any>) {
    const r = results[localSelectedParam.value]
    if (!r) return
    histResult.value = r

    const clrs: Record<string, string> = {
      green: '#4CAF50',
      orange: '#FF9800',
      darkorange: '#FF5722',
      red: '#F44336',
      gray: '#9E9E9E',
    }

    const rangeVal = r.data_max != null && r.data_min != null ? r.data_max - r.data_min : null
    const s3min = r.sigma3_min ?? (r.mean != null && r.std != null ? r.mean - 3 * r.std : null)
    const s3max = r.sigma3_max ?? (r.mean != null && r.std != null ? r.mean + 3 * r.std : null)
    const s6min = r.sigma6_min ?? (r.mean != null && r.std != null ? r.mean - 6 * r.std : null)
    const s6max = r.sigma6_max ?? (r.mean != null && r.std != null ? r.mean + 6 * r.std : null)

    statCards.value = [
      { label: 'N', value: r.total_count?.toLocaleString() ?? '-' },
      { label: 'Mean', value: r.mean?.toFixed(4) ?? '-' },
      { label: 'Median', value: r.median?.toFixed(4) ?? '-' },
      { label: 'STD', value: r.std?.toFixed(4) ?? '-' },
      { label: 'Min', value: r.data_min?.toFixed(4) ?? '-' },
      { label: 'Max', value: r.data_max?.toFixed(4) ?? '-' },
      { label: 'Range', value: rangeVal != null ? rangeVal.toFixed(4) : '-' },
      {
        label: 'CPK',
        value: r.cpk != null ? `${r.cpk.toFixed(4)} (${r.cpk_level})` : '-',
        color: clrs[r.cpk_color] ?? undefined,
      },
      {
        label: '3σ',
        value: s3min != null && s3max != null
          ? `[${s3min.toFixed(4)}, ${s3max.toFixed(4)}]`
          : '-',
      },
      {
        label: '6σ',
        value: s6min != null && s6max != null
          ? `[${s6min.toFixed(4)}, ${s6max.toFixed(4)}]`
          : '-',
      },
    ]

    const s4min = (r.mean || 0) - 4 * (r.std || 0)
    const s4max = (r.mean || 0) + 4 * (r.std || 0)
    const unit = r.unit || ''
    const rdlGap = r.upper_limit != null && r.lower_limit != null ? ((r.upper_limit - r.lower_limit) / 25).toFixed(5) : '-'
    const drGap = r.data_max != null && r.data_min != null ? ((r.data_max - r.data_min) / 25).toFixed(5) : '-'
    const s3Gap = s3min != null && s3max != null ? ((s3max - s3min) / 25).toFixed(5) : '-'
    const s4Gap = s4max != null && s4min != null ? ((s4max - s4min) / 25).toFixed(5) : '-'
    const s6Gap = s6min != null && s6max != null ? ((s6max - s6min) / 25).toFixed(5) : '-'

    rangeTableData.value = [
      { label: 'RowDataLimit', low: r.lower_limit?.toFixed(5) ?? '-', high: r.upper_limit?.toFixed(5) ?? '-', gap: rdlGap, unit },
      { label: 'Data Range', low: r.data_min?.toFixed(5) ?? '-', high: r.data_max?.toFixed(5) ?? '-', gap: drGap, unit },
      { label: 'CustomLimit', low: r.data_min?.toFixed(5) ?? '-', high: r.data_max?.toFixed(5) ?? '-', gap: drGap, unit },
      { label: '3 Sigma', low: s3min?.toFixed(5) ?? '-', high: s3max?.toFixed(5) ?? '-', gap: s3Gap, unit },
      { label: '4 Sigma', low: s4min?.toFixed(5) ?? '-', high: s4max?.toFixed(5) ?? '-', gap: s4Gap, unit },
      { label: '6 Sigma', low: s6min?.toFixed(5) ?? '-', high: s6max?.toFixed(5) ?? '-', gap: s6Gap, unit },
    ]
  }

  watch(localSelectedParam, () => {
    loadHistogram()
  })

  watch(ignoreNoLimit, () => {
    loadHistogram()
  })

  // Range type / custom limits drive server-side binning → must re-fetch.
  watch(rangeType, () => {
    loadHistogram()
  })

  watch([customLow, customHigh], () => {
    if (rangeType.value === 'CL') {
      loadHistogram()
    }
  })

  watch(getSelectedFileId, () => {
    const fileId = getSelectedFileId()
    if (fileId && localSelectedParam.value) {
      loadHistogram()
    }
  })

  return {
    histResult,
    statCards,
    rangeTableData,
    loadHistogram,
    histLoading,
  }
}
