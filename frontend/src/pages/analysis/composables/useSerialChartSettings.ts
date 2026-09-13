/**
 * 序列分布图的「按 Site 拆分 / 点径 / 透明度」设置（从 SerialChart.vue 局部态上提）。
 *
 * 上提原因：这三项设置移到图表标题栏右上角的齿轮弹层，而齿轮由 SingleParamTab
 * 渲染、与图表体不在同一组件里 —— 状态必须由父级持有，再以 props 下发给 SerialChart。
 *
 * 语义（spec 2026-09-12）：
 * - 自动档：按总点数分级（大文件散点不糊成实色带）；
 * - 手动覆盖：null = 自动；每次数据重载清零，避免手动值毁掉小文件；
 * - splitBySite 为会话级偏好，不随数据重载重置。
 */
import { computed, ref, watch, type Ref } from 'vue'

/** 按总点数自适应点径/透明度（分级表为单一来源） */
export function autoPointStyle(count: number): { size: number; opacity: number } {
  if (count < 5000) return { size: 6, opacity: 0.85 }
  if (count <= 20000) return { size: 4, opacity: 0.5 }
  return { size: 3, opacity: 0.35 }
}

export function useSerialChartSettings(data: Ref<any>) {
  const pointCount = computed(() =>
    (data.value?.series_data || []).reduce(
      (sum: number, sd: { data?: unknown[] }) => sum + (sd.data?.length ?? 0), 0))
  const siteCount = computed(() => (data.value?.series_data || []).length)
  const canSplit = computed(() => siteCount.value >= 2)

  const autoStyle = computed(() => autoPointStyle(pointCount.value))

  /** 按 Site 拆分小多图开关（会话级偏好，不随数据重载重置） */
  const splitBySite = ref(false)
  /** 手动覆盖（null = 自动）：每次数据重载清零 */
  const pointSizeOverride = ref<number | null>(null)
  const opacityOverridePct = ref<number | null>(null) // 百分比 10-100

  watch(data, () => {
    pointSizeOverride.value = null
    opacityOverridePct.value = null
  })

  const effSize = computed(() => pointSizeOverride.value ?? autoStyle.value.size)
  const effOpacityPct = computed(() => opacityOverridePct.value ?? Math.round(autoStyle.value.opacity * 100))
  const effOpacity = computed(() => effOpacityPct.value / 100)
  const sizeAutoHint = computed(() => (pointSizeOverride.value == null ? '(自动)' : ''))
  const opacityAutoHint = computed(() => (opacityOverridePct.value == null ? '(自动)' : ''))

  return {
    splitBySite,
    pointSizeOverride,
    opacityOverridePct,
    pointCount,
    siteCount,
    canSplit,
    autoStyle,
    effSize,
    effOpacityPct,
    effOpacity,
    sizeAutoHint,
    opacityAutoHint,
  }
}
