<script setup lang="ts">
import type { WeightGroupDto } from '../weightChartOption'
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import { buildWeightOption } from '../weightChartOption'

const props = defineProps<{ group: WeightGroupDto; showMean: boolean }>()
// useEChartsTheme() 只返回 { isDark, colors, getBaseOption }：取色一律走 colors.value.*（lessons R7②）。
const { colors, isDark } = useEChartsTheme()

const buildOption = () => buildWeightOption(props.group, {
  showMean: props.showMean,
  colors: colors.value.seriesColors,
  meanColor: colors.value.textColor,
  textColor: colors.value.textColor,
  axisLineColor: colors.value.axisLineColor,
  titleText: props.group.name,
})

const { chartRef } = useChart(
  buildOption,
  [() => props.group, () => props.showMean, isDark],
)
void chartRef // bound to <div ref="chartRef"> in template
</script>

<template>
  <div
    ref="chartRef"
    class="weight-chart"
    data-testid="weight-chart"
    :data-group="group.name"
  />
</template>

<style scoped>
.weight-chart {
  width: 100%;
  height: 320px;
  flex: 0 0 320px;
}
</style>
