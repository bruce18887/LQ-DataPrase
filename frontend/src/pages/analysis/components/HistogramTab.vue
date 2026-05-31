<template>
  <div class="histogram-tab">
    <!-- 顶部工具栏：模式切换 -->
    <div class="toolbar">
      <el-radio-group v-model="chartMode" size="small">
        <el-radio-button value="distribution">数值分布</el-radio-button>
        <el-radio-button value="serial">序列分布</el-radio-button>
      </el-radio-group>
    </div>

    <!-- 主内容区：左侧配置面板 + 右侧图表 -->
    <el-row :gutter="12" class="main-row">
      <!-- 左侧配置面板 -->
      <el-col :span="6" class="left-panel">
        <ChartConfigPanel
          v-model:chart-config="chartConfig"
          v-model:range-type="rangeType"
          v-model:bar-width-percent="barWidthPercent"
          v-model:ignore-no-limit="ignoreNoLimit"
          v-model:custom-low="customLow"
          v-model:custom-high="customHigh"
        />
        <RangeComparisonTable :range-table-data="rangeTableData" :range-type="rangeType" />
        <SiteStatsTable :site-stats="siteStats" :site-stats-error="siteStatsError" />
      </el-col>

      <!-- 右侧图表区 -->
      <el-col :span="18" class="right-panel" v-loading="histLoading" element-loading-text="正在分析数据...">
        <!-- 参数选择 + 统计摘要 -->
        <div class="top-bar">
          <ParamSelector
            :params="params"
            v-model:selected-param="localSelectedParam"
            @prev="prevParam"
            @next="nextParam"
          />
          <StatsSummary :stat-cards="statCards" />
        </div>

        <!-- 图表 -->
        <div class="chart-wrapper">
          <HistogramChart
            v-if="histResult && chartMode === 'distribution'"
            :result="histResult"
            :chart-config="chartConfig"
            :range-type="rangeType"
            :bar-width-percent="barWidthPercent"
            :selected-param="localSelectedParam"
          />
          <SerialChart
            v-if="chartMode === 'serial'"
            :data="serialDistData"
          />
        </div>
      </el-col>
    </el-row>

    <el-divider />

    <!-- 相关性分析 -->
    <CorrelationPanel
      :params="params"
      :loading="corrLoading"
      :pearson-r="corrPearsonR"
      :chart-data="corrResult"
      v-model:axis-mode="corrAxisMode"
      @analyze="loadCorrelation"
    />

    <!-- 批量导出 -->
    <BatchExportPanel
      :params="params"
      :exporting="exporting"
      @export-sigma="exportSigmaLimit"
      @export-batch="exportBatchCharts"
    />

    <!-- 相关性矩阵 -->
    <CorrelationMatrixPanel
      :loading="matrixLoading"
      :matrix-data="correlationMatrix"
      @calculate="loadCorrelationMatrix"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAnalysisStore } from '../../../stores/analysis'
import ChartConfigPanel from './ChartConfigPanel.vue'
import RangeComparisonTable from './RangeComparisonTable.vue'
import SiteStatsTable from './SiteStatsTable.vue'
import ParamSelector from './ParamSelector.vue'
import StatsSummary from './StatsSummary.vue'
import HistogramChart from './HistogramChart.vue'
import SerialChart from './SerialChart.vue'
import CorrelationPanel from './CorrelationPanel.vue'
import BatchExportPanel from './BatchExportPanel.vue'
import CorrelationMatrixPanel from './CorrelationMatrixPanel.vue'
import { useHistogram } from '../composables/useHistogram'
import { useSerialDistribution } from '../composables/useSerialDistribution'
import { useCorrelation } from '../composables/useCorrelation'
import { useSiteStats } from '../composables/useSiteStats'
import { useExport } from '../composables/useExport'

const props = defineProps<{
  files: any[]
  selectedFileId: number | null
  params: string[]
  loading: boolean
}>()

const localSelectedParam = defineModel<string>('selectedParam', { default: '' })

const analysisStore = useAnalysisStore()

// Chart configuration state
const chartMode = ref(analysisStore.chartMode)
const rangeType = ref(analysisStore.rangeType)
const chartConfig = ref<string[]>(analysisStore.chartConfig)
const barWidthPercent = ref(analysisStore.barWidthPercent)
const ignoreNoLimit = ref(analysisStore.ignoreNoLimit)
const customLow = ref<number | null>(analysisStore.customLow)
const customHigh = ref<number | null>(analysisStore.customHigh)

// Composable: Histogram
const {
  histResult,
  statCards,
  rangeTableData,
  histLoading,
} = useHistogram(
  () => props.selectedFileId,
  localSelectedParam,
  ignoreNoLimit
)

// Composable: Serial Distribution
const {
  serialDistData,
  loadSerialDistribution,
} = useSerialDistribution(
  () => props.selectedFileId,
  localSelectedParam,
  chartMode,
  chartConfig,
  rangeType
)

// Composable: Correlation
const {
  corrLoading,
  corrResult,
  corrPearsonR,
  corrAxisMode,
  loadCorrelation,
} = useCorrelation(() => props.selectedFileId)

// Composable: Site Stats
const {
  siteStats,
  siteStatsError,
  loadSiteStats,
} = useSiteStats(
  () => props.selectedFileId,
  localSelectedParam,
  rangeType
)

// Composable: Export & Correlation Matrix
const {
  exporting,
  correlationMatrix,
  matrixLoading,
  loadCorrelationMatrix,
  exportSigmaLimit,
  exportBatchCharts,
} = useExport(() => props.selectedFileId)

// ========== Store sync ==========
watch(chartMode, (val) => { analysisStore.chartMode = val })
watch(chartConfig, (val) => { analysisStore.chartConfig = val }, { deep: true })
watch(rangeType, (val) => { analysisStore.rangeType = val })
watch(barWidthPercent, (val) => { analysisStore.barWidthPercent = val })
watch(ignoreNoLimit, (val) => { analysisStore.ignoreNoLimit = val })
watch(customLow, (val) => { analysisStore.customLow = val })
watch(customHigh, (val) => { analysisStore.customHigh = val })

// ========== Cross-composable orchestration ==========
watch([chartConfig, rangeType], () => {
  loadSiteStats()
}, { deep: true })

watch(histResult, () => {
  loadSiteStats()
  if (chartMode.value === 'serial') {
    loadSerialDistribution()
  }
})

// ========== Param navigation ==========
function prevParam() {
  const idx = props.params.indexOf(localSelectedParam.value)
  if (idx > 0) {
    localSelectedParam.value = props.params[idx - 1]
  } else if (props.params.length > 0) {
    localSelectedParam.value = props.params[props.params.length - 1]
  }
}

function nextParam() {
  const idx = props.params.indexOf(localSelectedParam.value)
  if (idx < props.params.length - 1) {
    localSelectedParam.value = props.params[idx + 1]
  } else if (props.params.length > 0) {
    localSelectedParam.value = props.params[0]
  }
}
</script>

<style scoped>
.histogram-tab {
  padding: 0;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: #f8f9fa;
  border-radius: 6px;
  border: 1px solid #e4e7ed;
}

.main-row {
  margin-bottom: 16px;
}

.left-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.right-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.top-bar {
  display: flex;
  gap: 12px;
  align-items: stretch;
}

.top-bar > *:first-child {
  flex: 0 0 320px;
}

.top-bar > *:last-child {
  flex: 1;
  min-width: 0;
}

.chart-wrapper {
  flex: 1;
  min-height: 520px;
  background: #fff;
  border-radius: 6px;
  border: 1px solid #e4e7ed;
  overflow: hidden;
}

.chart-wrapper > * {
  height: 100%;
}
</style>

<style>
.param-select-dropdown .el-select-dropdown__list {
  max-height: 360px;
  overflow-y: auto;
}

.range-active-row {
  background-color: #d0e8ff !important;
  font-weight: bold;
  color: #e53935;
}
</style>
