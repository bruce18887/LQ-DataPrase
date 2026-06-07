<template>
  <div ref="chartRef" class="chart-container" />
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { initEchartsWhenReady, type EchartsHandle } from '../../../../utils/echarts-init'
import { useThemeStore } from '../../../../stores/theme'

const props = defineProps<{
  phases: any[]
  spcLimits?: { ucl?: number | null; cl?: number | null; lcl?: number | null }
}>()

const chartRef = ref<HTMLElement>()
let handle: EchartsHandle | null = null

const themeStore = useThemeStore()

function buildOption() {
  const phases = props.phases || []
  const spc = props.spcLimits || {}

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['测试总数', 'Pass数量', '良率', 'UCL', 'CL', 'LCL'], top: 5, textStyle: { color: 'var(--text-primary)' } },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '18%', containLabel: true },
    xAxis: {
      type: 'category',
      data: phases.map((p: any) => p.phase),
      axisLine: { lineStyle: { color: 'var(--border-default)' } },
      axisLabel: { color: 'var(--text-primary)' },
    },
    yAxis: [
      {
        type: 'value',
        name: '数量',
        position: 'left',
        axisLine: { lineStyle: { color: 'var(--border-default)' } },
        axisLabel: { color: 'var(--text-primary)' },
        splitLine: { lineStyle: { color: 'var(--border-muted)' } },
      },
      {
        type: 'value',
        name: '良率(%)',
        min: 0,
        max: 100,
        position: 'right',
        axisLabel: { formatter: '{value}%', color: 'var(--text-primary)' },
        nameTextStyle: { color: 'var(--text-primary)' },
        axisLine: { lineStyle: { color: 'var(--border-default)' } },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '测试总数', type: 'bar', data: phases.map((p: any) => p.total),
        itemStyle: { color: '#4facfe' }, barWidth: '25%',
      },
      {
        name: 'Pass数量', type: 'bar', data: phases.map((p: any) => p.pass_count),
        itemStyle: { color: '#11998e' }, barWidth: '25%',
      },
      {
        name: '良率', type: 'line', yAxisIndex: 1,
        data: phases.map((p: any) => p.yield_pct),
        itemStyle: { color: '#f5576c' }, lineStyle: { width: 3 },
        symbol: 'circle', symbolSize: 8,
        label: { show: true, formatter: '{c}%', fontSize: 11, color: 'var(--text-primary)' },
      },
      ...(spc.ucl != null ? [{
        name: 'UCL', type: 'line', yAxisIndex: 1,
        data: Array(phases.length).fill(spc.ucl),
        lineStyle: { type: 'dashed' as const, color: '#f5576c' }, symbol: 'none',
      }] : []),
      ...(spc.cl != null ? [{
        name: 'CL', type: 'line', yAxisIndex: 1,
        data: Array(phases.length).fill(spc.cl),
        lineStyle: { type: 'dashed' as const, color: '#11998e' }, symbol: 'none',
      }] : []),
      ...(spc.lcl != null ? [{
        name: 'LCL', type: 'line', yAxisIndex: 1,
        data: Array(phases.length).fill(spc.lcl),
        lineStyle: { type: 'dashed' as const, color: '#f5576c' }, symbol: 'none',
      }] : []),
    ],
  }
}

function ensureChart() {
  if (!chartRef.value) return
  if (handle) {
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

watch(() => [props.phases, props.spcLimits], () => {
  nextTick(() => ensureChart())
}, { deep: true })

function handleResize() {
  handle?.chart?.resize()
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
  // 首次挂载时主动触发：watch 默认不在初始化时触发，
  // 而 props.phases/spcLimits 在挂载时已被父组件绑定，不存在"变化"
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
