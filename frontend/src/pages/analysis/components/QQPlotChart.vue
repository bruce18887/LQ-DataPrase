<template>
  <div class="qqplot-chart">
    <!-- Loading state -->
    <div v-if="loading" class="qqplot-placeholder">
      <el-icon class="is-loading" style="font-size: 24px; margin-right: 8px;"><Loading /></el-icon>
      <span>正在计算QQ图...</span>
    </div>
    <!-- Empty / no-data state: plain div to avoid el-empty emitsOptions race -->
    <div
      v-else-if="!result || isEmptyResult"
      class="qqplot-placeholder"
      :data-testid="error ? 'chart-error' : undefined"
    >
      <el-icon class="qqplot-placeholder__icon"><InfoFilled /></el-icon>
      <span class="qqplot-placeholder__text">{{ error || (!result ? '暂无QQ图数据' : '该参数无有效数值数据') }}</span>
    </div>
    <!-- Chart container -->
    <div v-else class="qqplot-chart-inner">
      <div ref="chartRef" class="qqplot-container" role="img" aria-label="QQ 正态分布图" />
      <OutlierHintBar
        :mode="outlierHandling || 'off'"
        :outlier-info="result?.outlier_info ?? null"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Loading, InfoFilled } from '@element-plus/icons-vue'
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme, getChartRenderer } from '../../../utils/echarts-theme'
import { formatAxisValue } from '../../../utils/chart-bar'
import OutlierHintBar from './OutlierHintBar.vue'

const props = defineProps<{
  fileId: number | null
  param: string
  visible: boolean
  result: any
  loading: boolean
  /** 请求失败消息（来自 useQQPlot 的 error）：有值时占位文案直接显示它，
   *  与「该参数没有数据」的空态区分开 */
  error?: string | null
  outlierHandling?: 'clip' | 'exclude' | 'off'
}>()

const { colors, isDark } = useEChartsTheme()

const isEmptyResult = computed(() => {
  if (!props.result) return false
  const t = props.result.theoretical_quantiles
  return !t || t.length === 0
})

// 大数据量（≥5000 点，如数万行文件逐行返回分位数）启用 large 模式 + canvas：
// 上万散点不再产生上万 DOM 节点，避免拖垮渲染与交互（与 SerialChart 一致）
const pointCount = computed(() => props.result?.theoretical_quantiles?.length ?? 0)
const isLarge = computed(() => pointCount.value >= 5000)

// 图表布局常量（与下方 CSS .qqplot-container 的 height: 400px 同步）：
// Y 轴滑动块必须与 grid 同源定位——top 对齐 grid 顶，高度 = 容器高 − top − bottom，
// 否则滑块与 Y 轴长度不一致
const GRID_TOP = 50
const GRID_BOTTOM = 40
const CHART_HEIGHT = 400

function buildOption() {
  const r = props.result
  if (!r) return {}

  const theoretical: number[] = r.theoretical_quantiles || []
  const observed: number[] = r.observed_quantiles || []
  if (theoretical.length === 0) return {}

  const tc = colors.value.textColor

  // Apply outlier clipping
  const outlierInfo = r.outlier_info
  const handlingMode = props.outlierHandling || 'off'
  let filteredTheoretical = theoretical
  let filteredObserved = observed
  // 实际发生了过滤（排除/裁剪移除过点）→ Y 轴需锚定可见区间，见下方注释
  let didFilter = false

  if (handlingMode !== 'off' && outlierInfo?.has_outliers) {
    const lb = outlierInfo.lower_bound
    const ub = outlierInfo.upper_bound
    const indices = observed
      .map((v: number, i: number) => (v >= lb && v <= ub ? i : -1))
      .filter((i: number) => i >= 0)
    if (indices.length > 2) {
      filteredTheoretical = indices.map((i: number) => theoretical[i])
      filteredObserved = indices.map((i: number) => observed[i])
      didFilter = true
    }
  }

  // 单趟循环构建散点并同时求 min/max —— 不能用 Math.min(...allValues) 展开：
  // 数万行文件展开 ~13 万个参数会超出引擎调用栈上限（RangeError: Maximum
  // call stack size exceeded）
  const scatterData: number[][] = []
  let dataMin = Infinity
  let dataMax = -Infinity
  // 观测值专属 min/max：dataMin/dataMax 混入理论分位数（标准正态 ±4.5），
  // 不能直接作为观测值 Y 轴范围
  let oMin = Infinity
  let oMax = -Infinity
  for (let i = 0; i < filteredTheoretical.length; i++) {
    const t = filteredTheoretical[i]
    const o = filteredObserved[i]
    scatterData.push([t, o])
    if (t < dataMin) dataMin = t
    if (o < dataMin) dataMin = o
    if (t > dataMax) dataMax = t
    if (o > dataMax) dataMax = o
    if (o < oMin) oMin = o
    if (o > oMax) oMax = o
  }

  // 异常值排除/裁剪后，Y 轴锚定可见观测值区间：参考线端点按全量数据最小二乘
  // 拟合（y = intercept + slope·x，x 取理论分位数极值），其纵坐标远超过滤后的
  // 区间——若不 pin，轴会被参考线撑回含离群点的全范围，可见散点只占中间一条
  // 带（回归：qq-yaxis-outlier-range）。线超出轴的部分由 ECharts 裁剪，斜率/
  // 截距语义不变（与 R²/正态性徽章同属全量口径，保持一致）
  let yAxisMinMax: { min: number; max: number } | null = null
  if (didFilter) {
    const pad = (oMax - oMin) * 0.05 || 0.5 // 常量区间兜底 ±0.5
    yAxisMinMax = { min: oMin - pad, max: oMax + pad }
  }
  // 参考线 = 正态拟合线 y = intercept + slope·x（probplot 最小二乘拟合），
  // 而非 y=x——理论分位数是标准正态，只有均值 0/方差 1 的数据才贴合 y=x；
  // 真实数据须随均值/方差平移旋转（常量数据 slope/intercept 为 null → 回退 y=x）
  let diagonal: number[][] = [[dataMin, dataMin], [dataMax, dataMax]]
  const fitSlope = r.slope
  const fitIntercept = r.intercept
  if (typeof fitSlope === 'number' && typeof fitIntercept === 'number') {
    const x0 = filteredTheoretical[0]
    const x1 = filteredTheoretical[filteredTheoretical.length - 1]
    diagonal = [[x0, fitIntercept + fitSlope * x0], [x1, fitIntercept + fitSlope * x1]]
  }

  const rSquared = r.r_squared
  const isNormal = r.is_normal === true

  const graphic: any[] = []
  if (rSquared != null) {
    graphic.push({
      type: 'text', left: 10, top: 32, z: 100,
      style: {
        text: `R² = ${rSquared.toFixed(4)}`, fill: colors.value.tooltipText, fontSize: 13, fontWeight: 'bold',
        backgroundColor: colors.value.tooltipBg, padding: [4, 8], borderRadius: 4,
      },
    })
  }
  graphic.push({
    type: 'text', right: 10, top: 32, z: 100,
    style: {
      // 正态徽章：红-绿对在红绿色盲下不可分（deutan ΔE 17.5），改用语义 success/error 色；
      // night 深底用深色文字（白字对比度仅 2.5-2.7 不达标）
      text: isNormal ? '正态' : '非正态', fill: isDark.value ? '#1a1a2e' : '#ffffff', fontSize: 12, fontWeight: 'bold',
      backgroundColor: isNormal ? (isDark.value ? '#14b8a6' : '#047857') : (isDark.value ? '#fb7185' : '#b91c1c'), padding: [4, 10], borderRadius: 4,
    },
  })

  return {
    // large 模式下上万 symbol 的入场/更新动画是纯开销，直接关闭
    animation: !isLarge.value,
    title: {
      text: `${props.param} QQ图`, left: 'center', top: 6,
      textStyle: { fontSize: 15, fontWeight: 'bold', color: tc },
    },
    tooltip: {
      trigger: 'item',
      backgroundColor: colors.value.tooltipBg,
      borderColor: colors.value.tooltipBorder,
      textStyle: { color: colors.value.tooltipText },
      formatter: (p: any) =>
        `理论分位数: ${Number(p.value[0]).toFixed(4)}<br/>观测值: ${Number(p.value[1]).toFixed(4)}`,
    },
    toolbox: { feature: { saveAsImage: { name: `${props.param}_QQ图` } } },
    // grid.right 预留右侧 Y 轴滑动块空间（宽 30 + 边距）
    grid: { top: GRID_TOP, bottom: GRID_BOTTOM, left: 55, right: 40 },
    // Y 轴数据缩放（滑块 + 滚轮）：观测值区间局部放大，定位离群点/区间
    // 形态；双主题：filler/手柄跟随主题主色（亮=蓝 #2563eb、暗=金 #fdd835）；
    // 滑块与 grid 同源定位——top 对齐、高度 = 容器高 − top − bottom
    dataZoom: [
      {
        type: 'slider',
        yAxisIndex: 0,
        right: 4,
        top: GRID_TOP,
        height: CHART_HEIGHT - GRID_TOP - GRID_BOTTOM,
        backgroundColor: 'transparent',
        borderColor: colors.value.axisLineColor,
        fillerColor: `${colors.value.seriesColors[0]}26`,
        handleStyle: { color: colors.value.seriesColors[0], borderColor: 'transparent' },
        moveHandleStyle: { color: colors.value.seriesColors[0] },
        textStyle: { color: colors.value.subtextColor, fontSize: 10 },
      },
      { type: 'inside', yAxisIndex: 0 },
    ],
    xAxis: {
      type: 'value', name: '理论分位数', nameLocation: 'middle', nameGap: 30,
      nameTextStyle: { color: tc },
      axisLine: { lineStyle: { color: colors.value.axisLineColor } },
      axisLabel: { fontSize: 9, formatter: formatAxisValue, color: tc },
    },
    yAxis: {
      type: 'value', name: '观测值', nameLocation: 'middle', nameGap: 45,
      nameTextStyle: { color: tc },
      axisLine: { lineStyle: { color: colors.value.axisLineColor } },
      axisLabel: { fontSize: 9, formatter: formatAxisValue, color: tc },
      ...(yAxisMinMax ?? {}),
    },
    graphic,
    series: [
      {
        name: '数据点', type: 'scatter', data: scatterData, symbolSize: 5,
        itemStyle: { color: '#1E88E5' },
        ...(isLarge.value ? { large: true } : {}),
      },
      { name: 'y=x参考线', type: 'line', data: diagonal, lineStyle: { color: '#9E9E9E', type: 'dashed', width: 2 }, symbol: 'none', silent: true },
    ],
  }
}

// 大数据量强制 canvas（SVG 渲染器对 large 符号仍会为每点发射 DOM 元素；
// canvas 无 DOM 节点，官方推荐大数据散点必用 canvas）；小数据量跟随用户全局设置
const { chartRef } = useChart(
  buildOption,
  [() => props.result, () => props.visible, () => props.outlierHandling],
  'chartRef',
  () => (isLarge.value ? 'canvas' : getChartRenderer()),
)
void chartRef // bound to <div ref="chartRef"> in template
</script>

<style scoped>
.qqplot-chart {
  width: 100%;
  height: 100%;
  min-height: 400px;
  position: relative;
}

.qqplot-chart-inner {
  display: flex;
  flex-direction: column;
}

.qqplot-container {
  width: 100%;
  height: 400px;
}

.qqplot-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 400px;
  background: var(--bg-2);
  border-radius: 6px;
  border: 1px solid var(--border-2);
  color: var(--text-2);
  font-size: 14px;
  gap: 8px;
}
.qqplot-placeholder__icon {
  font-size: 18px;
  color: var(--text-2);
}
.qqplot-placeholder__text {
  color: var(--text-2);
}
</style>
