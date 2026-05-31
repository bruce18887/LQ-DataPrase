<template>
  <div class="qqplot-chart">
    <!-- Loading state -->
    <div v-if="loading" class="qqplot-placeholder">
      <el-icon class="is-loading" style="font-size: 24px; margin-right: 8px;"><Loading /></el-icon>
      <span>正在计算QQ图...</span>
    </div>
    <!-- Empty / no-data state -->
    <div v-else-if="!result || isEmptyResult" class="qqplot-placeholder">
      <el-empty :description="!result ? '暂无QQ图数据' : '该参数无有效数值数据'" :image-size="80" />
    </div>
    <!-- Chart container -->
    <div v-else ref="chartRef" class="qqplot-container" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { useThemeStore } from '../../../stores/theme'

const _tc = () =>
  getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#ffffff'

const themeStore = useThemeStore()

const props = defineProps<{
  fileId: number | null
  param: string
  visible: boolean
  result: any
  loading: boolean
}>()

const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

const isEmptyResult = computed(() => {
  if (!props.result) return false
  const t = props.result.theoretical_quantiles
  return !t || t.length === 0
})

function initChart() {
  if (!chartRef.value) return
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
  chartInstance = echarts.init(chartRef.value)
}

function renderChart() {
  if (!chartInstance || !props.result) return
  chartInstance.clear()

  const r = props.result
  const theoretical: number[] = r.theoretical_quantiles || []
  const observed: number[] = r.observed_quantiles || []
  if (theoretical.length === 0) return

  // Data points as [x, y] pairs
  const scatterData = theoretical.map((t, i) => [t, observed[i]])

  // Diagonal reference line y = x
  const allValues = [...theoretical, ...observed]
  const dataMin = Math.min(...allValues)
  const dataMax = Math.max(...allValues)
  const diagonal = [
    [dataMin, dataMin],
    [dataMax, dataMax],
  ]

  const textColor = _tc()
  const rSquared = r.r_squared
  const isNormal = r.is_normal === true

  // Graphic elements for annotations
  const graphic: any[] = []

  // R-squared annotation (top-left)
  if (rSquared != null) {
    graphic.push({
      type: 'text',
      left: 10,
      top: 32,
      style: {
        text: `R² = ${rSquared.toFixed(4)}`,
        fill: textColor,
        fontSize: 13,
        fontWeight: 'bold',
        backgroundColor: 'rgba(255,255,255,0.75)',
        padding: [4, 8],
        borderRadius: 4,
      },
      z: 100,
    })
  }

  // Normality verdict badge (top-right)
  graphic.push({
    type: 'text',
    right: 10,
    top: 32,
    style: {
      text: isNormal ? '正态' : '非正态',
      fill: '#ffffff',
      fontSize: 12,
      fontWeight: 'bold',
      backgroundColor: isNormal ? '#4CAF50' : '#F44336',
      padding: [4, 10],
      borderRadius: 4,
    },
    z: 100,
  })

  chartInstance.setOption({
    title: {
      text: `${props.param} QQ图`,
      left: 'center',
      top: 6,
      textStyle: { fontSize: 14, fontWeight: 'bold', color: textColor },
    },
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        return `理论分位数: ${Number(p.value[0]).toFixed(4)}<br/>观测值: ${Number(p.value[1]).toFixed(4)}`
      },
    },
    toolbox: {
      feature: {
        saveAsImage: { name: `${props.param}_QQ图` },
      },
    },
    grid: { top: 50, bottom: 40, left: 55, right: 20 },
    xAxis: {
      type: 'value',
      name: '理论分位数',
      nameLocation: 'middle',
      nameGap: 30,
      nameTextStyle: { color: textColor },
      axisLabel: { color: textColor },
    },
    yAxis: {
      type: 'value',
      name: '观测值',
      nameLocation: 'middle',
      nameGap: 45,
      nameTextStyle: { color: textColor },
      axisLabel: { color: textColor },
    },
    graphic,
    series: [
      {
        name: '数据点',
        type: 'scatter',
        data: scatterData,
        symbolSize: 5,
        itemStyle: { color: '#1E88E5' },
      },
      {
        name: 'y=x参考线',
        type: 'line',
        data: diagonal,
        lineStyle: { color: '#9E9E9E', type: 'dashed', width: 2 },
        symbol: 'none',
        silent: true,
      },
    ],
  })
}

function resize() {
  chartInstance?.resize()
}

// React to data changes
watch(
  () => props.result,
  () => {
    if (props.visible) {
      nextTick(() => {
        initChart()
        renderChart()
      })
    }
  },
  { deep: true }
)

// React to visibility toggle
watch(
  () => props.visible,
  (val) => {
    if (val && props.result) {
      nextTick(() => {
        initChart()
        renderChart()
      })
    }
  }
)

// React to theme change
watch(
  () => themeStore.currentTheme,
  () => {
    nextTick(() => renderChart())
  }
)

onMounted(() => {
  if (props.visible && props.result) {
    initChart()
    renderChart()
  }
  window.addEventListener('resize', resize)
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<style scoped>
.qqplot-chart {
  width: 100%;
  height: 100%;
  min-height: 400px;
  position: relative;
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
  background: var(--bg-secondary);
  border-radius: 6px;
  border: 1px solid var(--border-default);
  color: var(--text-secondary);
  font-size: 14px;
}
</style>
