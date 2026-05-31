<template>
  <el-card header="🔗 相关性分析" style="margin-top: 16px">
    <el-row :gutter="12" style="margin-bottom: 12px" align="middle">
      <el-col :span="5">
        <el-select v-model="localX" placeholder="X 参数" filterable style="width: 100%">
          <el-option v-for="p in params" :key="p" :label="p" :value="p" />
        </el-select>
      </el-col>
      <el-col :span="5">
        <el-select v-model="localY" placeholder="Y 参数" filterable style="width: 100%">
          <el-option v-for="p in params" :key="p" :label="p" :value="p" />
        </el-select>
      </el-col>
      <el-col :span="3">
        <el-button type="primary" @click="onAnalyze" :loading="loading">
          分析相关性
        </el-button>
      </el-col>
      <el-col :span="6" v-if="pearsonR !== null">
        <el-tag size="large" :type="Math.abs(pearsonR) > 0.7 ? 'success' : Math.abs(pearsonR) > 0.4 ? 'warning' : 'info'">
          Pearson r = {{ pearsonR.toFixed(4) }}
        </el-tag>
      </el-col>
    </el-row>
    <el-row :gutter="8" style="margin-top:8px">
      <el-col :span="4">
        <el-select v-model="localAxisMode" @change="onAxisModeChange" style="width:100%">
          <el-option label="数据分布" value="data" />
          <el-option label="3 Sigma" value="s3" />
          <el-option label="6 Sigma" value="s6" />
        </el-select>
      </el-col>
    </el-row>
    <div v-if="chartData" ref="chartRef" style="height: 450px" />
  </el-card>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import { useThemeStore } from '../../../stores/theme'
const _tc = () => getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#ffffff'
const themeStore = useThemeStore()

const props = defineProps<{
  params: string[]
  loading: boolean
  pearsonR: number | null
  chartData: any
  axisMode: string
}>()

const emit = defineEmits<{
  analyze: [x: string, y: string]
  'update:axisMode': [value: string]
}>()

const localX = ref('')
const localY = ref('')
const localAxisMode = ref(props.axisMode)
const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

const SITE_COLORS = [
  '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
  '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#5383e0',
]

watch(() => props.axisMode, (val) => {
  localAxisMode.value = val
})

watch(localAxisMode, (val) => {
  emit('update:axisMode', val)
})

function onAnalyze() {
  if (localX.value && localY.value) {
    emit('analyze', localX.value, localY.value)
  }
}

function onAxisModeChange() {
  if (props.chartData) {
    nextTick(() => renderChart())
  }
}

function initChart() {
  if (!chartRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
  }
}

function renderChart() {
  if (!chartInstance || !props.chartData) return
  chartInstance.clear()

  const data = props.chartData

  const series: any[] = (data.series_data || []).map(
    (sd: { name: string; data: number[][] }, idx: number) => ({
      name: sd.name,
      type: 'scatter',
      data: sd.data,
      symbolSize: 5,
      itemStyle: { color: SITE_COLORS[idx % SITE_COLORS.length], opacity: 0.6 },
    })
  )

  let xMin: number | undefined = undefined
  let xMax: number | undefined = undefined
  let yMin: number | undefined = undefined
  let yMax: number | undefined = undefined

  if (localAxisMode.value !== 'data') {
    const sigmaLevel = localAxisMode.value === 's3' ? 3 : 6
    const allX: number[] = []
    const allY: number[] = []
    for (const sd of data.series_data || []) {
      for (const pt of sd.data || []) {
        allX.push(pt[0])
        allY.push(pt[1])
      }
    }
    if (allX.length > 0) {
      const mx = allX.reduce((a: number, b: number) => a + b, 0) / allX.length
      const sx = Math.sqrt(allX.reduce((sum: number, v: number) => sum + (v - mx) ** 2, 0) / allX.length)
      xMin = mx - sigmaLevel * sx
      xMax = mx + sigmaLevel * sx

      const my = allY.reduce((a: number, b: number) => a + b, 0) / allY.length
      const sy = Math.sqrt(allY.reduce((sum: number, v: number) => sum + (v - my) ** 2, 0) / allY.length)
      yMin = my - sigmaLevel * sy
      yMax = my + sigmaLevel * sy
    }
  }

  chartInstance.setOption({
    title: {
      text: `${data.param_x} vs ${data.param_y}`,
      subtext: `Pearson r = ${data.pearson_r?.toFixed(4) ?? '-'} | N = ${data.n}`,
      left: 'center',
    },
    tooltip: {
      trigger: 'item',
      formatter: (p: any) =>
        `${p.seriesName}<br/>${data.param_x}: ${Number(p.value[0]).toFixed(4)}<br/>${data.param_y}: ${Number(p.value[1]).toFixed(4)}`,
    },
    legend: {
      data: series.map((s: any) => s.name),
      bottom: 5,
      type: 'scroll',
      textStyle: { color: _tc() },
    },
    xAxis: { type: 'value', name: data.param_x, min: xMin, max: xMax, axisLabel: { color: _tc() }, nameTextStyle: { color: _tc() } },
    yAxis: { type: 'value', name: data.param_y, min: yMin, max: yMax, axisLabel: { color: _tc() }, nameTextStyle: { color: _tc() } },
    dataZoom: [
      { type: 'slider', xAxisIndex: 0, start: 0, end: 100 },
      { type: 'inside', xAxisIndex: 0 },
    ],
    series,
  })
}

function resize() {
  chartInstance?.resize()
}

watch(() => props.chartData, () => {
  nextTick(() => {
    initChart()
    renderChart()
  })
})

watch(() => themeStore.currentTheme, () => {
  nextTick(() => renderChart())
})

onMounted(() => {
  window.addEventListener('resize', resize)
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>
