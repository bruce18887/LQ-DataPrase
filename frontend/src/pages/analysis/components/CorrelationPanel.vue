<template>
  <div class="correlation-panel">
    <el-card header="🔗 测试项相关性分析" style="margin-top: 16px">
      <!-- 参数选择 -->
      <el-row :gutter="12" style="margin-bottom: 12px" align="middle">
        <el-col :span="5">
          <el-select v-model="localX" placeholder="X轴测试项" filterable style="width: 100%">
            <el-option v-for="p in params" :key="p" :label="p" :value="p" />
          </el-select>
        </el-col>
        <el-col :span="5">
          <el-select v-model="localY" placeholder="Y轴测试项" filterable style="width: 100%">
            <el-option v-for="p in params" :key="p" :label="p" :value="p" />
          </el-select>
        </el-col>
        <el-col :span="3">
          <el-button type="primary" @click="onAnalyze" :loading="loading">
            分析相关性
          </el-button>
        </el-col>
      </el-row>

      <!-- 坐标轴范围设置 (可折叠，默认收起) -->
      <div v-if="chartData" class="axis-row">
        <el-collapse v-model="axisCollapse" style="border: none">
          <el-collapse-item title="坐标轴范围设置" name="axis">
            <div class="axis-body">
              <!-- X 轴 -->
              <div class="axis-item">
                <label class="axis-select-label">X轴范围</label>
                <el-select v-model="axisModeX" @change="onAxisChange" size="small" style="width: 95px">
                  <el-option label="数据分布" value="data" />
                  <el-option label="西格玛" value="sigma" />
                  <el-option label="自定义" value="custom" />
                </el-select>
                <el-select v-if="axisModeX === 'sigma'" v-model="sigmaX" @change="onAxisChange" size="small" style="width: 65px; margin-left: 6px">
                  <el-option :value="3" label="3σ" />
                  <el-option :value="4" label="4σ" />
                  <el-option :value="6" label="6σ" />
                </el-select>
                <template v-if="axisModeX === 'custom'">
                  <el-input-number v-model="customMinX" @change="onAxisChange" size="small" :precision="4" :controls="false" style="width: 100px; margin-left: 6px" placeholder="最小值" />
                  <span style="margin: 0 3px">~</span>
                  <el-input-number v-model="customMaxX" @change="onAxisChange" size="small" :precision="4" :controls="false" style="width: 100px" placeholder="最大值" />
                </template>
              </div>
              <!-- Y 轴 -->
              <div class="axis-item">
                <label class="axis-select-label">Y轴范围</label>
                <el-select v-model="axisModeY" @change="onAxisChange" size="small" style="width: 95px">
                  <el-option label="数据分布" value="data" />
                  <el-option label="西格玛" value="sigma" />
                  <el-option label="自定义" value="custom" />
                </el-select>
                <el-select v-if="axisModeY === 'sigma'" v-model="sigmaY" @change="onAxisChange" size="small" style="width: 65px; margin-left: 6px">
                  <el-option :value="3" label="3σ" />
                  <el-option :value="4" label="4σ" />
                  <el-option :value="6" label="6σ" />
                </el-select>
                <template v-if="axisModeY === 'custom'">
                  <el-input-number v-model="customMinY" @change="onAxisChange" size="small" :precision="4" :controls="false" style="width: 100px; margin-left: 6px" placeholder="最小值" />
                  <span style="margin: 0 3px">~</span>
                  <el-input-number v-model="customMaxY" @change="onAxisChange" size="small" :precision="4" :controls="false" style="width: 100px" placeholder="最大值" />
                </template>
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>

      <!-- 散点图 -->
      <div v-if="chartData" ref="chartRef" class="chart-container" />

      <!-- 指标栏: Pearson r | 数据点数 -->
      <el-row v-if="chartData" :gutter="16" style="margin-top: 16px">
        <el-col :span="12">
          <div class="metric-card">
            <div class="metric-label">Pearson r</div>
            <div class="metric-value" :class="rColorClass">
              {{ (chartData?.pearson_r ?? 0).toFixed(4) }}
            </div>
          </div>
        </el-col>
        <el-col :span="12">
          <div class="metric-card">
            <div class="metric-label">数据点数</div>
            <div class="metric-value">{{ (chartData?.n ?? 0).toLocaleString() }}</div>
          </div>
        </el-col>
      </el-row>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import { getChartInitOpts } from '../../../utils/echarts-theme'
import { useThemeStore } from '../../../stores/theme'
const _tc = () => getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#606266'
const themeStore = useThemeStore()

const props = defineProps<{
  params: string[]
  loading: boolean
  chartData: any
}>()

const emit = defineEmits<{
  analyze: [x: string, y: string]
}>()

const localX = ref('')
const localY = ref('')

// ---- 轴范围 (默认收起，X/Y 独立) ----
const axisCollapse = ref<string[]>([])
const axisModeX = ref<'data' | 'sigma' | 'custom'>('data')
const axisModeY = ref<'data' | 'sigma' | 'custom'>('data')
const sigmaX = ref(3)
const sigmaY = ref(3)
const customMinX = ref(0)
const customMaxX = ref(0)
const customMinY = ref(0)
const customMaxY = ref(0)

// ---- chart ----
const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

const SITE_COLORS = [
  '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
  '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#5383e0',
]

const rColorClass = computed(() => {
  const r = Math.abs(props.chartData?.pearson_r ?? 0)
  if (r > 0.7) return 'r-strong'
  if (r > 0.4) return 'r-medium'
  return 'r-weak'
})

// 新数据到达时初始化自定义范围默认值
watch(() => props.chartData, (data) => {
  if (!data) return
  const allX: number[] = [], allY: number[] = []
  for (const sd of data.series_data || []) {
    for (const pt of sd.data || []) {
      allX.push(pt[0]); allY.push(pt[1])
    }
  }
  if (allX.length > 0) { customMinX.value = r4(Math.min(...allX)); customMaxX.value = r4(Math.max(...allX)) }
  if (allY.length > 0) { customMinY.value = r4(Math.min(...allY)); customMaxY.value = r4(Math.max(...allY)) }
})

function r4(v: number) { return Math.round(v * 1e4) / 1e4 }

function onAnalyze() {
  if (localX.value && localY.value) emit('analyze', localX.value, localY.value)
}

function onAxisChange() {
  if (props.chartData) nextTick(() => renderChart())
}

function initChart() {
  if (!chartRef.value || chartInstance) return
  chartInstance = echarts.init(chartRef.value, undefined, getChartInitOpts())
}

function computeRange(mode: string, sigma: number, cMin: number, cMax: number, vals: number[]) {
  if (mode === 'custom') return { min: cMin, max: cMax }
  if (mode === 'sigma') {
    const m = vals.reduce((a, b) => a + b, 0) / vals.length
    const s = Math.sqrt(vals.reduce((sum, v) => sum + (v - m) ** 2, 0) / vals.length)
    return { min: m - sigma * s, max: m + sigma * s }
  }
  // data: 数据范围 + 两边各加两等分 (range / 2)
  const dMin = Math.min(...vals), dMax = Math.max(...vals)
  const rng = dMax > dMin ? dMax - dMin : 1
  const expand = rng / 2
  return { min: dMin - expand, max: dMax + expand }
}

function renderChart() {
  if (!chartInstance || !props.chartData) return
  chartInstance.clear()

  const d = props.chartData
  const series: any[] = (d.series_data || []).map(
    (sd: { name: string; data: number[][] }, idx: number) => ({
      name: sd.name,
      type: 'scatter',
      data: sd.data,
      symbolSize: 6,
      itemStyle: { color: SITE_COLORS[idx % SITE_COLORS.length], opacity: 0.6 },
    })
  )

  // 收集全部 X / Y
  const allX: number[] = [], allY: number[] = []
  for (const sd of d.series_data || []) {
    for (const pt of sd.data || []) { allX.push(pt[0]); allY.push(pt[1]) }
  }

  const xR = allX.length > 0 ? computeRange(axisModeX.value, sigmaX.value, customMinX.value, customMaxX.value, allX) : { min: undefined, max: undefined }
  const yR = allY.length > 0 ? computeRange(axisModeY.value, sigmaY.value, customMinY.value, customMaxY.value, allY) : { min: undefined, max: undefined }

  chartInstance.setOption({
    title: {
      text: `${d.param_x} vs ${d.param_y}`,
      subtext: `Pearson r = ${d.pearson_r?.toFixed(4) ?? '-'}`,
      left: 'center',
      textStyle: { color: _tc(), fontSize: 14 },
      subtextStyle: { color: _tc(), fontSize: 12 },
    },
    toolbox: { feature: { saveAsImage: { title: '保存图片' }, restore: { title: '还原' } }, right: 10 },
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => `${p.seriesName}<br/>${d.param_x}: ${Number(p.value[0]).toFixed(4)}<br/>${d.param_y}: ${Number(p.value[1]).toFixed(4)}`,
    },
    legend: { data: series.map((s: any) => s.name), bottom: 5, type: 'scroll', textStyle: { color: _tc() } },
    xAxis: {
      type: 'value', name: d.param_x, nameLocation: 'center', nameGap: 30,
      min: xR.min, max: xR.max,
      axisLabel: { color: _tc() }, nameTextStyle: { color: _tc() },
    },
    yAxis: {
      type: 'value', name: d.param_y, nameLocation: 'center', nameGap: 40,
      min: yR.min, max: yR.max,
      axisLabel: { color: _tc() }, nameTextStyle: { color: _tc() },
    },
    dataZoom: [
      { type: 'slider', xAxisIndex: 0, start: 0, end: 100 },
      { type: 'slider', yAxisIndex: 0, start: 0, end: 100 },
      { type: 'inside', xAxisIndex: 0 },
      { type: 'inside', yAxisIndex: 0 },
    ],
    series,
  })
}

function resize() { chartInstance?.resize() }

watch(() => props.chartData, () => { nextTick(() => { initChart(); renderChart() }) })
watch(() => themeStore.currentTheme, () => { if (!chartRef.value?.isConnected) return; nextTick(() => renderChart()) })

onMounted(() => window.addEventListener('resize', resize))
onUnmounted(() => {
  window.removeEventListener('resize', resize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<style scoped>
.correlation-panel { width: 100%; }
.chart-container { height: 500px; width: 100%; }

.axis-row { margin-bottom: 8px; }
.axis-body { display: flex; gap: 24px; }
.axis-item { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.axis-select-label { font-size: 13px; color: var(--text-secondary, #909399); white-space: nowrap; }

.metric-card {
  background: var(--bg-tertiary, #f5f7fa);
  border-radius: 8px; padding: 12px 16px;
  text-align: center; height: 100%;
  display: flex; flex-direction: column; justify-content: center; align-items: center;
}
.metric-label { font-size: 12px; color: var(--text-secondary, #909399); margin-bottom: 4px; }
.metric-value { font-size: 22px; font-weight: 700; color: var(--text-primary, #303133); }
.metric-value.r-strong { color: #059669; }
.metric-value.r-medium { color: #d97706; }
.metric-value.r-weak { color: var(--text-primary, #303133); }

:deep(.el-collapse-item__header) { font-size: 13px; color: var(--text-secondary, #909399); border: none; padding: 4px 0; }
:deep(.el-collapse-item__wrap) { border: none; }
:deep(.el-collapse-item__content) { padding: 8px 0 0 0; }
</style>
