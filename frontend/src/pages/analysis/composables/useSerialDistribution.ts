import { watch, type Ref } from 'vue'
import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'
import { useAnalysisStore } from '../../../stores/analysis'

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
  /** 显式指定序列列（空串 = 自动检测：Serial_No > Dut_No > PART_ID） */
  serialCol?: Ref<string>,
) {
  const { data: serialDistData, error: serialError, run } = useAsyncData<any>({ silent: true })
  const analysisStore = useAnalysisStore()

  async function loadSerialDistribution() {
    const fileId = getSelectedFileId()
    // 未真正发请求的分支也要清错误态，否则旧 serialError 横幅会一直挂着
    serialError.value = null
    if (!fileId || !localSelectedParam.value) return
    // Skip if param is known to be non-numeric
    if (availableParams?.value && !availableParams.value.includes(localSelectedParam.value)) return
    await run(() => api.post('/analysis/serial_distribution/', {
      file_id: fileId,
      param: localSelectedParam.value,
      chart_config: chartConfig.value,
      range_type: rangeType.value,
      data_only_bin1: dataOnlyBin1?.value ?? false,
      serial_col: serialCol?.value || undefined,
      // 敏感度在**发请求时**实时读 store（不是挂载时快照）。后端本端点
      // 此前连 parse_filter_flags 都没调，异常值栅栏写死 1.5，现已贯穿。
      iqr_multiplier: analysisStore.iqrMultiplier,
    }))
  }

  watch(chartMode, (val) => { if (val === 'serial') loadSerialDistribution() })
  // 敏感度变化 → 重发（与 useHistogram 同口径），否则序列分布的异常值
  // 标记会滞留旧值，与同屏直方图矛盾。
  watch(() => analysisStore.iqrMultiplier, () => {
    if (chartMode.value === 'serial') loadSerialDistribution()
  })
  watch([chartConfig, rangeType], () => { if (chartMode.value === 'serial') loadSerialDistribution() }, { deep: true })
  watch(localSelectedParam, () => { if (chartMode.value === 'serial') loadSerialDistribution() })
  if (dataOnlyBin1) watch(dataOnlyBin1, () => { if (chartMode.value === 'serial') loadSerialDistribution() })
  if (serialCol) watch(serialCol, () => { if (chartMode.value === 'serial') loadSerialDistribution() })

  return { serialDistData, serialError, loadSerialDistribution }
}
