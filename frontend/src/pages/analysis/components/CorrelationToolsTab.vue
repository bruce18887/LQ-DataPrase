<!-- frontend/src/pages/analysis/components/CorrelationToolsTab.vue -->
<template>
  <AnalysisTabLayout :loading="corrLoading || matrixLoading">
    <!-- 工具栏 -->
    <template #toolbar>
      <el-radio-group v-model="viewMode" size="small">
        <el-radio-button value="scatter">散点图</el-radio-button>
        <el-radio-button value="matrix">相关性矩阵</el-radio-button>
      </el-radio-group>
      <el-switch v-model="ignoreNoLimit" size="small" active-text="Ignore No Limit" style="margin-left: 12px" />
    </template>

    <!-- 左侧面板 -->
    <template #left-panel>
      <!-- 数据筛选（与单文件 5 开关同口径，2026-08-20）：散点/矩阵两种模式共享。
           切换后参数列表由 AnalysisPage 的 store watch 自动刷新，请求携带全部开关 -->
      <el-card shadow="hover" :body-style="{ padding: '12px' }">
        <label class="section-label">数据筛选</label>
        <div class="corr-filter-box">
          <el-checkbox v-model="ignoreNoLimit" size="small">忽略无Limit</el-checkbox>
          <el-checkbox v-model="ignoreNoTestValue" size="small">忽略无测试值</el-checkbox>
          <el-checkbox v-model="dataOnlyBin1" size="small">仅用Pass数据(Bin1)</el-checkbox>
          <el-checkbox v-model="onlyFailTestItem" size="small">仅显示Fail测试项</el-checkbox>
          <el-checkbox v-model="onlyLowCpk" size="small">仅显示低CPK项</el-checkbox>
        </div>
      </el-card>

      <!-- 散点图模式 -->
      <template v-if="viewMode === 'scatter'">
        <el-card shadow="hover" :body-style="{ padding: '12px' }">
          <label class="section-label">X 轴测试项</label>
          <el-select v-model="localX" placeholder="选择 X 轴参数" filterable style="width: 100%">
            <el-option v-for="p in params" :key="p" :label="p" :value="p" />
          </el-select>
        </el-card>
        <el-card shadow="hover" :body-style="{ padding: '12px' }">
          <label class="section-label">Y 轴测试项</label>
          <el-select v-model="localY" placeholder="选择 Y 轴参数" filterable style="width: 100%">
            <el-option v-for="p in params" :key="p" :label="p" :value="p" />
          </el-select>
        </el-card>
        <el-card shadow="hover" :body-style="{ padding: '12px' }">
          <el-switch v-model="showRegression" size="small" active-text="显示回归线" />
        </el-card>

        <!-- 坐标轴范围设置 -->
        <CorrelationScatterAxisCard
          :show="!!corrResult"
          v-model:axis-mode-x="axisModeX"
          v-model:axis-mode-y="axisModeY"
          v-model:sigma-x="sigmaX"
          v-model:sigma-y="sigmaY"
          v-model:custom-min-x="customMinX"
          v-model:custom-min-y="customMinY"
          v-model:custom-max-x="customMaxX"
          v-model:custom-max-y="customMaxY"
        />
      </template>

      <!-- 矩阵模式 -->
      <template v-if="viewMode === 'matrix'">
        <el-card shadow="hover" :body-style="{ padding: '12px' }">
          <div class="matrix-param-header">
            <label class="section-label">选择参数（已选 {{ selectedMatrixParams.length }}/{{ params.length }}）</label>
            <div class="matrix-param-actions">
              <el-button link type="primary" size="small" @click="selectedMatrixParams = [...params]">全选</el-button>
              <el-button link type="primary" size="small" @click="selectedMatrixParams = []">清空</el-button>
            </div>
          </div>
          <el-select
            v-model="selectedMatrixParams"
            multiple
            filterable
            placeholder="选择参数"
            style="width: 100%"
          >
            <el-option v-for="p in params" :key="p" :label="p" :value="p" />
          </el-select>
        </el-card>
        <el-button
          type="primary"
          size="small"
          :loading="matrixLoading"
          :disabled="selectedMatrixParams.length < 2"
          style="width: 100%"
          @click="onCalculateMatrix"
        >
          计算相关性矩阵（{{ selectedMatrixParams.length }} 项）
        </el-button>
      </template>

    </template>

    <!-- 右侧面板 -->
    <template #right-panel>
      <!-- 散点图模式 -->
      <template v-if="viewMode === 'scatter'">
        <div v-if="corrResult" class="top-bar">
          <div class="metric-card">
            <div class="metric-label">Pearson r</div>
            <div class="metric-value" :class="rColorClass">{{ (corrResult?.pearson_r ?? 0).toFixed(4) }}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">R²</div>
            <div class="metric-value">{{ ((corrResult?.pearson_r ?? 0) ** 2).toFixed(4) }}</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">数据点数</div>
            <div class="metric-value">{{ (corrResult?.n ?? 0).toLocaleString() }}</div>
          </div>
          <div v-if="regressionInfo" class="metric-card">
            <div class="metric-label">回归方程</div>
            <div class="metric-value regression-eq">{{ regressionInfo.equation }}</div>
          </div>
        </div>
        <div class="chart-wrapper">
          <div v-if="corrResult" ref="scatterChartRef" class="chart-inner" />
          <ErrorBanner
            v-else-if="corrError"
            :message="corrError"
            title="相关性数据加载失败"
            @retry="reloadCorrelation"
          />
          <el-empty v-else-if="!corrResult" description="选择 X/Y 轴参数以分析相关性" />
        </div>
          <OutlierHintBar
            v-if="corrResult"
            :mode="outlierHandling"
            :outlier-info="corrResult?.x_outlier_info ?? null"
          />
          <OutlierHintBar
            v-if="corrResult"
            :mode="outlierHandling"
            :outlier-info="corrResult?.y_outlier_info ?? null"
          />
      </template>

      <!-- 矩阵模式 -->
      <template v-if="viewMode === 'matrix'">
        <div class="chart-wrapper">
          <div v-if="matrixData" ref="matrixChartRef" class="chart-inner" />
          <el-empty v-else description="选择参数后点击「计算相关性矩阵」按钮" />
        </div>
      </template>

    </template>
  </AnalysisTabLayout>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import AnalysisTabLayout from './AnalysisTabLayout.vue'
import { useCorrelation } from '../composables/useCorrelation'
import { useCorrelationMatrix } from '../composables/useCorrelationMatrix'
import { buildCorrelationMatrixOption } from '../composables/matrix-option'
import CorrelationScatterAxisCard from './CorrelationScatterAxisCard.vue'
import ErrorBanner from '../../../components/common/ErrorBanner.vue'
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme, getChartRenderer } from '../../../utils/echarts-theme'
import { minMax } from '../../../utils/minmax'
import { formatAxisValue, getSiteColors8 } from '../../../utils/chart-bar'
import { useAnalysisStore } from '../../../stores/analysis'
import OutlierHintBar from './OutlierHintBar.vue'

const props = defineProps<{
  fileId: number | null
  params: string[]
  /** 本 tab 是否处于激活态（AnalysisPage 传入）：隐藏时不重发全量计算 */
  active?: boolean
}>()

const analysisStore = useAnalysisStore()
const { colors, isDark } = useEChartsTheme()

// View mode
const viewMode = ref<'scatter' | 'matrix'>('scatter')
const ignoreNoLimit = ref(analysisStore.ignoreNoLimit)
watch(ignoreNoLimit, (val) => { analysisStore.ignoreNoLimit = val })
// 数据筛选开关（与单文件 store 5 开关同源：AnalysisPage 的 watch 会联动
// 刷新参数列表；本页 watch 只负责重发散点/矩阵请求）
const ignoreNoTestValue = ref(analysisStore.ignoreNoTestValue)
const dataOnlyBin1 = ref(analysisStore.dataOnlyBin1)
const onlyFailTestItem = ref(analysisStore.onlyFailTestItem)
const onlyLowCpk = ref(analysisStore.onlyLowCpk)
for (const [local, key] of [
  [ignoreNoTestValue, 'ignoreNoTestValue'],
  [dataOnlyBin1, 'dataOnlyBin1'],
  [onlyFailTestItem, 'onlyFailTestItem'],
  [onlyLowCpk, 'onlyLowCpk'],
] as const) {
  watch(local, (val) => { (analysisStore as any)[key] = val })
  watch(() => (analysisStore as any)[key], (val) => { local.value = val })
}

/** 散点/矩阵请求携带的筛选载荷 */
const corrFlags = computed(() => ({
  ignore_no_limit: ignoreNoLimit.value,
  ignore_no_test_value: ignoreNoTestValue.value,
  data_only_bin1: dataOnlyBin1.value,
  only_fail_test_item: onlyFailTestItem.value,
  only_low_cpk: onlyLowCpk.value,
  iqr_multiplier: analysisStore.iqrMultiplier,
}))

const outlierHandling = ref(analysisStore.outlierHandling)
watch(outlierHandling, (val) => { analysisStore.outlierHandling = val })
watch(() => analysisStore.outlierHandling, (val) => { outlierHandling.value = val })

// ===== Scatter mode =====
const localX = ref('')
const localY = ref('')
const showRegression = ref(true)
const axisModeX = ref<'data' | 'sigma' | 'custom'>('data')
const axisModeY = ref<'data' | 'sigma' | 'custom'>('data')
const sigmaX = ref(3); const sigmaY = ref(3)
const customMinX = ref(0); const customMaxX = ref(0)
const customMinY = ref(0); const customMaxY = ref(0)

const { corrLoading, corrResult, corrError, loadCorrelation } = useCorrelation(() => props.fileId)

const rColorClass = computed(() => {
  const r = Math.abs(corrResult.value?.pearson_r ?? 0)
  if (r > 0.7) return 'r-strong'
  if (r > 0.4) return 'r-medium'
  return 'r-weak'
})

// 大数据量（≥5000 点）启用 large 模式 + canvas：上万散点不再产生上万
// DOM 节点（与 SerialChart/QQPlotChart 一致）
const isLarge = computed(() => {
  const series = corrResult.value?.series_data || []
  return series.reduce((sum: number, sd: { data?: unknown[] }) =>
    sum + (sd.data?.length ?? 0), 0) >= 5000
})

/** 线性回归计算 */
function linearRegression(points: number[][]): { slope: number; intercept: number } {
  const n = points.length
  if (n < 2) return { slope: 0, intercept: 0 }
  let sumX = 0, sumY = 0, sumXY = 0, sumX2 = 0
  for (const [x, y] of points) {
    sumX += x; sumY += y; sumXY += x * y; sumX2 += x * x
  }
  const denom = n * sumX2 - sumX * sumX
  if (Math.abs(denom) < 1e-12) return { slope: 0, intercept: sumY / n }
  const slope = (n * sumXY - sumX * sumY) / denom
  const intercept = (sumY - slope * sumX) / n
  return { slope, intercept }
}

/** 回归信息（方程 + R²） */
const regressionInfo = computed(() => {
  if (!corrResult.value) return null
  const d = corrResult.value
  const allPts: number[][] = []
  for (const sd of d.series_data || []) for (const pt of sd.data || []) allPts.push(pt)
  if (allPts.length < 2) return null
  const { slope, intercept } = linearRegression(allPts)
  const sign = intercept >= 0 ? '+' : '-'
  return {
    slope,
    intercept,
    equation: `y=${slope.toFixed(4)}x${sign}${Math.abs(intercept).toFixed(4)}`,
  }
})

// Auto-load scatter when both X and Y are selected
watch([localX, localY], ([x, y]) => {
  if (x && y) loadCorrelation(x, y, corrFlags.value)
})

/** 重试当前 X/Y 组合（ErrorBanner @retry 复用既有加载函数，不新造请求逻辑） */
function reloadCorrelation() {
  if (localX.value && localY.value) loadCorrelation(localX.value, localY.value, corrFlags.value)
}

// 筛选开关变化 → 重发散点（X/Y 已选时）+ 矩阵参数与过滤后列表求交集修剪
// 本 tab 隐藏时不重发（全文件重算）：记一笔欠账，切回来再补
let reloadOwed = false
watch([ignoreNoTestValue, dataOnlyBin1, onlyFailTestItem, onlyLowCpk, ignoreNoLimit], () => {
  // props.params 由 AnalysisPage 联动刷新；本页修剪过期选中项防 400
  if (props.active === false) {
    reloadOwed = true
    trimMatrixParams()
    return
  }
  if (localX.value && localY.value) loadCorrelation(localX.value, localY.value, corrFlags.value)
  trimMatrixParams()
})

watch(() => props.active, (val) => {
  if (val && reloadOwed) {
    reloadOwed = false
    reloadCorrelation()
  }
})

function computeRange(mode: string, sigma: number, cMin: number, cMax: number, vals: number[]) {
  if (mode === 'custom') return { min: cMin, max: cMax }
  if (mode === 'sigma') {
    const m = vals.reduce((a, b) => a + b, 0) / vals.length
    const s = Math.sqrt(vals.reduce((sum, v) => sum + (v - m) ** 2, 0) / vals.length)
    return { min: m - sigma * s, max: m + sigma * s }
  }
  const [dMin, dMax] = minMax(vals)
  const rng = dMax > dMin ? dMax - dMin : 1
  return { min: dMin - rng / 2, max: dMax + rng / 2 }
}

function buildScatterOption() {
  if (!corrResult.value) return {}
  const tc = colors.value.textColor
  const d = corrResult.value
  const series: any[] = (d.series_data || []).map(
    (sd: { name: string; data: number[][] }, idx: number) => ({
      name: sd.name, type: 'scatter', data: sd.data, symbolSize: 6,
      itemStyle: { color: getSiteColors8(isDark.value)[idx % 8], opacity: 0.6 },
      ...(isLarge.value ? { large: true } : {}),
    }),
  )
  const allX: number[] = [], allY: number[] = []
  for (const sd of d.series_data || []) for (const pt of sd.data || []) { allX.push(pt[0]); allY.push(pt[1]) }
  const xR = allX.length > 0 ? computeRange(axisModeX.value, sigmaX.value, customMinX.value, customMaxX.value, allX) : { min: undefined, max: undefined }
  const yR = allY.length > 0 ? computeRange(axisModeY.value, sigmaY.value, customMinY.value, customMaxY.value, allY) : { min: undefined, max: undefined }

  // Apply outlier clipping to axis ranges
  if (outlierHandling.value === 'clip') {
    if (d.x_outlier_info?.has_outliers) {
      if (axisModeX.value === 'data') {
        xR.min = d.x_outlier_info.lower_bound
        xR.max = d.x_outlier_info.upper_bound
      }
    }
    if (d.y_outlier_info?.has_outliers) {
      if (axisModeY.value === 'data') {
        yR.min = d.y_outlier_info.lower_bound
        yR.max = d.y_outlier_info.upper_bound
      }
    }
  }

  // Regression line
  if (showRegression.value && allX.length >= 2) {
    const { slope, intercept } = linearRegression(allX.map((x, i) => [x, allY[i]]))
    const [xAllMin, xAllMax] = minMax(allX)
    const xMin = xR.min ?? xAllMin
    const xMax = xR.max ?? xAllMax
    const r2 = (d.pearson_r ?? 0) ** 2
    series.push({
      name: '回归线',
      type: 'line',
      data: [[xMin, slope * xMin + intercept], [xMax, slope * xMax + intercept]],
      // itemStyle.color 与 lineStyle 同源——图例 marker 只取 itemStyle（2026-08-20）
      itemStyle: { color: colors.value.seriesColors[3] },
      lineStyle: { type: 'dashed', color: colors.value.seriesColors[3], width: 2 },
      symbol: 'none',
      tooltip: {
        formatter: () => `回归方程: y = ${slope.toFixed(4)}x + ${intercept.toFixed(4)}<br/>R² = ${r2.toFixed(4)}`,
      },
    })
  }

  return {
    // large 模式下上万 symbol 的入场/更新动画是纯开销，直接关闭
    animation: !isLarge.value,
    title: { text: `${d.param_x} vs ${d.param_y}`, subtext: `Pearson r = ${d.pearson_r?.toFixed(4) ?? '-'}`, left: 'center', textStyle: { color: tc, fontSize: 15 }, subtextStyle: { color: tc, fontSize: 12 } },
    toolbox: { feature: { saveAsImage: { title: '保存图片' }, restore: { title: '还原' } }, right: 10 },
    tooltip: { trigger: 'item', backgroundColor: colors.value.tooltipBg, borderColor: colors.value.tooltipBorder, textStyle: { color: colors.value.tooltipText }, formatter: (p: any) => `${p.seriesName}<br/>${d.param_x}: ${Number(p.value[0]).toFixed(4)}<br/>${d.param_y}: ${Number(p.value[1]).toFixed(4)}` },
    legend: { data: series.map((s: any) => s.name), bottom: 5, type: 'scroll', textStyle: { color: tc } },
    xAxis: { type: 'value', name: d.param_x, nameLocation: 'center', nameGap: 30, min: xR.min, max: xR.max, axisLine: { lineStyle: { color: colors.value.axisLineColor } }, axisLabel: { fontSize: 9, formatter: formatAxisValue, color: tc }, nameTextStyle: { color: tc } },
    yAxis: { type: 'value', name: d.param_y, nameLocation: 'center', nameGap: 40, min: yR.min, max: yR.max, axisLine: { lineStyle: { color: colors.value.axisLineColor } }, axisLabel: { fontSize: 9, formatter: formatAxisValue, color: tc }, nameTextStyle: { color: tc } },
    dataZoom: [
      { type: 'slider', xAxisIndex: 0, start: 0, end: 100 },
      { type: 'slider', yAxisIndex: 0, start: 0, end: 100 },
      { type: 'inside', xAxisIndex: 0 },
      { type: 'inside', yAxisIndex: 0 },
    ],
    series,
  }
}

// 大数据量强制 canvas（SVG 渲染器对 large 符号仍会为每点发射 DOM 元素）；
// 小数据量跟随用户全局设置
const { chartRef: scatterChartRef } = useChart(buildScatterOption, [
  () => corrResult.value,
  () => showRegression.value,
  () => axisModeX.value, () => axisModeY.value,
  () => sigmaX.value, () => sigmaY.value,
  () => customMinX.value, () => customMaxX.value,
  () => customMinY.value, () => customMaxY.value,
  () => outlierHandling.value,
], 'scatterChartRef', () => (isLarge.value ? 'canvas' : getChartRenderer()))
void scatterChartRef

watch(() => corrResult.value, (data) => {
  if (!data) return
  const allX: number[] = [], allY: number[] = []
  for (const sd of data.series_data || []) for (const pt of sd.data || []) { allX.push(pt[0]); allY.push(pt[1]) }
  const r4 = (v: number) => Math.round(v * 1e4) / 1e4
  if (allX.length > 0) { const [mn, mx] = minMax(allX); customMinX.value = r4(mn); customMaxX.value = r4(mx) }
  if (allY.length > 0) { const [mn, mx] = minMax(allY); customMinY.value = r4(mn); customMaxY.value = r4(mx) }
})

// ===== Matrix mode =====
const selectedMatrixParams = ref<string[]>([])
const { loading: matrixLoading, matrixData, loadCorrelationMatrix } = useCorrelationMatrix(() => props.fileId)

/** 矩阵参数与当前（可能已筛选收缩的）参数列表求交集——防过期项 400 */
function trimMatrixParams() {
  if (selectedMatrixParams.value.length === 0) return
  const valid = new Set(props.params)
  const kept = selectedMatrixParams.value.filter((p) => valid.has(p))
  if (kept.length !== selectedMatrixParams.value.length) {
    selectedMatrixParams.value = kept
  }
}

// Initialize matrix params when props.params changes（含筛选开关导致的列表收缩）
// 默认只取前 MATRIX_DEFAULT_MAX 项：热力图 N×N 每格带文字标签，全选 180 项
// 就是 32400 格，首屏卡数秒。需要更多用「全选」显式加压。
const MATRIX_DEFAULT_MAX = 12
watch(() => props.params, (newParams) => {
  if (newParams.length > 0 && selectedMatrixParams.value.length === 0) {
    selectedMatrixParams.value = newParams.slice(0, MATRIX_DEFAULT_MAX)
  } else {
    trimMatrixParams()
  }
}, { immediate: true })

function onCalculateMatrix() {
  if (!props.fileId) return
  loadCorrelationMatrix(
    selectedMatrixParams.value.length > 0 ? selectedMatrixParams.value : undefined,
    corrFlags.value,
  )
}

function buildMatrixOption() {
  if (!matrixData.value) return {}
  return buildCorrelationMatrixOption(matrixData.value, {
    textColor: colors.value.textColor,
    isDark: isDark.value,
  })
}

const { chartRef: matrixChartRef } = useChart(buildMatrixOption, [() => matrixData.value], 'matrixChartRef')
void matrixChartRef
</script>

<style scoped>
.section-label {
  font-size: 11px;
  color: var(--text-2);
  margin-bottom: 4px;
  font-weight: 500;
  display: block;
}

.hint-text {
  font-size: 13px;
  color: var(--text-2);
  margin: 0;
}

.top-bar {
  display: flex;
  gap: 12px;
}

.metric-card {
  background: var(--bg-3, #f5f7fa);
  border-radius: 8px;
  padding: 12px 16px;
  text-align: center;
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}

.metric-label {
  font-size: 12px;
  color: var(--text-2, #909399);
  margin-bottom: 4px;
}

.metric-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text, #303133);
}

.metric-value.r-strong { color: var(--success); }
.metric-value.r-medium { color: var(--warn); }
.metric-value.r-weak { color: var(--text, #303133); }

.regression-eq {
  font-size: 13px;
  font-weight: 600;
  word-break: break-all;
}

.chart-wrapper {
  flex: 1;
  min-height: 480px;
  background: var(--bg-2, #fff);
  border-radius: 6px;
  border: 1px solid var(--border-2, #e4e7ed);
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.chart-inner {
  width: 100%;
  height: 100%;
  min-height: 480px;
}

.matrix-param-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.matrix-param-header .section-label {
  margin-bottom: 0;
}

.corr-filter-box {
  display: flex;
  flex-wrap: wrap;
  gap: 0 12px;
}

.corr-filter-box :deep(.el-checkbox) {
  margin-right: 0;
  height: 24px;
}

.corr-filter-box :deep(.el-checkbox__label) {
  font-size: 12px;
  padding-left: 4px;
}

.matrix-param-actions {
  display: flex;
  gap: 4px;
}
</style>
