import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

export const useAnalysisStore = defineStore('analysis', () => {
  const route = useRoute()
  const router = useRouter()

  // 持久化状态
  const selectedFileId = ref<number | null>(null)
  const selectedParam = ref('')
  const activeTab = ref('single-param')
  const chartMode = ref('distribution')
  const chartConfig = ref<string[]>(['limit', 's6'])
  const rangeType = ref('RDL')
  const barWidthPercent = ref(20)
  const ignoreNoLimit = ref(false)
  const customLow = ref<number | null>(null)
  const customHigh = ref<number | null>(null)
  const outlierHandling = ref<'clip' | 'exclude' | 'off'>('clip')
  const iqrMultiplier = ref<number>(1.5)

  // Tab: 多文件分析（multi-file）
  const multiFileIds = ref<number[]>([])
  const multiSelectedParam = ref('')
  const multiFileNames = ref<Record<number, string>>({})
  const multiChartConfig = ref<string[]>(['limit'])
  const multiBarWidthPercent = ref(20)
  const multiIgnoreNoLimit = ref(false)
  const multiRangeType = ref('RDL')

  // Initialize from URL query params
  function initFromQuery() {
    const q = route.query
    if (q.mf_ids) {
      const ids = String(q.mf_ids).split(',').map(Number).filter(n => !isNaN(n))
      if (ids.length >= 2) multiFileIds.value = ids
    }
    if (q.mf_param) multiSelectedParam.value = String(q.mf_param)
    if (q.mf_range) multiRangeType.value = String(q.mf_range)
  }

  // Sync multi-file state to URL query params (debounced)
  let syncTimer: ReturnType<typeof setTimeout> | null = null
  function syncToQuery() {
    if (syncTimer) clearTimeout(syncTimer)
    syncTimer = setTimeout(() => {
      const q: Record<string, string> = {}
      if (multiFileIds.value.length >= 2) q.mf_ids = multiFileIds.value.join(',')
      if (multiSelectedParam.value) q.mf_param = multiSelectedParam.value
      if (multiRangeType.value && multiRangeType.value !== 'RDL') q.mf_range = multiRangeType.value
      router.replace({ query: { ...route.query, ...q } })
    }, 300)
  }

  watch([multiFileIds, multiSelectedParam, multiRangeType], syncToQuery)

  function reset() {
    selectedFileId.value = null
    selectedParam.value = ''
    activeTab.value = 'single-param'
    chartMode.value = 'distribution'
    chartConfig.value = ['limit', 's6']
    rangeType.value = 'RDL'
    barWidthPercent.value = 20
    ignoreNoLimit.value = false
    customLow.value = null
    customHigh.value = null
    outlierHandling.value = 'clip'
    iqrMultiplier.value = 1.5
    multiFileIds.value = []
    multiSelectedParam.value = ''
    multiFileNames.value = {}
    multiChartConfig.value = ['limit']
    multiBarWidthPercent.value = 20
    multiIgnoreNoLimit.value = false
    multiRangeType.value = 'RDL'
  }

  return {
    selectedFileId,
    selectedParam,
    activeTab,
    chartMode,
    chartConfig,
    rangeType,
    barWidthPercent,
    ignoreNoLimit,
    customLow,
    customHigh,
    outlierHandling,
    iqrMultiplier,
    multiFileIds,
    multiSelectedParam,
    multiFileNames,
    multiChartConfig,
    multiBarWidthPercent,
    multiIgnoreNoLimit,
    multiRangeType,
    initFromQuery,
    reset,
  }
})
