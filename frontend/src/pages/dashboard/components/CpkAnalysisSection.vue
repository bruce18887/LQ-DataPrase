<template>
  <div v-if="paramStats.length">
    <h2 class="sec-title"><span>📊</span> 参数质量分析 (Top 10 CPK)</h2>
    <div class="panel-row panel-row--wider panel-row--h350">
      <div class="panel-card panel-card--wider">
        <div class="panel-head">📋 CPK 参数表</div>
        <el-table :data="topParamStats" stripe size="small" max-height="310" border class="panel-table">
          <el-table-column prop="param" label="参数名称" min-width="140" show-overflow-tooltip />
          <el-table-column prop="cpk" label="CPK" width="80" align="center">
            <template #default="{ row }">
              <el-tag :type="getCpkTagType(row.cpk)" size="small">{{ row.cpk.toFixed(2) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="cpk_level" label="等级" width="90" align="center">
            <template #default="{ row }">
              <span :style="{ color: row.cpk_color, fontWeight: 'bold' }">{{ row.cpk_level }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="mean" label="均值" width="120" align="right">
            <template #default="{ row }">{{ row.mean.toFixed(4) }} <span class="cell-unit">{{ row.unit }}</span></template>
          </el-table-column>
          <el-table-column prop="std" label="标准差" width="90" align="right">
            <template #default="{ row }">{{ row.std.toFixed(4) }}</template>
          </el-table-column>
          <el-table-column label="规格限" width="180" align="center">
            <template #default="{ row }">
              <span v-if="row.lsl !== null && row.usl !== null" class="cell-spec">{{ row.lsl.toFixed(4) }} ~ {{ row.usl.toFixed(4) }}</span>
              <span v-else class="cell-na">未设置</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div class="panel-card">
        <div class="panel-head">CPK 分布统计</div>
        <div class="panel-body"><div ref="cpkDistChart" class="chart-fill" role="img" aria-label="CPK分布统计饼图" /></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { initEchartsWhenReady, type EchartsHandle } from '../../../utils/echarts-init'
import { useThemeStore } from '../../../stores/theme'

const themeStore = useThemeStore()

const props = defineProps<{
  paramStats: any[]
}>()

const cpkDistChart = ref<HTMLElement>()
let cpkDistHandle: EchartsHandle | null = null

const topParamStats = computed(() => props.paramStats.slice(0, 10))

function _tc() {
  return getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#ffffff'
}

function _ts() {
  return getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim() || 'rgba(255,255,255,0.8)'
}

function getCpkTagType(cpk: number): string {
  if (cpk >= 1.67) return 'success'
  if (cpk >= 1.33) return 'warning'
  return 'danger'
}

function buildCpkDistOption() {
  // 统计CPK分布 - 使用实际的等级名称（带括号）
  const levels: Record<string, number> = {}
  props.paramStats.forEach(p => {
    const level = p.cpk_level || ''
    if (level) {
      levels[level] = (levels[level] || 0) + 1
    }
  })

  // 过滤掉值为0的等级
  const chartData = Object.entries(levels)
    .filter(([_, value]) => value > 0)
    .map(([name, value]) => ({ name, value }))

  // 如果所有等级都是0，显示空状态
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

  // 定义颜色映射 - 根据等级前缀匹配
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
  if (!cpkDistChart.value || !props.paramStats.length) return
  if (cpkDistHandle) {
    cpkDistHandle.chart?.setOption(buildCpkDistOption() as any, { notMerge: true, lazyUpdate: true })
  } else {
    cpkDistHandle = initEchartsWhenReady(cpkDistChart.value, { option: buildCpkDistOption() as any, reuse: true })
  }
}

function handleResize() {
  cpkDistHandle?.chart?.resize()
}

watch(() => props.paramStats, () => {
  nextTick(() => renderCpkDistChart())
}, { deep: true, immediate: true })

// 主题切换时重新渲染图表，更新文字颜色
watch(() => themeStore.currentTheme, () => {
  nextTick(() => renderCpkDistChart())
})

onMounted(() => {
  window.addEventListener('resize', handleResize)
  nextTick(() => renderCpkDistChart())
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  cpkDistHandle?.dispose(); cpkDistHandle = null
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

@media (min-width: 993px) {
  .panel-row--wider {
    grid-template-columns: 7fr 5fr;
  }
}

.panel-row--h350 .panel-card { height: 350px; }
@media (max-width: 992px) {
  .panel-row--h350 .panel-card { height: auto; min-height: 300px; }
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
   Table cell helpers
   ================================================================ */
.cell-unit { color: #9ca3af; font-size: 11px; }
.cell-spec { font-size: 12px; color: #374151; }
.cell-na   { color: #9ca3af; }
</style>
