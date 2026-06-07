<template>
  <div class="single-param-tab">
    <!-- 顶部工具栏：模式切换 -->
    <div class="toolbar">
      <el-radio-group v-model="chartMode" size="small">
        <el-radio-button value="distribution">数值分布</el-radio-button>
        <el-radio-button value="serial">序列分布</el-radio-button>
      </el-radio-group>
      <el-checkbox
        v-if="chartMode === 'distribution'"
        v-model="showQQPlot"
        size="small"
        style="margin-left: 12px;"
      >
        显示QQ图
      </el-checkbox>
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
          <div class="top-bar-right">
            <StatsSummary :stat-cards="statCards" />
            <el-tag
              v-if="qqResult && showQQPlot"
              :type="qqResult.is_normal ? 'success' : 'danger'"
              size="small"
              class="normality-tag"
            >
              {{ qqResult.is_normal ? '正态' : '非正态' }}
            </el-tag>
          </div>
        </div>

        <!-- 图表：QQ图激活时上下布局（柱状图在上，QQ图在下） -->
        <div
          v-if="showQQPlot && chartMode === 'distribution' && histResult"
          class="chart-vertical-layout"
        >
          <div class="chart-wrapper chart-wrapper--top">
            <HistogramChart
              :result="histResult"
              :chart-config="chartConfig"
              :range-type="rangeType"
              :bar-width-percent="barWidthPercent"
              :selected-param="localSelectedParam"
            />
          </div>
          <div class="chart-wrapper chart-wrapper--bottom">
            <QQPlotChart
              :file-id="props.fileId"
              :param="localSelectedParam"
              :visible="showQQPlot"
              :result="qqResult"
              :loading="qqLoading"
            />
          </div>
        </div>
        <!-- 图表：默认全宽布局 -->
        <div v-else class="chart-wrapper">
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
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import api from '../../../api'
import { useAnalysisStore } from '../../../stores/analysis'
import ChartConfigPanel from './ChartConfigPanel.vue'
import RangeComparisonTable from './RangeComparisonTable.vue'
import SiteStatsTable from './SiteStatsTable.vue'
import ParamSelector from './ParamSelector.vue'
import StatsSummary from './StatsSummary.vue'
import HistogramChart from './HistogramChart.vue'
import SerialChart from './SerialChart.vue'
import QQPlotChart from './QQPlotChart.vue'
import { useHistogram } from '../composables/useHistogram'
import { useSerialDistribution } from '../composables/useSerialDistribution'
import { useSiteStats } from '../composables/useSiteStats'

const props = defineProps<{
  fileId: number | null
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
  () => props.fileId,
  localSelectedParam,
  ignoreNoLimit,
  rangeType,
  customLow,
  customHigh
)

// Composable: Serial Distribution
const {
  serialDistData,
  loadSerialDistribution,
} = useSerialDistribution(
  () => props.fileId,
  localSelectedParam,
  chartMode,
  chartConfig,
  rangeType
)

// Composable: Site Stats
const {
  siteStats,
  siteStatsError,
  loadSiteStats,
} = useSiteStats(
  () => props.fileId,
  localSelectedParam,
  rangeType
)

// ========== QQ Plot state ==========
const showQQPlot = ref(false)
const qqResult = ref<any>(null)
const qqLoading = ref(false)

async function loadQQPlot() {
  if (!props.fileId || !localSelectedParam.value || !showQQPlot.value) {
    qqResult.value = null
    return
  }
  qqLoading.value = true
  qqResult.value = null
  try {
    const { data } = await api.post('/analysis/qqplot/', {
      file_id: props.fileId,
      param: localSelectedParam.value,
    })
    qqResult.value = data
  } catch {
    qqResult.value = null
  } finally {
    qqLoading.value = false
  }
}

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
  if (showQQPlot.value && chartMode.value === 'distribution') {
    loadQQPlot()
  }
})

// ========== QQ Plot orchestration ==========
watch(showQQPlot, (val) => {
  if (val) {
    loadQQPlot()
  } else {
    qqResult.value = null
  }
})

watch(localSelectedParam, () => {
  if (showQQPlot.value) {
    loadQQPlot()
  }
})

watch(() => props.fileId, () => {
  if (showQQPlot.value) {
    loadQQPlot()
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
.single-param-tab {
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

.top-bar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.top-bar-right > :first-child {
  flex: 1;
  min-width: 0;
}

.normality-tag {
  flex-shrink: 0;
}

.chart-wrapper {
  flex: 1;
  min-height: 480px;
  background: #fff;
  border-radius: 6px;
  border: 1px solid #e4e7ed;
  overflow: hidden;
}

.chart-wrapper > * {
  height: 100%;
}

.chart-wrapper--bottom {
  min-height: 400px;
  margin-top: 12px;
}

.chart-vertical-layout {
  flex: 1;
  display: flex;
  flex-direction: column;
}
</style>
