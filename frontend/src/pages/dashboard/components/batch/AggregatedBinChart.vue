<template>
  <div ref="chartRef" class="chart-container" />
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'
import { getChartInitOpts } from '../../../../utils/echarts-theme'
import { useThemeStore } from '../../../../stores/theme'

const props = defineProps<{
  binDistribution: any[]
}>()

const chartRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null

const themeStore = useThemeStore()

watch(() => themeStore.currentTheme, () => {
  nextTick(() => renderChart())
})

watch(() => props.binDistribution, () => {
  nextTick(() => renderChart())
}, { deep: true })

function renderChart() {
  if (!chartRef.value || !props.binDistribution?.length) return
  if (!chart) chart = echarts.init(chartRef.value, undefined, getChartInitOpts())
  else chart.clear()

  chart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', left: 'left', type: 'scroll', textStyle: { color: 'var(--text-primary)' } },
    series: [{
      type: 'pie',
      radius: ['35%', '70%'],
      center: ['60%', '50%'],
      data: props.binDistribution,
      label: { formatter: '{b}\n{d}%', color: 'var(--text-primary)' },
    }],
  })
}

function handleResize() {
  if (chart && !chart.isDisposed()) chart.resize()
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chart?.dispose(); chart = null
})

defineExpose({ handleResize })
</script>

<style scoped>
.chart-container {
  height: 320px;
}
</style>
