<template>
  <AnalysisTabLayout :loading="histLoading">
    <template #toolbar>
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
      <el-checkbox
        v-if="chartMode === 'distribution'"
        v-model="showBoxPlot"
        size="small"
        style="margin-left: 12px;"
      >
        显示箱线图
      </el-checkbox>
      <el-checkbox
        v-if="showBoxPlot"
        v-model="showJitter"
        size="small"
        style="margin-left: 12px;"
      >
        Jitter散点
      </el-checkbox>
      <el-select
        v-if="showBoxPlot"
        v-model="groupBy"
        size="small"
        style="width: 120px; margin-left: 8px"
        placeholder="分组方式"
      >
        <el-option
          v-for="opt in groupByOptions"
          :key="opt.value"
          :label="opt.label"
          :value="opt.value"
        />
      </el-select>
    </template>

    <template #left-panel>
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
      <QQPlotStatsTable v-if="showQQPlot && qqResult" :result="qqResult" />
      <BoxPlotStatsTable
        v-if="showBoxPlot && boxPlotOverallStats && !boxPlotLoading"
        :stats="boxPlotOverallStats"
      />
      <el-skeleton
        v-else-if="showBoxPlot && boxPlotLoading"
        :rows="4"
        animated
        style="margin-top: 8px;"
      />
    </template>

    <template #right-panel>
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

      <!-- 图表：distribution 模式 -->
      <div
        v-if="chartMode === 'distribution' && histResult"
        class="chart-vertical-layout"
      >
        <div class="chart-wrapper chart-wrapper--top">
          <HistogramChart
            :result="histResult"
            :chart-config="chartConfig"
            :range-type="rangeType"
            :bar-width-percent="barWidthPercent"
            :selected-param="localSelectedParam"
            :outlier-handling="outlierHandling"
          />
        </div>
        <div v-if="showQQPlot" :key="`qq-${localSelectedParam}`" class="chart-wrapper chart-wrapper--bottom">
          <QQPlotChart
            :file-id="props.fileId"
            :param="localSelectedParam"
            :visible="showQQPlot"
            :result="qqResult"
            :loading="qqLoading"
          />
        </div>
        <div
          v-if="showBoxPlot"
          :key="`bp-${localSelectedParam}`"
          class="chart-wrapper chart-wrapper--bottom"
          style="position: relative;"
        >
          <el-skeleton
            v-if="boxPlotLoading"
            :rows="6"
            animated
            style="position: absolute; inset: 0; z-index: 10; background: var(--el-bg-color);"
          />
          <BoxPlotChart
            :data="currentBoxPlotData"
            :show-jitter="showJitter"
            :visible="showBoxPlot"
          />
        </div>
      </div>
      <!-- 图表：serial 模式 -->
      <div v-else-if="chartMode === 'serial'" class="chart-wrapper">
        <SerialChart v-if="serialDistData" :data="serialDistData" />
        <el-empty v-else description="当前参数无序列分布数据，请选择其他参数" />
      </div>
    </template>
  </AnalysisTabLayout>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useAnalysisStore } from '../../../stores/analysis'
import ChartConfigPanel from './ChartConfigPanel.vue'
import RangeComparisonTable from './RangeComparisonTable.vue'
import SiteStatsTable from './SiteStatsTable.vue'
import ParamSelector from './ParamSelector.vue'
import StatsSummary from './StatsSummary.vue'
import HistogramChart from './HistogramChart.vue'
import SerialChart from './SerialChart.vue'
import QQPlotChart from './QQPlotChart.vue'
import BoxPlotChart from './BoxPlotChart.vue'
import QQPlotStatsTable from './QQPlotStatsTable.vue'
import BoxPlotStatsTable from './distribution/BoxPlotStatsTable.vue'
import AnalysisTabLayout from './AnalysisTabLayout.vue'
import { useHistogram } from '../composables/useHistogram'
import { useSerialDistribution } from '../composables/useSerialDistribution'
import { useSiteStats } from '../composables/useSiteStats'
import { useBoxPlot } from '../composables/useBoxPlot'
import { useQQPlot } from '../composables/useQQPlot'

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
const outlierHandling = ref(analysisStore.outlierHandling)

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
  rangeType,
  computed(() => props.params),
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

// Composable: BoxPlot
const showBoxPlot = ref(false)
const showJitter = ref(false)
const groupBy = ref('site')
const groupByOptions = [
  { label: '按 Site 分组', value: 'site' },
  { label: '按 Bin 分组', value: 'bin' },
  { label: '不分组', value: '' },
]
const {
  boxPlotData,
  loading: boxPlotLoading,
} = useBoxPlot(
  () => props.fileId,
  localSelectedParam,
  groupBy,
  showBoxPlot,
)
const currentBoxPlotData = computed(() => {
  if (!boxPlotData.value || !localSelectedParam.value) return null
  const paramData = boxPlotData.value[localSelectedParam.value]
  if (!paramData) return null
  return { ...paramData, param: localSelectedParam.value }
})
const boxPlotOverallStats = computed(() => currentBoxPlotData.value?.overall ?? null)

// Composable: QQ Plot
const showQQPlot = ref(false)
const {
  qqLoading,
  qqResult,
  loadQQPlot,
} = useQQPlot(
  () => props.fileId,
  localSelectedParam,
  showQQPlot,
)

// ========== Store sync ==========
watch(chartMode, (val) => { analysisStore.chartMode = val })
watch(chartConfig, (val) => { analysisStore.chartConfig = val }, { deep: true })
watch(rangeType, (val) => { analysisStore.rangeType = val })
watch(barWidthPercent, (val) => { analysisStore.barWidthPercent = val })
watch(ignoreNoLimit, (val) => { analysisStore.ignoreNoLimit = val })
watch(customLow, (val) => { analysisStore.customLow = val })
watch(customHigh, (val) => { analysisStore.customHigh = val })
watch(outlierHandling, (val) => { analysisStore.outlierHandling = val })
watch(() => analysisStore.outlierHandling, (val) => { outlierHandling.value = val })

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

// When the file changes, the parent component is responsible for resetting
// the selectedParam (see AnalysisPage.onFileChange). This watcher is a
// defense-in-depth fallback: if a parent path forgets to reset it, we
// don't carry the stale value into the new file's chart APIs.
watch(() => props.fileId, () => {
  localSelectedParam.value = ''
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
