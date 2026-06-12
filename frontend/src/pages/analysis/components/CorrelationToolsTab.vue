<!-- frontend/src/pages/analysis/components/CorrelationToolsTab.vue -->
<template>
  <AnalysisTabLayout :loading="corrLoading || matrixLoading">
    <!-- 工具栏 -->
    <template #toolbar>
      <el-radio-group v-model="viewMode" size="small">
        <el-radio-button value="scatter">散点图</el-radio-button>
        <el-radio-button value="matrix">相关性矩阵</el-radio-button>
      </el-radio-group>
      <el-button
        v-if="viewMode === 'scatter'"
        type="primary"
        size="small"
        :loading="corrLoading"
        :disabled="!localX || !localY"
        @click="onAnalyze"
      >
        分析相关性
      </el-button>
      <el-button
        v-if="viewMode === 'matrix'"
        type="primary"
        size="small"
        :loading="matrixLoading"
        @click="onCalculateMatrix"
      >
        计算相关性矩阵
      </el-button>
    </template>

    <!-- 左侧面板 -->
    <template #left-panel>
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

        <!-- 坐标轴范围设置 -->
        <el-card v-if="corrResult" shadow="hover" :body-style="{ padding: '12px' }">
          <el-collapse v-model="axisCollapse" style="border: none">
            <el-collapse-item title="坐标轴范围设置" name="axis">
              <div class="axis-body">
                <div class="axis-item">
                  <label class="axis-label">X轴</label>
                  <el-select v-model="axisModeX" size="small" style="width: 95px">
                    <el-option label="数据分布" value="data" />
                    <el-option label="西格玛" value="sigma" />
                    <el-option label="自定义" value="custom" />
                  </el-select>
                  <el-select v-if="axisModeX === 'sigma'" v-model="sigmaX" size="small" style="width: 65px; margin-left: 6px">
                    <el-option :value="3" label="3σ" /><el-option :value="4" label="4σ" /><el-option :value="6" label="6σ" />
                  </el-select>
                  <template v-if="axisModeX === 'custom'">
                    <el-input-number v-model="customMinX" size="small" :precision="4" :controls="false" style="width: 100px; margin-left: 6px" placeholder="最小值" />
                    <span style="margin: 0 3px">~</span>
                    <el-input-number v-model="customMaxX" size="small" :precision="4" :controls="false" style="width: 100px" placeholder="最大值" />
                  </template>
                </div>
                <div class="axis-item">
                  <label class="axis-label">Y轴</label>
                  <el-select v-model="axisModeY" size="small" style="width: 95px">
                    <el-option label="数据分布" value="data" />
                    <el-option label="西格玛" value="sigma" />
                    <el-option label="自定义" value="custom" />
                  </el-select>
                  <el-select v-if="axisModeY === 'sigma'" v-model="sigmaY" size="small" style="width: 65px; margin-left: 6px">
                    <el-option :value="3" label="3σ" /><el-option :value="4" label="4σ" /><el-option :value="6" label="6σ" />
                  </el-select>
                  <template v-if="axisModeY === 'custom'">
                    <el-input-number v-model="customMinY" size="small" :precision="4" :controls="false" style="width: 100px; margin-left: 6px" placeholder="最小值" />
                    <span style="margin: 0 3px">~</span>
                    <el-input-number v-model="customMaxY" size="small" :precision="4" :controls="false" style="width: 100px" placeholder="最大值" />
                  </template>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </el-card>
      </template>

      <!-- 矩阵模式 -->
      <template v-if="viewMode === 'matrix'">
        <el-card shadow="hover" :body-style="{ padding: '12px' }">
          <p class="hint-text">计算所有含 Limit 测试项的 Pearson 相关系数矩阵</p>
        </el-card>
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
            <div class="metric-label">数据点数</div>
            <div class="metric-value">{{ (corrResult?.n ?? 0).toLocaleString() }}</div>
          </div>
        </div>
        <div class="chart-wrapper">
          <div v-if="corrResult" ref="scatterChartRef" class="chart-inner" />
          <el-empty v-else description="选择 X/Y 轴参数后点击分析相关性" />
        </div>
      </template>

      <!-- 矩阵模式 -->
      <template v-if="viewMode === 'matrix'">
        <div class="chart-wrapper">
          <div v-if="matrixData" ref="matrixChartRef" class="chart-inner" />
          <el-empty v-else description="点击按钮计算所有有 Limit 测试项的 Pearson 相关系数矩阵" />
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
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'

const props = defineProps<{
  fileId: number | null
  params: string[]
}>()

const { colors } = useEChartsTheme()

// View mode
const viewMode = ref<'scatter' | 'matrix'>('scatter')

// ===== Scatter mode =====
const localX = ref('')
const localY = ref('')
const axisCollapse = ref<string[]>([])
const axisModeX = ref<'data' | 'sigma' | 'custom'>('data')
const axisModeY = ref<'data' | 'sigma' | 'custom'>('data')
const sigmaX = ref(3); const sigmaY = ref(3)
const customMinX = ref(0); const customMaxX = ref(0)
const customMinY = ref(0); const customMaxY = ref(0)

const { corrLoading, corrResult, loadCorrelation } = useCorrelation(() => props.fileId)

const SITE_COLORS = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#5383e0']

const rColorClass = computed(() => {
  const r = Math.abs(corrResult.value?.pearson_r ?? 0)
  if (r > 0.7) return 'r-strong'
  if (r > 0.4) return 'r-medium'
  return 'r-weak'
})

function onAnalyze() {
  if (localX.value && localY.value) loadCorrelation(localX.value, localY.value)
}

function computeRange(mode: string, sigma: number, cMin: number, cMax: number, vals: number[]) {
  if (mode === 'custom') return { min: cMin, max: cMax }
  if (mode === 'sigma') {
    const m = vals.reduce((a, b) => a + b, 0) / vals.length
    const s = Math.sqrt(vals.reduce((sum, v) => sum + (v - m) ** 2, 0) / vals.length)
    return { min: m - sigma * s, max: m + sigma * s }
  }
  const dMin = Math.min(...vals), dMax = Math.max(...vals)
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
      itemStyle: { color: SITE_COLORS[idx % SITE_COLORS.length], opacity: 0.6 },
    }),
  )
  const allX: number[] = [], allY: number[] = []
  for (const sd of d.series_data || []) for (const pt of sd.data || []) { allX.push(pt[0]); allY.push(pt[1]) }
  const xR = allX.length > 0 ? computeRange(axisModeX.value, sigmaX.value, customMinX.value, customMaxX.value, allX) : { min: undefined, max: undefined }
  const yR = allY.length > 0 ? computeRange(axisModeY.value, sigmaY.value, customMinY.value, customMaxY.value, allY) : { min: undefined, max: undefined }

  return {
    title: { text: `${d.param_x} vs ${d.param_y}`, subtext: `Pearson r = ${d.pearson_r?.toFixed(4) ?? '-'}`, left: 'center', textStyle: { color: tc, fontSize: 14 }, subtextStyle: { color: tc, fontSize: 12 } },
    toolbox: { feature: { saveAsImage: { title: '保存图片' }, restore: { title: '还原' } }, right: 10 },
    tooltip: { trigger: 'item', formatter: (p: any) => `${p.seriesName}<br/>${d.param_x}: ${Number(p.value[0]).toFixed(4)}<br/>${d.param_y}: ${Number(p.value[1]).toFixed(4)}` },
    legend: { data: series.map((s: any) => s.name), bottom: 5, type: 'scroll', textStyle: { color: tc } },
    xAxis: { type: 'value', name: d.param_x, nameLocation: 'center', nameGap: 30, min: xR.min, max: xR.max, axisLabel: { color: tc }, nameTextStyle: { color: tc } },
    yAxis: { type: 'value', name: d.param_y, nameLocation: 'center', nameGap: 40, min: yR.min, max: yR.max, axisLabel: { color: tc }, nameTextStyle: { color: tc } },
    dataZoom: [
      { type: 'slider', xAxisIndex: 0, start: 0, end: 100 },
      { type: 'slider', yAxisIndex: 0, start: 0, end: 100 },
      { type: 'inside', xAxisIndex: 0 },
      { type: 'inside', yAxisIndex: 0 },
    ],
    series,
  }
}

const { chartRef: scatterChartRef } = useChart(buildScatterOption, [
  () => corrResult.value,
  () => axisModeX.value, () => axisModeY.value,
  () => sigmaX.value, () => sigmaY.value,
  () => customMinX.value, () => customMaxX.value,
  () => customMinY.value, () => customMaxY.value,
])

watch(() => corrResult.value, (data) => {
  if (!data) return
  const allX: number[] = [], allY: number[] = []
  for (const sd of data.series_data || []) for (const pt of sd.data || []) { allX.push(pt[0]); allY.push(pt[1]) }
  const r4 = (v: number) => Math.round(v * 1e4) / 1e4
  if (allX.length > 0) { customMinX.value = r4(Math.min(...allX)); customMaxX.value = r4(Math.max(...allX)) }
  if (allY.length > 0) { customMinY.value = r4(Math.min(...allY)); customMaxY.value = r4(Math.max(...allY)) }
})

// ===== Matrix mode =====
const { loading: matrixLoading, matrixData, loadCorrelationMatrix } = useCorrelationMatrix(() => props.fileId)

function onCalculateMatrix() {
  loadCorrelationMatrix()
}

function buildMatrixOption() {
  if (!matrixData.value) return {}
  const tc = colors.value.textColor
  const data = matrixData.value
  const params: string[] = data.params || []
  const matrix: number[][] = data.matrix || []

  const heatmapData: [number, number, number][] = []
  for (let i = 0; i < params.length; i++) {
    for (let j = 0; j < params.length; j++) {
      heatmapData.push([i, j, matrix[i]?.[j] ?? 0])
    }
  }

  return {
    tooltip: {
      position: 'top',
      formatter: (p: any) => `${params[p.value[0]]} vs ${params[p.value[1]]}<br/>Pearson r: ${p.value[2].toFixed(4)}`,
    },
    grid: { left: '15%', right: '10%', top: '10%', bottom: '15%' },
    xAxis: { type: 'category', data: params, splitArea: { show: true }, axisLabel: { rotate: 45, fontSize: 10, color: tc } },
    yAxis: { type: 'category', data: params, splitArea: { show: true }, axisLabel: { fontSize: 10, color: tc } },
    visualMap: {
      min: -1, max: 1, calculable: true, orient: 'horizontal', left: 'center', bottom: '0%',
      inRange: { color: ['#d73027', '#f46d43', '#fdae61', '#fee08b', '#e6f598', '#abdda4', '#66c2a5', '#3288bd'] },
    },
    series: [{
      name: 'Pearson r', type: 'heatmap', data: heatmapData,
      label: { show: true, fontSize: 9, formatter: (p: any) => p.value[2].toFixed(2) },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.5)' } },
    }],
  }
}

const { chartRef: matrixChartRef } = useChart(buildMatrixOption, [() => matrixData.value])
</script>

<style scoped>
.section-label {
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 4px;
  font-weight: 500;
  display: block;
}

.hint-text {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0;
}

.top-bar {
  display: flex;
  gap: 16px;
}

.metric-card {
  background: var(--bg-tertiary, #f5f7fa);
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
  color: var(--text-secondary, #909399);
  margin-bottom: 4px;
}

.metric-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary, #303133);
}

.metric-value.r-strong { color: #059669; }
.metric-value.r-medium { color: #d97706; }
.metric-value.r-weak { color: var(--text-primary, #303133); }

.chart-wrapper {
  flex: 1;
  min-height: 480px;
  background: var(--bg-secondary, #fff);
  border-radius: 6px;
  border: 1px solid var(--border-default, #e4e7ed);
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

.axis-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.axis-item {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.axis-label {
  font-size: 13px;
  color: var(--text-secondary, #909399);
  white-space: nowrap;
  min-width: 30px;
}

:deep(.el-collapse-item__header) {
  font-size: 13px;
  color: var(--text-secondary, #909399);
  border: none;
  padding: 4px 0;
}

:deep(.el-collapse-item__wrap) {
  border: none;
}

:deep(.el-collapse-item__content) {
  padding: 8px 0 0 0;
}
</style>
