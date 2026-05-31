import { ref, watch, type Ref } from 'vue'
import api from '../../../api'

export function useSerialDistribution(
  getSelectedFileId: () => number | null,
  localSelectedParam: Ref<string>,
  chartMode: Ref<string>,
  chartConfig: Ref<string[]>,
  rangeType: Ref<string>
) {
  const serialDistData = ref<any>(null)

  async function loadSerialDistribution() {
    const fileId = getSelectedFileId()
    if (!fileId || !localSelectedParam.value) return
    try {
      const { data } = await api.post('/analysis/serial_distribution/', {
        file_id: fileId,
        param: localSelectedParam.value,
        chart_config: chartConfig.value,
        range_type: rangeType.value,
      })
      serialDistData.value = data
    } catch {
      // silently fail
    }
  }

  watch(chartMode, (val) => {
    if (val === 'serial') {
      loadSerialDistribution()
    }
  })

  watch([chartConfig, rangeType], () => {
    if (chartMode.value === 'serial') {
      loadSerialDistribution()
    }
  }, { deep: true })

  return {
    serialDistData,
    loadSerialDistribution,
  }
}
