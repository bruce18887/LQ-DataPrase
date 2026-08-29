<template>
  <div ref="chartRef" class="chart-container" />
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { initEchartsWhenReady, type EchartsHandle } from '../../../../utils/echarts-init'
import { useThemeStore } from '../../../../stores/theme'
import { useEChartsTheme } from '../../../../utils/echarts-theme'

const props = defineProps<{
  binDistribution: any[]
}>()

const chartRef = ref<HTMLElement>()
let handle: EchartsHandle | null = null

const themeStore = useThemeStore()
const { colors } = useEChartsTheme()

function buildOption() {
  // 注意：ECharts/zrender 不解析 CSS 变量，'var(--text)' 会回退默认深色
  //（夜晚不可读）——必须用 useEChartsTheme 的实时色值（2026-08-26 修复）
  const tc = colors.value.textColor
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', left: 'left', type: 'scroll', textStyle: { color: tc } },
    series: [{
      type: 'pie',
      radius: ['35%', '70%'],
      center: ['60%', '50%'],
      data: props.binDistribution,
      label: { formatter: '{b}\n{d}%', color: tc },
    }],
  }
}

function ensureChart() {
  if (!chartRef.value) return
  if (handle) {
    // 已有句柄：仅刷新 option（容器已就绪）
    handle.chart?.setOption(buildOption() as any, { notMerge: true, lazyUpdate: true })
    return
  }
  handle = initEchartsWhenReady(chartRef.value, {
    option: buildOption() as any,
    reuse: true,
  })
}

watch(() => themeStore.currentTheme, () => {
  nextTick(() => ensureChart())
})

watch(() => props.binDistribution, () => {
  nextTick(() => ensureChart())
}, { deep: true })

function handleResize() {
  handle?.chart?.resize()
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
  // 首次挂载时主动触发：watch 默认不在初始化时触发，
  // 而 props.binDistribution 在挂载时已被父组件绑定，不存在"变化"
  nextTick(() => ensureChart())
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  handle?.dispose()
  handle = null
})

defineExpose({ handleResize })
</script>

<style scoped>
.chart-container {
  height: 320px;
}
</style>
