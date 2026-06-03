import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAnalysisStore = defineStore('analysis', () => {
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

  // Tab3: 分布对比模式
  const comparisonMode = ref<'boxplot' | 'multilot'>('boxplot')

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
    comparisonMode.value = 'boxplot'
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
    comparisonMode,
    reset,
  }
})
