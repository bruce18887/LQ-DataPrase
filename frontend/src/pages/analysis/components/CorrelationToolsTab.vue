<!-- frontend/src/pages/analysis/components/CorrelationToolsTab.vue -->
<template>
  <AnalysisTabLayout :loading="corrLoading || matrixLoading">
    <!-- 工具栏：文件选择（散点/矩阵 radio 已删——2026-09-07 同屏改造，两卡常驻） -->
    <template #toolbar>
      <AnalysisFilePicker
        v-model="fileId"
        :files="files"
        scope="correlation"
        :loading="listLoading"
      />
    </template>

    <!-- 左侧面板 -->
    <template #left-panel>
      <!-- 数据筛选 + 异常值处理：只动本 tab 自己那份（与单文件 tab 互不影响） -->
      <DataFilterSection
        scope="correlation"
        v-model:ignore-no-limit="ignoreNoLimit"
        v-model:ignore-no-test-value="ignoreNoTestValue"
        v-model:data-only-bin1="dataOnlyBin1"
        v-model:only-fail-test-item="onlyFailTestItem"
        v-model:only-low-cpk="onlyLowCpk"
        v-model:outlier-handling="outlierHandling"
        v-model:iqr-multiplier="iqrMultiplier"
      />

      <!-- 散点对选择（双入口之一：X/Y 下拉；另一个入口是点矩阵格） -->
      <el-card shadow="hover" :body-style="{ padding: '12px' }">
        <label class="section-label">X 轴测试项</label>
        <el-select v-model="localX" placeholder="选择 X 轴参数" filterable style="width: 100%"
          popper-class="dp-corr-x-popper">
          <el-option v-for="p in params" :key="p" :label="p" :value="p" />
        </el-select>
        <label class="section-label" style="margin-top: 10px">Y 轴测试项</label>
        <el-select v-model="localY" placeholder="选择 Y 轴参数" filterable style="width: 100%"
          popper-class="dp-corr-y-popper">
          <el-option v-for="p in params" :key="p" :label="p" :value="p" />
        </el-select>
        <div style="margin-top: 10px">
          <el-switch v-model="showRegression" size="small" active-text="显示回归线" />
        </div>
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

      <!-- 矩阵参数选择（搜索框+chips）+ 方法 + 计算按钮（按钮留左栏原位） -->
      <MatrixParamPicker :params="params" v-model:selected="selectedMatrixParams" />
      <el-card shadow="hover" :body-style="{ padding: '12px' }">
        <label class="section-label">相关系数方法</label>
        <!-- data-corr-method：e2e 契约选择器（同 data-file-picker/data-filter 惯例） -->
        <el-select v-model="method" data-corr-method style="width: 100%"
          popper-class="dp-corr-method-popper">
          <el-option label="Pearson（线性）" value="pearson" />
          <el-option label="Spearman（秩相关）" value="spearman" />
          <el-option label="Kendall（秩相关）" value="kendall" />
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

    <!-- 右侧面板：矩阵卡 + 散点卡同屏常驻（对齐原型布局） -->
    <template #right-panel>
      <!-- 矩阵卡 -->
      <div class="inline-card" data-corr-matrix-card>
        <div class="inline-card-h">
          <span>相关系数矩阵</span>
          <span class="grow"></span>
          <span v-if="matrixData" class="matrix-meta-inline">{{ matrixMeta }}</span>
        </div>
        <div class="inline-card-b">
          <div v-if="matrixData" ref="matrixChartRef" class="matrix-chart-inner" />
          <el-empty
            v-else
            description="选择参数后点击左栏「计算相关性矩阵」按钮"
            :image-size="72"
          />
        </div>
      </div>

      <!-- 散点卡：卡头一行承载 r/p/n/回归式（KPI 大卡已并入） -->
      <div class="inline-card" data-corr-scatter-card>
        <div class="inline-card-h">
          <span>散点明细<template v-if="corrResult"> · {{ corrResult.param_x }} × {{ corrResult.param_y }}</template></span>
          <span class="grow"></span>
          <template v-if="corrResult">
            <span class="head-metric" :class="rColorClass">r={{ (corrResult.pearson_r ?? 0).toFixed(4) }}<span v-if="scatterPStars" class="p-stars">{{ scatterPStars }}</span></span>
            <span class="head-metric">p={{ scatterPText }}</span>
            <span class="head-metric">n={{ (corrResult.n ?? 0).toLocaleString() }}</span>
            <span v-if="regressionInfo" class="head-metric head-eq">{{ regressionInfo.equation }}</span>
          </template>
        </div>
        <div class="inline-card-b">
          <div v-if="corrResult" ref="scatterChartRef" class="scatter-chart-inner" />
          <ErrorBanner
            v-else-if="corrError"
            :message="corrError"
            title="相关性数据加载失败"
            @retry="reloadCorrelation"
          />
          <el-empty v-else description="选择 X/Y 轴参数或点击矩阵格以分析相关性" :image-size="72" />
        </div>
        <div v-if="sampledText" class="sample-note">{{ sampledText }}</div>
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
  </AnalysisTabLayout>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { storeToRefs } from 'pinia'
import AnalysisTabLayout from './AnalysisTabLayout.vue'
import AnalysisFilePicker from './AnalysisFilePicker.vue'
import DataFilterSection from './DataFilterSection.vue'
import MatrixParamPicker from './MatrixParamPicker.vue'
import { useCorrelation } from '../composables/useCorrelation'
import { useCorrelationMatrix } from '../composables/useCorrelationMatrix'
import { useTabFileParams } from '../composables/useTabFileParams'
import { buildCorrelationMatrixOption, formatPValue, getSignificanceStars } from '../composables/matrix-option'
import { buildCorrelationScatterOption, linearRegression } from '../composables/scatter-option'
import CorrelationScatterAxisCard from './CorrelationScatterAxisCard.vue'
import ErrorBanner from '../../../components/common/ErrorBanner.vue'
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme, getChartRenderer } from '../../../utils/echarts-theme'
import { minMax } from '../../../utils/minmax'
import { getSiteColors8 } from '../../../utils/chart-bar'
import { useCorrelationTabStore } from '../../../stores/analysisTabs'
import type { DataFile } from '../../../types'
import OutlierHintBar from './OutlierHintBar.vue'

const props = defineProps<{
  /** 文件列表（页面统一拉）；本 tab 自己的选择与开关存在相关性子 store */
  files: DataFile[]
  /** 本 tab 是否处于激活态：隐藏时不重发全量计算 */
  active?: boolean
}>()

const { colors, isDark } = useEChartsTheme()

// 本 tab 的文件→参数列表 + 数据筛选/异常值（与单文件 tab 同构但完全独立）
const {
  fileId,
  params,
  loading: listLoading,
  ignoreNoLimit,
  ignoreNoTestValue,
  dataOnlyBin1,
  onlyFailTestItem,
  onlyLowCpk,
  outlierHandling,
  iqrMultiplier,
  method,
} = storeToRefs(useCorrelationTabStore())

// View mode 已删除（2026-09-07 同屏改造）：矩阵卡与散点卡常驻右栏，
// 点矩阵格就地更新下方散点，不再有视图切换

/** 散点/矩阵请求携带的筛选载荷（也是拉参数列表的同一批开关，口径不会分叉） */
const corrFlags = computed(() => ({
  ignore_no_limit: ignoreNoLimit.value,
  ignore_no_test_value: ignoreNoTestValue.value,
  data_only_bin1: dataOnlyBin1.value,
  only_fail_test_item: onlyFailTestItem.value,
  only_low_cpk: onlyLowCpk.value,
  iqr_multiplier: iqrMultiplier.value,
}))

// 本 tab 的文件→参数列表（必须排在 corrFlags 之后：watch 建立时就会读一次）
useTabFileParams({
  ctx: { fileId, params, loading: listLoading },
  files: computed(() => props.files),
  filters: () => corrFlags.value,
})

// ===== Scatter mode =====
const localX = ref('')
const localY = ref('')
const showRegression = ref(true)
const axisModeX = ref<'data' | 'sigma' | 'custom'>('data')
const axisModeY = ref<'data' | 'sigma' | 'custom'>('data')
const sigmaX = ref(3); const sigmaY = ref(3)
const customMinX = ref(0); const customMaxX = ref(0)
const customMinY = ref(0); const customMaxY = ref(0)

const { corrLoading, corrResult, corrError, loadCorrelation } = useCorrelation(() => fileId.value)

const rColorClass = computed(() => {
  const r = Math.abs(corrResult.value?.pearson_r ?? 0)
  if (r > 0.7) return 'r-strong'
  if (r > 0.4) return 'r-medium'
  return 'r-weak'
})

// 散点 p 值（后端 /analysis/correlation/ 2026-09-06 起返回；n<=2 或 σ=0 时为 null）
const scatterP = computed<number | null>(() => {
  const p = corrResult.value?.p_value
  return (p === null || p === undefined || !Number.isFinite(p)) ? null : p
})
const scatterPText = computed(() => scatterP.value === null ? '-' : formatPValue(scatterP.value))
const scatterPStars = computed(() => scatterP.value === null ? '' : getSignificanceStars(scatterP.value))

// 抽样注记：后端 n 是降采样前全量口径（correlation.py n = len(common_idx)），
// 已画点数 = 各 series data 长度和；N < M 才显示「抽样 N/M 点」
const sampledText = computed(() => {
  if (!corrResult.value) return ''
  const drawn = (corrResult.value.series_data || []).reduce(
    (sum: number, sd: { data?: unknown[] }) => sum + (sd.data?.length ?? 0), 0)
  const total = corrResult.value.n ?? 0
  return drawn < total ? `抽样 ${drawn.toLocaleString()}/${total.toLocaleString()} 点` : ''
})

// 大数据量（≥5000 点）启用 large 模式 + canvas：上万散点不再产生上万
// DOM 节点（与 SerialChart/QQPlotChart 一致）
const isLarge = computed(() => {
  const series = corrResult.value?.series_data || []
  return series.reduce((sum: number, sd: { data?: unknown[] }) =>
    sum + (sd.data?.length ?? 0), 0) >= 5000
})

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

// 筛选开关与敏感度变化 → 重发散点（X/Y 已选时）+ 矩阵参数与过滤后列表求交集
// 修剪。本 tab 隐藏时不重发（全文件重算）：记一笔欠账，切回来再补。
let reloadOwed = false
watch([ignoreNoTestValue, dataOnlyBin1, onlyFailTestItem, onlyLowCpk, ignoreNoLimit, iqrMultiplier], () => {
  // 参数列表由本 tab 的 useTabFileParams 联动刷新；本页修剪过期选中项防 400
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

// 散点 option 构建已外移 composables/scatter-option.ts（撞 600 行上限，与
// matrix-option.ts 同款处理）；此处仅把响应式状态装配进去
const { chartRef: scatterChartRef } = useChart(() => buildCorrelationScatterOption({
  result: corrResult.value,
  theme: {
    textColor: colors.value.textColor,
    axisLineColor: colors.value.axisLineColor,
    tooltipBg: colors.value.tooltipBg,
    tooltipBorder: colors.value.tooltipBorder,
    tooltipText: colors.value.tooltipText,
    regressionColor: colors.value.seriesColors[3],
    siteColors: getSiteColors8(isDark.value),
  },
  isLarge: isLarge.value,
  showRegression: showRegression.value,
  axis: {
    axisModeX: axisModeX.value, axisModeY: axisModeY.value,
    sigmaX: sigmaX.value, sigmaY: sigmaY.value,
    customMinX: customMinX.value, customMaxX: customMaxX.value,
    customMinY: customMinY.value, customMaxY: customMaxY.value,
    outlierHandling: outlierHandling.value,
  },
}), [
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
const { loading: matrixLoading, matrixData, loadCorrelationMatrix } = useCorrelationMatrix(() => fileId.value)

// 换文件后旧数据不再属于当前选择，直接清掉防止误读（对照 WaferMapPanel 的
// 同款 watch）：localX/localY 是本组件本地 ref，不随 useTabFileParams 的参数
// 列表刷新重置——不清的话散点图/Pearson r/回归方程会无限期显示上一个文件的
// 结果；新文件恰有同名参数时更是静默错误数据。矩阵数据同清，用户重选后重算。
watch(fileId, () => {
  localX.value = ''
  localY.value = ''
  corrResult.value = null
  matrixData.value = null
})

/** 矩阵参数与当前（可能已筛选收缩的）参数列表求交集——防过期项 400 */
function trimMatrixParams() {
  if (selectedMatrixParams.value.length === 0) return
  const valid = new Set(params.value)
  const kept = selectedMatrixParams.value.filter((p) => valid.has(p))
  if (kept.length !== selectedMatrixParams.value.length) {
    selectedMatrixParams.value = kept
  }
}

// Initialize matrix params when the param list changes（含筛选开关导致的列表收缩）
// 默认只取前 MATRIX_DEFAULT_MAX 项：热力图 N×N 每格带文字标签，全选 180 项
// 就是 32400 格，首屏卡数秒。需要更多用「全选」显式加压。
const MATRIX_DEFAULT_MAX = 12
watch(params, (newParams) => {
  if (newParams.length > 0 && selectedMatrixParams.value.length === 0) {
    selectedMatrixParams.value = newParams.slice(0, MATRIX_DEFAULT_MAX)
  } else {
    trimMatrixParams()
  }
}, { immediate: true })

function onCalculateMatrix() {
  if (!fileId.value) return
  loadCorrelationMatrix(
    selectedMatrixParams.value.length > 0 ? selectedMatrixParams.value : undefined,
    corrFlags.value,
    method.value,
  )
}

// 矩阵 meta 行（照原型 cMxMeta）：方法 · n · 星标口径 · 色相语义
const matrixMeta = computed(() => {
  if (!matrixData.value) return ''
  const n = matrixData.value.sample_size ?? 0
  return `${method.value} · n=${n.toLocaleString()} · 星标 <0.001 ***/<0.01 **/<0.05 * · 色相表方向，非表好坏`
})

function buildMatrixOption() {
  if (!matrixData.value) return {}
  return buildCorrelationMatrixOption(matrixData.value, {
    textColor: colors.value.textColor,
    isDark: isDark.value,
    brandColor: colors.value.brandColor,
  })
}

const { chartRef: matrixChartRef, chartInstance: matrixChartInstance } = useChart(
  buildMatrixOption, [() => matrixData.value], 'matrixChartRef')
void matrixChartRef

// 矩阵格 → 散点联动（同屏就地更新，2026-09-07）：热力图 data 项 value
// 为 [i, j, r]，对角（恒 1）与 r 无定义的格不响应；选中该对后，
// 既有 watch([localX, localY]) 自动加载，不新造请求逻辑。矩阵参数本就 ⊆
// 散点参数列表（同一 params 源），无失效对。实例可能因渲染器切换被重建，
// 故 watch chartInstance 重挂前先 off 防重复绑定。
watch(matrixChartInstance, (chart) => {
  if (!chart) return
  chart.off('click')
  chart.on('click', (p: any) => {
    if (p?.componentType !== 'series') return
    const [i, j, r] = (p.value ?? []) as [number, number, number | null]
    if (i === j || r == null) return
    const list: string[] = matrixData.value?.params || []
    const x = list[i]
    const y = list[j]
    if (!x || !y) return
    localX.value = x
    localY.value = y
  })
})
void matrixChartInstance
</script>

<style scoped>
.section-label {
  font-size: 11px;
  color: var(--text-2);
  margin-bottom: 4px;
  font-weight: 500;
  display: block;
}

/* 同屏双卡（对齐原型 .chart/.chart-h/.chart-b 结构） */
.inline-card {
  background: var(--card);
  border: 1px solid var(--border-2);
  border-radius: 6px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.inline-card-h {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  background: var(--bg-3);
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}

.inline-card-h .grow { flex: 1; }

.inline-card-b {
  padding: 6px;
  min-height: 480px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.matrix-chart-inner,
.scatter-chart-inner {
  width: 100%;
  height: 480px;
}

/* 卡头一行指标（badge/note 规格） */
.head-metric {
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-mono, monospace);
  color: var(--text);
  white-space: nowrap;
}

.head-metric.r-strong { color: var(--success); }
.head-metric.r-medium { color: var(--warn); }
.head-metric.r-weak { color: var(--text-2); }

.p-stars {
  color: var(--warn);
  font-size: 11px;
  margin-left: 1px;
}

.head-eq {
  font-weight: 500;
  color: var(--text-2);
}

.matrix-meta-inline {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sample-note {
  padding: 2px 10px 6px;
  font-size: 11px;
  color: var(--text-3);
}
</style>
