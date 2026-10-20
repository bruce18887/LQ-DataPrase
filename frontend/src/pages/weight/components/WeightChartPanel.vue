<script setup lang="ts">
import { computed } from 'vue'
import type { WeightGroupDto } from '../weightChartOption'
import { groupCodeMax, groupColor } from '../weightChartOption'
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import { buildWeightOption } from '../weightChartOption'

const props = defineProps<{ group: WeightGroupDto; showMean: boolean }>()
// useEChartsTheme() 只返回 { isDark, colors, getBaseOption }：取色一律走 colors.value.*（lessons R7②）。
const { colors, isDark } = useEChartsTheme()

const color = computed(() => groupColor(colors.value.seriesColors, props.group.index))
const codeCount = computed(() => groupCodeMax(props.group) + 1)

const buildOption = () => buildWeightOption(props.group, {
  showMean: props.showMean,
  colors: colors.value.seriesColors,
  meanColor: colors.value.textColor,
  textColor: colors.value.textColor,
  labelColor: colors.value.titleColor,
  axisLineColor: colors.value.axisLineColor,
  splitLineColor: colors.value.splitLineColor,
  titleText: props.group.name,
})

const { chartRef } = useChart(
  buildOption,
  [() => props.group, () => props.showMean, isDark],
)
void chartRef // bound to <div ref="chartRef"> in template
</script>

<template>
  <article
    class="weight-chart-card"
    data-testid="weight-chart"
    :data-group="group.name"
  >
    <header class="weight-chart-head">
      <span class="group-dot" :style="{ backgroundColor: color }" aria-hidden="true" />
      <span class="group-name" :title="group.name">{{ group.name }}</span>
      <span class="group-meta">
        {{ group.series.length }} 系列{{ showMean ? ' + 均值' : '' }} · {{ codeCount }} Code
      </span>
    </header>
    <div ref="chartRef" class="weight-chart-body" />
  </article>
</template>

<style scoped>
.weight-chart-card {
  min-width: 0;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--p-radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  transition: box-shadow 0.2s ease, border-color 0.2s ease;
}

.weight-chart-card:hover {
  border-color: var(--border-2);
  box-shadow: var(--shadow-md);
}

.weight-chart-head {
  display: flex;
  align-items: center;
  gap: 7px;
  height: 34px;
  padding: 0 12px;
  background: color-mix(in srgb, var(--bg-2) 60%, var(--card));
  border-bottom: 1px solid var(--border);
}

.group-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  border-radius: 2px;
}

.group-name {
  min-width: 0;
  flex: 0 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--p-fs-dense);
  font-weight: 700;
  color: var(--text);
}

.group-meta {
  margin-left: 2px;
  flex: 0 0 auto;
  white-space: nowrap;
  font-size: var(--p-fs-micro);
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}

.weight-chart-body {
  width: 100%;
  height: 300px;
  padding: 4px 4px 0;
}
</style>
