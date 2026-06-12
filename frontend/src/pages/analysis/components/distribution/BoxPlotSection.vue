<!-- frontend/src/pages/analysis/components/distribution/BoxPlotSection.vue -->
<template>
  <AnalysisTabLayout :loading="loading">
    <!-- 工具栏：散点叠加开关 -->
    <template #toolbar>
      <el-switch v-model="showJitter" size="small" active-text="显示散点叠加" />
    </template>

    <!-- 左侧面板：参数选择 + 统计表格 -->
    <template #left-panel>
      <ParamSelector
        :params="availableParams"
        v-model:selected-param="localSelectedParam"
        @prev="prevParam"
        @next="nextParam"
      />
      <BoxPlotStatsTable :stats="stats" />
    </template>

    <!-- 右侧面板：统计卡片 + 图表 -->
    <template #right-panel>
      <div class="top-bar">
        <StatsSummary :stat-cards="statCards" />
      </div>

      <div class="chart-wrapper">
        <BoxPlotChart
          v-if="currentParamData"
          :data="currentParamData"
          :title="`Box Plot - ${localSelectedParam}`"
          :show-jitter="showJitter"
        />
        <el-empty v-else description="请选择参数" />
      </div>
    </template>
  </AnalysisTabLayout>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import AnalysisTabLayout from '../AnalysisTabLayout.vue'
import ParamSelector from '../ParamSelector.vue'
import StatsSummary from '../StatsSummary.vue'
import BoxPlotChart from '../BoxPlotChart.vue'
import BoxPlotStatsTable from './BoxPlotStatsTable.vue'
import { useBoxPlot } from '../../composables/useBoxPlot'

const props = defineProps<{
  fileId: number | null
  availableParams: string[]
}>()

const localSelectedParam = ref('')
const groupBy = ref('site') // 固定按 Site 分组
const showJitter = ref(false)

const { loading, boxPlotData, stats } = useBoxPlot(
  () => props.fileId,
  localSelectedParam,
  groupBy
)

/** 当前参数的箱线图数据 */
const currentParamData = computed(() => {
  if (!boxPlotData.value || !localSelectedParam.value) return null
  const paramData = boxPlotData.value[localSelectedParam.value]
  if (!paramData) return null
  return { param: localSelectedParam.value, ...paramData }
})

/** 统计卡片 */
const statCards = computed(() => {
  if (!stats.value) return []
  const s = stats.value
  return [
    { label: 'Min', value: s.min.toFixed(4) },
    { label: 'Q1', value: s.q1.toFixed(4) },
    { label: 'Median', value: s.median.toFixed(4) },
    { label: 'Q3', value: s.q3.toFixed(4) },
    { label: 'Max', value: s.max.toFixed(4) },
    { label: 'Outliers', value: String(s.outliers.length) },
  ]
})

// Auto-select first param when params change
watch(() => props.availableParams, (newParams) => {
  if (newParams.length > 0 && !localSelectedParam.value) {
    localSelectedParam.value = newParams[0]
  }
}, { immediate: true })

// Reset when file changes
watch(() => props.fileId, () => {
  localSelectedParam.value = ''
})

function prevParam() {
  const idx = props.availableParams.indexOf(localSelectedParam.value)
  if (idx > 0) {
    localSelectedParam.value = props.availableParams[idx - 1]
  } else if (props.availableParams.length > 0) {
    localSelectedParam.value = props.availableParams[props.availableParams.length - 1]
  }
}

function nextParam() {
  const idx = props.availableParams.indexOf(localSelectedParam.value)
  if (idx < props.availableParams.length - 1) {
    localSelectedParam.value = props.availableParams[idx + 1]
  } else if (props.availableParams.length > 0) {
    localSelectedParam.value = props.availableParams[0]
  }
}
</script>

<style scoped>
.top-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.top-bar :deep(.stats-summary) {
  flex: 1;
}

.chart-wrapper {
  flex: 1;
  min-height: 480px;
  background: var(--bg-secondary, #fff);
  border-radius: 6px;
  border: 1px solid var(--border-default, #e4e7ed);
  overflow: hidden;
}

.chart-wrapper > * {
  height: 100%;
}
</style>
