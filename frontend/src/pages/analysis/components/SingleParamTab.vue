<template>
  <AnalysisTabLayout :loading="histLoading" class="single-param-tab">
    <template #toolbar>
      <AnalysisFilePicker
        v-model="fileId"
        :files="files"
        scope="single"
        :loading="tabLoading"
      />
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
        :bar-width-max="barWidthMax"
        v-model:bar-overlap-percent="barOverlapPercent"
        v-model:custom-low="customLow"
        v-model:custom-high="customHigh"
      />
      <!-- 数据筛选与异常值处理：只动本 tab 的那份状态 -->
      <DataFilterSection
        v-model:ignore-no-limit="ignoreNoLimit"
        v-model:ignore-no-test-value="ignoreNoTestValue"
        v-model:data-only-bin1="dataOnlyBin1"
        v-model:only-fail-test-item="onlyFailTestItem"
        v-model:only-low-cpk="onlyLowCpk"
        v-model:outlier-handling="outlierHandling"
        v-model:iqr-multiplier="iqrMultiplier"
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
      <ErrorBanner
        v-if="histError"
        :message="histError"
        title="直方图数据加载失败"
        @retry="loadHistogram"
      />
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
            :bar-overlap-percent="barOverlapPercent"
            :selected-param="localSelectedParam"
            :outlier-handling="outlierHandling"
          />
        </div>
        <div v-if="showQQPlot" :key="`qq-${localSelectedParam}`" class="chart-wrapper chart-wrapper--bottom">
          <QQPlotChart
            :file-id="fileId"
            :param="localSelectedParam"
            :visible="showQQPlot"
            :result="qqResult"
            :loading="qqLoading"
            :error="qqError"
            :outlier-handling="outlierHandling"
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
            :error="boxPlotError"
            :show-jitter="showJitter"
            :visible="showBoxPlot"
          />
        </div>
      </div>
      <!-- 图表：serial 模式 -->
      <div v-else-if="chartMode === 'serial'" class="chart-wrapper">
        <!-- 无序列号列等错误：优先展示提示，避免渲染残留旧数据或空图 -->
        <el-alert
          v-if="serialError"
          :title="serialError"
          type="error"
          show-icon
          :closable="false"
          class="serial-error-alert"
        />
        <SerialChart
          v-else-if="serialDistData"
          :data="serialDistData"
          :outlier-handling="outlierHandling"
          :serial-col="serialCol"
          :serial-candidates="serialDistData.serial_candidates || []"
          @update:serial-col="(v: string) => { serialCol = v }"
        />
        <el-empty v-else description="当前参数无序列分布数据，请选择其他参数" />
      </div>
    </template>
  </AnalysisTabLayout>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useSingleTabStore } from '../../../stores/analysisTabs'
import type { DataFile } from '../../../types'
import { getMaxBarWidthPercent } from '../../../utils/chart-bar'
import ChartConfigPanel from './ChartConfigPanel.vue'
import DataFilterSection from './DataFilterSection.vue'
import AnalysisFilePicker from './AnalysisFilePicker.vue'
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
import ErrorBanner from '../../../components/common/ErrorBanner.vue'
import { useHistogram } from '../composables/useHistogram'
import { useSerialDistribution } from '../composables/useSerialDistribution'
import { useSiteStats } from '../composables/useSiteStats'
import { useBoxPlot } from '../composables/useBoxPlot'
import { useQQPlot } from '../composables/useQQPlot'
import { useTabFileParams } from '../composables/useTabFileParams'

const props = defineProps<{
  /** 文件列表（页面统一拉一次给 4 个 tab；本 tab 自己的选择存在单文件 store） */
  files: DataFile[]
}>()

// Chart configuration state
// 直接取本 tab 子 store 的 ref（storeToRefs），本组件的读写就是 store 的读写。
// 之前这里是 14 个 `ref(analysisStore.x)` 本地快照 + 逐个 watch 回写，
// store→组件方向只有 outlierHandling 补了，于是页头改「敏感度」后
// useHistogram 仍用挂载时快照的 1.5 发请求：界面显示宽松 3.0x，
// 后端却按严格 1.5x 算异常值边界。
const {
  fileId,
  params,
  selectedParam: localSelectedParam,
  loading: tabLoading,
  chartMode,
  rangeType,
  chartConfig,
  barWidthPercent,
  barOverlapPercent,
  ignoreNoLimit,
  ignoreNoTestValue,
  dataOnlyBin1,
  onlyFailTestItem,
  onlyLowCpk,
  customLow,
  customHigh,
  outlierHandling,
  iqrMultiplier,
} = storeToRefs(useSingleTabStore())

// 本 tab 的文件→参数列表（与晶圆图/相关性 tab 互不影响）
useTabFileParams({
  ctx: { fileId, params, loading: tabLoading, selectedParam: localSelectedParam },
  files: computed(() => props.files),
  filters: () => ({
    ignore_no_limit: ignoreNoLimit.value,
    ignore_no_test_value: ignoreNoTestValue.value,
    data_only_bin1: dataOnlyBin1.value,
    only_fail_test_item: onlyFailTestItem.value,
    only_low_cpk: onlyLowCpk.value,
    iqr_multiplier: iqrMultiplier.value,
  }),
})
// 序列列手动选择（空串 = 自动检测）；多候选文件（Serial_No + Dut_No）由
// SerialChart 选择器写入，文件切换时重置回自动检测
const serialCol = ref('')

// Composable: Histogram
const {
  histResult,
  statCards,
  rangeTableData,
  histLoading,
  histError,
  loadHistogram,
} = useHistogram(
  () => fileId.value,
  localSelectedParam,
  ignoreNoLimit,
  rangeType,
  customLow,
  customHigh,
  iqrMultiplier,
  outlierHandling,
  ignoreNoTestValue,
  dataOnlyBin1,
  onlyFailTestItem,
  onlyLowCpk
)

// 柱宽 slider 上限：随系列数 + 重合度联动（N 系列柱组必须 ≤ bin 宽，否则贴限
// 柱体越过 USL 线——回归 limit-line-cross；重合越高柱组越窄、上限越高）
const barWidthMax = computed(() => {
  const sh = histResult.value?.site_histograms
  const keys = sh ? Object.keys(sh) : []
  return getMaxBarWidthPercent(keys.length >= 1 ? keys.length + 1 : 1, barOverlapPercent.value)
})
// 系列数变化时把已超上限的柱宽 clamp（避免 slider 显示 20% 实际 9%）
watch(barWidthMax, (max) => {
  if (barWidthPercent.value > max) barWidthPercent.value = max
})

// Composable: Serial Distribution
const {
  serialDistData,
  serialError,
  loadSerialDistribution,
} = useSerialDistribution(
  () => fileId.value,
  localSelectedParam,
  chartMode,
  chartConfig,
  rangeType,
  params,
  dataOnlyBin1,
  serialCol,
  iqrMultiplier,
)

// Composable: Site Stats
const {
  siteStats,
  siteStatsError,
  loadSiteStats,
} = useSiteStats(
  () => fileId.value,
  localSelectedParam,
  rangeType,
  dataOnlyBin1,
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
  boxPlotError,
  loading: boxPlotLoading,
} = useBoxPlot(
  () => fileId.value,
  localSelectedParam,
  groupBy,
  showBoxPlot,
  dataOnlyBin1,
  iqrMultiplier,
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
  qqError,
  loadQQPlot,
} = useQQPlot(
  () => fileId.value,
  localSelectedParam,
  showQQPlot,
  dataOnlyBin1,
  iqrMultiplier,
)

// ========== Store sync ==========
// 无：图表配置全部经 storeToRefs 直接读写 store（见上方 state 声明），
// 不再需要「本地快照 + watch 回写」这层胶水。

// ========== Cross-composable orchestration ==========
// site_stats 只依赖 range_type（与图表配置无关）：改 rangeType 触发一次，
// 切参数由下方 watch(localSelectedParam) 触发 —— 之前 chartConfig 变动和
// histResult 变化也会连带触发，一次修改产生两次重复请求
watch([rangeType], () => {
  loadSiteStats()
})

watch(localSelectedParam, () => {
  loadSiteStats()
})

watch(histResult, () => {
  if (chartMode.value === 'serial') {
    loadSerialDistribution()
  }
  if (showQQPlot.value && chartMode.value === 'distribution') {
    loadQQPlot()
  }
})

// 换文件时本 tab 的参数由 useTabFileParams 重新校验/回退首项（它拉新列表时
// 已把不在列表里的旧参数丢掉）；序列列选择是文件局部的配置，必须重置回自动检测
watch(fileId, () => {
  serialCol.value = ''
})

// ========== Param navigation ==========
function prevParam() {
  const idx = params.value.indexOf(localSelectedParam.value)
  if (idx > 0) {
    localSelectedParam.value = params.value[idx - 1]
  } else if (params.value.length > 0) {
    localSelectedParam.value = params.value[params.value.length - 1]
  }
}

function nextParam() {
  const idx = params.value.indexOf(localSelectedParam.value)
  if (idx < params.value.length - 1) {
    localSelectedParam.value = params.value[idx + 1]
  } else if (params.value.length > 0) {
    localSelectedParam.value = params.value[0]
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
  background: var(--bg-2, #fff);
  border-radius: 6px;
  border: 1px solid var(--border-2, #e4e7ed);
  overflow: hidden;
}

.chart-wrapper > * {
  height: 100%;
}

.serial-error-alert {
  margin: 16px;
  height: auto;
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
