<template>
  <div ref="chartRef" class="chart-container" />
</template>

<script setup lang="ts">
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import { buildMultiFileOption } from '../multiFileChartOption'
import type { MultiLotResponse, MultiLotTheme } from '../multiFileChartOption'

const props = defineProps<{
  /** /analysis/multi_lot/ 带 param 的响应 */
  lotData: any
  chartConfig: string[]
  barWidthPercent: number
  /** file_id → 自定义图例名 */
  fileNames: Record<number, string>
  selectedParam: string
}>()

const { colors, isDark } = useEChartsTheme()

/**
 * option 构造本身是纯函数（`pages/analysis/multiFileChartOption.ts`，判据住在 T2 的
 * `multiFileChartOption.spec.ts`）；这里只负责把主题色从 store 取出来传进去 ——
 * 纯模块一旦 import vue/pinia，T2 的 `environment: 'node'` 就起不来。
 */
function buildOption() {
  const theme: MultiLotTheme = {
    textColor: colors.value.textColor,
    axisLineColor: colors.value.axisLineColor,
    tooltipBg: colors.value.tooltipBg,
    tooltipBorder: colors.value.tooltipBorder,
    tooltipText: colors.value.tooltipText,
    isDark: isDark.value,
  }
  return buildMultiFileOption({
    lotData: props.lotData as MultiLotResponse,
    chartConfig: props.chartConfig,
    barWidthPercent: props.barWidthPercent,
    fileNames: props.fileNames,
    selectedParam: props.selectedParam,
    theme,
  })
}

const { chartRef } = useChart(buildOption, [
  () => props.lotData,
  () => props.chartConfig,
  () => props.barWidthPercent,
  () => props.fileNames,
  () => props.selectedParam,
])
void chartRef // bound to <div ref="chartRef"> in template
</script>

<style scoped>
.chart-container {
  width: 100%;
  height: 100%;
  min-height: 480px;
}
</style>
