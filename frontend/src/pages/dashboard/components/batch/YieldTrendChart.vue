<template>
  <div ref="chartRef" class="chart-container" />
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onActivated, onBeforeUnmount } from 'vue'
import { initEchartsWhenReady, observeContainerResize, type EchartsHandle } from '../../../../utils/echarts-init'
import { useThemeStore } from '../../../../stores/theme'
import { useEChartsTheme } from '../../../../utils/echarts-theme'
import { formatPercent } from '../../../../utils/chart-bar'

const props = defineProps<{
  phases: any[]
}>()

const chartRef = ref<HTMLElement>()
let handle: EchartsHandle | null = null
let stopObserve: (() => void) | null = null

const themeStore = useThemeStore()
const { colors } = useEChartsTheme()

function buildOption() {
  const phases = props.phases || []
  // 注意：ECharts/zrender 不解析 CSS 变量，'var(--text)' 会回退默认深色
  //（夜晚不可读）——必须用 useEChartsTheme 的实时色值（2026-08-26 修复）。
  // 同理 zrender 也不解析 CSS 函数 color-mix()：下方柱/线的颜色一度写成
  // 'color-mix(in srgb, var(--brand) 45%, transparent)' 与 'var(--info)'，
  // 与本注释自相矛盾，批次趋势图的柱体与折线在双主题下全部失色。
  const tc = colors.value.textColor
  const lineC = colors.value.axisLineColor
  const splitC = colors.value.splitLineColor
  const barC = colors.value.brandColorSoft
  const infoC = colors.value.infoColor

  // X 轴标签用唯一键（同名 phase 带 wafer 后缀），避免不同文件同名 phase
  // 在 category 轴上重复导致"标签与柱子对不上"。
  const xLabels = phases.map((p: any) => (p.wafer_id ? `${p.phase}-W${p.wafer_id}` : p.phase))
  // interval: 0 强制每个分类都出标签（ECharts 默认 auto 会跳签漏签，
  // 视觉上就是"X 坐标与柱状图对不上"）；数量多时旋转防重叠。
  const rotate = xLabels.length > 8 ? 45 : 0

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: ['测试总数', '良率'], top: 5, textStyle: { color: tc } },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '18%', containLabel: true },
    xAxis: {
      type: 'category',
      data: xLabels,
      axisLine: { lineStyle: { color: lineC } },
      axisTick: { alignWithLabel: true },
      axisLabel: {
        color: tc,
        interval: 0,
        rotate,
        // 回退短文件名较长，截断防标签重叠；tooltip 显示完整阶段名
        formatter: (val: string) => (val.length > 10 ? val.slice(0, 10) + '…' : val),
      },
    },
    yAxis: [
      {
        type: 'value',
        name: '数量',
        position: 'left',
        axisLine: { lineStyle: { color: lineC } },
        axisLabel: { color: tc },
        splitLine: { lineStyle: { color: splitC } },
      },
      {
        type: 'value',
        name: '良率(%)',
        min: 0,
        max: 100,
        position: 'right',
        axisLabel: { formatter: '{value}%', color: tc },
        nameTextStyle: { color: tc },
        axisLine: { lineStyle: { color: lineC } },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        // 柱 = 测试总数（品牌 45% 淡染，审阅页 t-bar 同色）
        name: '测试总数', type: 'bar', data: phases.map((p: any) => p.total),
        itemStyle: { color: barC }, barWidth: '40%',
      },
      {
        // 线 = 良率走势（--info 语义色）
        name: '良率', type: 'line', yAxisIndex: 1,
        data: phases.map((p: any) => p.yield_pct),
        itemStyle: { color: infoC }, lineStyle: { width: 2, color: infoC },
        symbol: 'circle', symbolSize: 6,
        label: { show: true, formatter: (p: any) => `${formatPercent(Number(p.value))}%`, fontSize: 11, color: tc },
      },
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

watch(() => props.phases, () => {
  nextTick(() => ensureChart())
}, { deep: true })

function handleResize() {
  handle?.chart?.resize()
}

onMounted(() => {
  // 容器级 RO：隐藏 Tab 切回/缩放均可靠 resize（window resize 覆盖不到 display:none 场景）
  stopObserve = observeContainerResize(chartRef.value, handleResize)
  // 首次挂载时主动触发：watch 默认不在初始化时触发，
  // 而 props.phases 在挂载时已被父组件绑定，不存在“变化”
  nextTick(() => ensureChart())
})

onActivated(() => {
  if (handle) { handle.dispose(); handle = null }
  nextTick(() => ensureChart())
})

onBeforeUnmount(() => {
  stopObserve?.()
  stopObserve = null
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
