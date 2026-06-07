import { watch, type Ref } from 'vue'
import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'

export function useSerialDistribution(
  getSelectedFileId: () => number | null,
  localSelectedParam: Ref<string>,
  chartMode: Ref<string>,
  chartConfig: Ref<string[]>,
  rangeType: Ref<string>
) {
  const { data: serialDistData, run } = useAsyncData<any>({ silent: true })

  async function loadSerialDistribution() {
    const fileId = getSelectedFileId()
    if (!fileId || !localSelectedParam.value) return
    await run(() => api.post('/analysis/serial_distribution/', {
      file_id: fileId,
      param: localSelectedParam.value,
      chart_config: chartConfig.value,
      range_type: rangeType.value,
    }))
  }

  watch(chartMode, (val) => { if (val === 'serial') loadSerialDistribution() })
  watch([chartConfig, rangeType], () => { if (chartMode.value === 'serial') loadSerialDistribution() }, { deep: true })

  return { serialDistData, loadSerialDistribution }
}
