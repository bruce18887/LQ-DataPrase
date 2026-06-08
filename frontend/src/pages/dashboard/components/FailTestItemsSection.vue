<template>
  <div>
    <h2 class="sec-title"><span>📉</span> Fail 测试项分析</h2>
    <div class="panel-row panel-row--h320">
      <div class="panel-card">
        <div class="panel-head">📋 Fail 测试项明细</div>
        <el-table :data="failTestItems" stripe size="small" max-height="280" border class="panel-table">
          <el-table-column prop="name" label="测试项名称" show-overflow-tooltip min-width="180" />
          <el-table-column prop="fail_count" label="Fail数量" width="90" align="center" />
          <el-table-column prop="percentage" label="占比" width="80" align="center">
            <template #default="{ row }">{{ row.percentage }}%</template>
          </el-table-column>
        </el-table>
        <div class="fail-total">总 Fail 次数: <b>{{ totalFailCount }}</b></div>
      </div>
      <div class="panel-card">
        <div class="panel-head">Top 10 Fail 测试项</div>
        <div class="panel-body"><div ref="failBarChart" class="chart-fill" role="img" aria-label="Top 10 Fail测试项柱状图" /></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { initEchartsWhenReady, type EchartsHandle } from '../../../utils/echarts-init'
import { useThemeStore } from '../../../stores/theme'

const themeStore = useThemeStore()

const props = defineProps<{
  failTestItems: { name: string; fail_count: number; percentage: number }[]
  totalFailCount: number
}>()

const failBarChart = ref<HTMLElement>()
let failBarHandle: EchartsHandle | null = null

function _tc() {
  return getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#ffffff'
}

function buildFailBarOption() {
  const top10 = props.failTestItems.slice(0, 10)

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
  if (!failBarChart.value || !props.failTestItems.length) return
  if (failBarHandle) {
    failBarHandle.chart?.setOption(buildFailBarOption() as any, { notMerge: true, lazyUpdate: true })
  } else {
    failBarHandle = initEchartsWhenReady(failBarChart.value, { option: buildFailBarOption() as any, reuse: true })
  }
}

function handleResize() {
  failBarHandle?.chart?.resize()
}

watch(() => props.failTestItems, () => {
  nextTick(() => renderFailBarChart())
}, { deep: true, immediate: true })

// 主题切换时重新渲染图表，更新文字颜色
watch(() => themeStore.currentTheme, () => {
  nextTick(() => renderFailBarChart())
})

onMounted(() => {
  window.addEventListener('resize', handleResize)
  nextTick(() => renderFailBarChart())
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  failBarHandle?.dispose(); failBarHandle = null
})

defineExpose({ handleResize })
</script>

<style scoped>
/* ================================================================
   Section Title
   ================================================================ */
.sec-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 17px;
  font-weight: 700;
  color: #1f2937;
  margin: 24px 0 12px 0;
  padding-left: 10px;
  border-left: 3px solid #2563eb;
  line-height: 1;
}

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
.panel-table {
  flex: 1;
  min-height: 0;
}
.chart-fill {
  width: 100%;
  height: 100%;
}

/* ================================================================
   Fail total
   ================================================================ */
.fail-total {
  text-align: right;
  color: #dc2626;
  font-weight: 600;
  font-size: 13px;
  padding: 8px 12px;
  border-top: 1px solid #fee2e2;
  background: #fef2f2;
  margin-top: auto;
}
</style>
