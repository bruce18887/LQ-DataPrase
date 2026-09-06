import { watch, ref, type Ref } from 'vue'
import api from '../../../api'
import { useAsyncData } from '../../../composables/useAsyncData'

export function useSerialDistribution(
  getSelectedFileId: () => number | null,
  localSelectedParam: Ref<string>,
  /** 「显示序列分布」勾选态：为 true 时才拉取/响应各 watch（原 chartMode==='serial' 模式改勾选共存） */
  serialEnabled: Ref<boolean>,
  chartConfig: Ref<string[]>,
  rangeType: Ref<string>,
  /** Available numeric param names — skip API call if current param is not numeric */
  availableParams?: Ref<string[]>,
  /** 仅用 Pass 数据(Bin1)：序列点只保留 pass-bin 行 */
  dataOnlyBin1?: Ref<boolean>,
  /** 显式指定序列列（空串 = 自动检测：Serial_No > Dut_No > PART_ID） */
  serialCol?: Ref<string>,
  /** 敏感度（IQR 倍数）：属于调用方 tab 自己的状态 */
  iqrMultiplier: Ref<number> = ref(1.5),
  /** CL 模式的用户自定义限：与 histogram 同口径（后端 resolve 'CL'） */
  customLow?: Ref<number | null>,
  customHigh?: Ref<number | null>,
) {
  const { data: serialDistData, error: serialError, run } = useAsyncData<any>({ silent: true })

  async function loadSerialDistribution() {
    const fileId = getSelectedFileId()
    // 未真正发请求的分支也要清错误态，否则旧 serialError 横幅会一直挂着
    serialError.value = null
    if (!fileId || !localSelectedParam.value) {
      // 切文件清参数的早退：旧文件的序列图滞留会误导（与 useQQPlot 同口径，
      // 2026-09-05 审查 M2）
      serialDistData.value = null
      return
    }
    // Skip if param is known to be non-numeric
    if (availableParams?.value && !availableParams.value.includes(localSelectedParam.value)) {
      serialDistData.value = null
      return
    }
    await run(() => api.post('/analysis/serial_distribution/', {
      file_id: fileId,
      param: localSelectedParam.value,
      chart_config: chartConfig.value,
      range_type: rangeType.value,
      // CL 语义三端点统一为「用户自定义限」：不带的话后端把数据 min/max
      // 画成 "LSL/USL" 幻影限值线，与同屏直方图矛盾
      custom_low: rangeType.value === 'CL' ? customLow?.value ?? null : null,
      custom_high: rangeType.value === 'CL' ? customHigh?.value ?? null : null,
      data_only_bin1: dataOnlyBin1?.value ?? false,
      serial_col: serialCol?.value || undefined,
      // 敏感度在**发请求时**实时读 ref（不是挂载时快照）。后端本端点
      // 此前连 parse_filter_flags 都没调，异常值栅栏写死 1.5，现已贯穿。
      iqr_multiplier: iqrMultiplier.value,
    }))
  }

  // 「显示序列分布」勾选 → 立即拉取；取消勾选不主动清空（组件不渲染即隐藏），
  // 再勾回时若数据已在则复用，避免重复请求（与 useQQPlot enabled 口径一致）
  watch(serialEnabled, (val) => { if (val) loadSerialDistribution() })
  // 敏感度变化 → 重发（与 useHistogram 同口径），否则序列分布的异常值
  // 标记会滞留旧值，与同屏直方图矛盾。
  watch(iqrMultiplier, () => {
    if (serialEnabled.value) loadSerialDistribution()
  })
  watch([chartConfig, rangeType], () => { if (serialEnabled.value) loadSerialDistribution() }, { deep: true })
  watch(localSelectedParam, () => { if (serialEnabled.value) loadSerialDistribution() })
  if (dataOnlyBin1) watch(dataOnlyBin1, () => { if (serialEnabled.value) loadSerialDistribution() })
  if (serialCol) watch(serialCol, () => { if (serialEnabled.value) loadSerialDistribution() })

  return { serialDistData, serialError, loadSerialDistribution }
}
