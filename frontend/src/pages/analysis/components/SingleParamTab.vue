<template>
  <AnalysisTabLayout :loading="histLoading" class="single-param-tab">
    <template #toolbar>
      <div class="control-panel">
        <!-- 第一行：选文件（左） + 三个「显示…」图表勾选（右对齐） -->
        <div class="control-panel__main">
          <AnalysisFilePicker
            v-model="fileId"
            :files="files"
            scope="single"
            :loading="tabLoading"
          />
          <div class="chart-toggles">
            <el-checkbox v-model="showSerial" size="small">显示序列分布</el-checkbox>
            <el-checkbox v-model="showQQPlot" size="small">显示QQ图</el-checkbox>
            <el-checkbox v-model="showBoxPlot" size="small">显示箱线图</el-checkbox>
          </div>
        </div>
        <!-- 第二行：数据口径（异常值处理 · 敏感度 · 数据筛选），内联无卡片 -->
        <div class="control-panel__filters">
          <DataFilterSection
            variant="bar"
            v-model:ignore-no-limit="ignoreNoLimit"
            v-model:ignore-no-test-value="ignoreNoTestValue"
            v-model:data-only-bin1="dataOnlyBin1"
            v-model:only-fail-test-item="onlyFailTestItem"
            v-model:only-low-cpk="onlyLowCpk"
            v-model:outlier-handling="outlierHandling"
            v-model:iqr-multiplier="iqrMultiplier"
          />
        </div>
      </div>
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
      <RangeComparisonTable :range-table-data="rangeTableData" :range-type="rangeType" />
      <SiteStatsTable :site-stats="siteStats" :site-stats-error="siteStatsError" />
      <QQPlotStatsTable v-if="showQQPlot && qqResult" :result="qqResult" />
      <BoxPlotStatsTable
        v-if="showBoxPlot && currentBoxPlotData && !boxPlotLoading"
        :data="currentBoxPlotData"
        :group-by="groupBy"
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
        </div>
      </div>

      <!-- 图表：可停靠拼格区（el-splitter 拖分隔条改高宽 + 标题栏手柄拖拽换布局 + 持久化） -->
      <ChartDock v-if="histResult" :active-keys="activeChartKeys" @close="onDockClose">
        <template #hist>
          <HistogramChart
            :result="histResult"
            :chart-config="chartConfig"
            :range-type="rangeType"
            :bar-width-percent="barWidthPercent"
            :bar-overlap-percent="barOverlapPercent"
            :selected-param="localSelectedParam"
            :outlier-handling="outlierHandling"
          />
        </template>

        <template #serial>
          <!-- 无序列号列等错误：优先提示，避免渲染残留旧数据或空图 -->
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
        </template>

        <template #qq>
          <QQPlotChart
            :file-id="fileId"
            :param="localSelectedParam"
            :visible="showQQPlot"
            :result="qqResult"
            :loading="qqLoading"
            :error="qqError"
            :outlier-handling="outlierHandling"
          />
        </template>

        <template #box>
          <div class="box-chart-host">
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
              :group-kind="groupBy === 'bin' ? 'bin' : 'site'"
            />
          </div>
        </template>

        <!-- 箱线图专属控件：分组方式 + 离群点，随图标题栏同屏（原在左栏，现归箱线图） -->
        <template #controls-box>
          <el-select v-model="groupBy" size="small" style="width: 120px" placeholder="分组方式">
            <el-option
              v-for="opt in groupByOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
          <el-checkbox v-model="showJitter" size="small">离群点</el-checkbox>
        </template>
      </ChartDock>
    </template>
  </AnalysisTabLayout>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
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
import ChartDock from './ChartDock.vue'
import ErrorBanner from '../../../components/common/ErrorBanner.vue'
import { useHistogram } from '../composables/useHistogram'
import { useSerialDistribution } from '../composables/useSerialDistribution'
import { useSiteStats } from '../composables/useSiteStats'
import { useBoxPlot } from '../composables/useBoxPlot'
import { useQQPlot } from '../composables/useQQPlot'
import { useTabFileParams } from '../composables/useTabFileParams'
import type { ChartKey } from '../composables/useChartDock'
import { loadChartMemory, saveChartState } from '../../../composables/useChartMemory'

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
// 序列分布由「显示序列分布」勾选驱动（原 chartMode==='serial' 互斥模式已移除），
// 勾选后序列图叠加显示在直方图下方，与 QQ/箱线共存
const showSerial = ref(false)

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
} = useSerialDistribution(
  () => fileId.value,
  localSelectedParam,
  showSerial,
  chartConfig,
  rangeType,
  params,
  dataOnlyBin1,
  serialCol,
  iqrMultiplier,
  customLow,
  customHigh,
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
  customLow,
  customHigh,
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

// Composable: QQ Plot
const showQQPlot = ref(false)
const {
  qqLoading,
  qqResult,
  qqError,
} = useQQPlot(
  () => fileId.value,
  localSelectedParam,
  showQQPlot,
  dataOnlyBin1,
  iqrMultiplier,
)

// ========== Chart dock（可停靠拼格布局）==========
// 当前可见图表 key 列表：直方图恒在，序列/QQ/箱线随勾选增删。
// 顺序即 ChartDock 的 reconcile 依据（新增图追加、取消勾选移除，保留其余相对顺序）。
const activeChartKeys = computed<ChartKey[]>(() => {
  const keys: ChartKey[] = ['hist']
  if (showSerial.value) keys.push('serial')
  if (showQQPlot.value) keys.push('qq')
  if (showBoxPlot.value) keys.push('box')
  return keys
})
// 面板「×」关闭 → 复位对应勾选（与顶部三个显示勾选同源）
function onDockClose(key: ChartKey) {
  if (key === 'serial') showSerial.value = false
  else if (key === 'qq') showQQPlot.value = false
  else if (key === 'box') showBoxPlot.value = false
}

// ========== 图表勾选账号记忆 ==========
// 套用与上报互斥：套用期间 watcher 不回写（避免把「恢复」当「用户改动」再存一遍）
let togglesApplying = false
let togglesTouched = false
watch([showSerial, showQQPlot, showBoxPlot], ([s, q, b]) => {
  if (togglesApplying) return
  togglesTouched = true
  saveChartState({ toggles: { serial: s, qq: q, box: b } })
})
void loadChartMemory().then(({ memoryEnabled, state }) => {
  // 开关关/未加载（null）一律不套用：记忆功能只在明确开启时生效
  if (memoryEnabled !== true || !state.toggles || togglesTouched) return
  togglesApplying = true
  showSerial.value = state.toggles.serial
  showQQPlot.value = state.toggles.qq
  showBoxPlot.value = state.toggles.box
  nextTick(() => { togglesApplying = false })
})

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

// （watch(histResult) 联动已删）切参数/改敏感度时 QQ 图与序列分布各发两次
// 相同请求：useQQPlot/useSerialDistribution 内部已有同触发的 watch（参数、
// 敏感度、bin1、模式），histResult 落地后再发的那次纯属重复——三个端点都
// 是后端重计算接口（2026-09-05 审查 L1/3.8）。

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

/* 顶部控件面板：两行（控件行 + 数据口径行），嵌在 AnalysisTabLayout 的 .toolbar 框内 */
.control-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.control-panel__main {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.control-panel__main > .dp-analysis-filepicker {
  flex: 1;
  min-width: 240px;
}
.chart-toggles {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}
.control-panel__filters {
  border-top: 1px dashed var(--border-2, #e4e7ed);
  padding-top: 8px;
}

/* dock 布局接管图表区的高度/宽度/排列；这里仅保留被 slot 注入的两处样式 */

/* 序列无列等错误提示：作为 ChartPanel 网格单元，贴顶不铺满 */
.serial-error-alert {
  align-self: start;
  margin: 16px;
  height: auto;
}

/* 箱线图宿主：为加载骨架提供定位上下文，并铺满面板 */
.box-chart-host {
  position: relative;
  height: 100%;
  width: 100%;
  min-height: 0;
}
</style>
