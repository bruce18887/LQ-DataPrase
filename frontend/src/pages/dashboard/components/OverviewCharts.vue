<template>
  <div class="panel-row panel-row--h320">
    <div class="panel-card">
      <div class="panel-head">CPK 分布统计</div>
      <div class="panel-body"><div ref="cpkDistChart" class="chart-fill" role="img" aria-label="CPK分布统计饼图" /></div>
    </div>
    <div class="panel-card">
      <div class="panel-head">Top 10 Fail 测试项</div>
      <div class="panel-body"><div ref="failBarChart" class="chart-fill" role="img" aria-label="Top 10 Fail测试项柱状图" /></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onActivated, onBeforeUnmount } from 'vue'
import { initEchartsWhenReady, type EchartsHandle } from '../../../utils/echarts-init'
import { useThemeStore } from '../../../stores/theme'
import type { TestItemOverview } from '../../../types'

const themeStore = useThemeStore()

const props = defineProps<{
  items: TestItemOverview[]
}>()

const cpkDistChart = ref<HTMLElement>()
const failBarChart = ref<HTMLElement>()
let cpkDistHandle: EchartsHandle | null = null
let failBarHandle: EchartsHandle | null = null

function _tc() {
  return getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#ffffff'
}

function _ts() {
  return getComputedStyle(document.documentElement).getPropertyValue('--text-2').trim() || 'rgba(255,255,255,0.8)'
}

/* ── CPK 分布饼图 ── */
function buildCpkDistOption() {
  const levels: Record<string, number> = {}
  props.items.forEach(p => {
    const level = p.cpk_level || ''
    if (level) {
      levels[level] = (levels[level] || 0) + 1
    }
  })

  const chartData = Object.entries(levels)
    .filter(([_, value]) => value > 0)
    .map(([name, value]) => ({ name, value }))

  if (chartData.length === 0) {
    return {
      title: {
        text: '暂无CPK数据',
        left: 'center',
        top: 'center',
        textStyle: { color: _ts(), fontSize: 14 }
      }
    }
  }

  const getColorByLevel = (levelName: string) => {
    if (levelName.startsWith('A级')) return '#059669'  // 绿色 - 优秀
    if (levelName.startsWith('B级')) return '#d97706'  // 橙色 - 良好
    if (levelName.startsWith('C级')) return '#dc2626'  // 红色 - 一般
    if (levelName.startsWith('D级')) return '#9ca3af'  // 灰色 - 不足
    return '#d1d5db'
  }

  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c}个 ({d}%)' },
    legend: { orient: 'vertical', left: 'left', top: 'center', textStyle: { color: _tc() } },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      center: ['60%', '50%'],
      data: chartData.map(item => ({
        name: item.name,
        value: item.value,
        itemStyle: { color: getColorByLevel(item.name) }
      })),
      label: { formatter: '{b}: {c}个\n({d}%)' },
      color: chartData.map(item => getColorByLevel(item.name))
    }]
  }
}

function renderCpkDistChart() {
  if (!cpkDistChart.value || !props.items.length) return
  if (cpkDistHandle) {
    cpkDistHandle.chart?.setOption(buildCpkDistOption() as any, { notMerge: true, lazyUpdate: true })
  } else {
    cpkDistHandle = initEchartsWhenReady(cpkDistChart.value, { option: buildCpkDistOption() as any, reuse: true })
  }
}

/* ── Top 10 Fail 柱状图 ── */
function buildFailBarOption() {
  const top10 = props.items
    .filter((t) => t.fail_count > 0)
    .sort((a, b) => b.fail_count - a.fail_count)
    .slice(0, 10)

  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '8%', bottom: '3%', top: '3%', containLabel: true },
    xAxis: { type: 'value', axisLabel: { color: _tc() } },
    yAxis: {
      type: 'category',
      data: top10.map((t) => (t.name.length > 25 ? t.name.slice(0, 25) + '...' : t.name)).reverse(),
      axisLabel: { fontSize: 10, color: _tc() },
    },
    series: [{
      type: 'bar',
      data: top10.map((t) => t.fail_count).reverse(),
      itemStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 1, y2: 0,
          colorStops: [{ offset: 0, color: '#f87171' }, { offset: 1, color: '#dc2626' }],
        },
      },
      label: { show: true, position: 'right', fontSize: 10 },
    }],
  }
}

function renderFailBarChart() {
  if (!failBarChart.value || !props.items.length) return
  if (failBarHandle) {
    failBarHandle.chart?.setOption(buildFailBarOption() as any, { notMerge: true, lazyUpdate: true })
  } else {
    failBarHandle = initEchartsWhenReady(failBarChart.value, { option: buildFailBarOption() as any, reuse: true })
  }
}

function handleResize() {
  cpkDistHandle?.chart?.resize()
  failBarHandle?.chart?.resize()
}

watch(() => props.items, () => {
  nextTick(() => { renderCpkDistChart(); renderFailBarChart() })
}, { deep: true, immediate: true })

// 主题切换时重新渲染图表，更新文字颜色
watch(() => themeStore.currentTheme, () => {
  nextTick(() => { renderCpkDistChart(); renderFailBarChart() })
})

onMounted(() => {
  window.addEventListener('resize', handleResize)
  nextTick(() => { renderCpkDistChart(); renderFailBarChart() })
})

onActivated(() => {
  if (cpkDistHandle) { cpkDistHandle.dispose(); cpkDistHandle = null }
  if (failBarHandle) { failBarHandle.dispose(); failBarHandle = null }
  nextTick(() => { renderCpkDistChart(); renderFailBarChart() })
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  cpkDistHandle?.dispose(); cpkDistHandle = null
  failBarHandle?.dispose(); failBarHandle = null
})

defineExpose({ handleResize })
</script>

<style scoped>
/* ================================================================
   Panel Row — two-column grid
   ================================================================ */
.panel-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 20px;
}
@media (max-width: 992px) { .panel-row { grid-template-columns: 1fr; } }

.panel-row--h320 .panel-card { height: 320px; }
@media (max-width: 992px) {
  .panel-row--h320 .panel-card { height: auto; min-height: 300px; }
}

/* ================================================================
   Panel Card
   ================================================================ */
.panel-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,.04);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel-head {
  font-size: 14px;
  font-weight: 650;
  color: #374151;
  padding: 10px 16px;
  border-bottom: 1px solid #f3f4f6;
  background: #fafbfc;
  flex-shrink: 0;
}
.panel-body {
  flex: 1;
  min-height: 0;
  padding: 8px;
}
.chart-fill {
  width: 100%;
  height: 100%;
}
</style>
