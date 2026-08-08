import { watch, type Ref } from 'vue'
import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'

export function useSerialDistribution(
  getSelectedFileId: () => number | null,
  localSelectedParam: Ref<string>,
  chartMode: Ref<string>,
  chartConfig: Ref<string[]>,
  rangeType: Ref<string>,
  /** Available numeric param names — skip API call if current param is not numeric */
  availableParams?: Ref<string[]>,
  /** 仅用 Pass 数据(Bin1)：序列点只保留 pass-bin 行 */
  dataOnlyBin1?: Ref<boolean>,
) {
  const { data: serialDistData, run } = useAsyncData<any>({ silent: true })

  async function loadSerialDistribution() {
    const fileId = getSelectedFileId()
    if (!fileId || !localSelectedParam.value) return
    // Skip if param is known to be non-numeric
    if (availableParams?.value && !availableParams.value.includes(localSelectedParam.value)) return
    await run(() => api.post('/analysis/serial_distribution/', {
      file_id: fileId,
      param: localSelectedParam.value,
      chart_config: chartConfig.value,
      range_type: rangeType.value,
      data_only_bin1: dataOnlyBin1?.value ?? false,
    }))
  }

  watch(chartMode, (val) => { if (val === 'serial') loadSerialDistribution() })
  watch([chartConfig, rangeType], () => { if (chartMode.value === 'serial') loadSerialDistribution() }, { deep: true })
  watch(localSelectedParam, () => { if (chartMode.value === 'serial') loadSerialDistribution() })
  if (dataOnlyBin1) watch(dataOnlyBin1, () => { if (chartMode.value === 'serial') loadSerialDistribution() })

  return { serialDistData, loadSerialDistribution }
}
