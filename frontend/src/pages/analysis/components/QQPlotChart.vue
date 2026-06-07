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
import { computed } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'

const props = defineProps<{
  fileId: number | null
  param: string
  visible: boolean
  result: any
  loading: boolean
}>()

const { colors } = useEChartsTheme()

const isEmptyResult = computed(() => {
  if (!props.result) return false
  const t = props.result.theoretical_quantiles
  return !t || t.length === 0
})

function buildOption() {
  const r = props.result
  if (!r) return {}

  const theoretical: number[] = r.theoretical_quantiles || []
  const observed: number[] = r.observed_quantiles || []
  if (theoretical.length === 0) return {}

  const tc = colors.value.textColor
  const scatterData = theoretical.map((t, i) => [t, observed[i]])
  const allValues = [...theoretical, ...observed]
  const dataMin = Math.min(...allValues)
  const dataMax = Math.max(...allValues)
  const diagonal = [[dataMin, dataMin], [dataMax, dataMax]]

  const rSquared = r.r_squared
  const isNormal = r.is_normal === true

  const graphic: any[] = []
  if (rSquared != null) {
    graphic.push({
      type: 'text', left: 10, top: 32, z: 100,
      style: {
        text: `R² = ${rSquared.toFixed(4)}`, fill: tc, fontSize: 13, fontWeight: 'bold',
        backgroundColor: 'rgba(255,255,255,0.75)', padding: [4, 8], borderRadius: 4,
      },
    })
  }
  graphic.push({
    type: 'text', right: 10, top: 32, z: 100,
    style: {
      text: isNormal ? '正态' : '非正态', fill: '#ffffff', fontSize: 12, fontWeight: 'bold',
      backgroundColor: isNormal ? '#4CAF50' : '#F44336', padding: [4, 10], borderRadius: 4,
    },
  })

  return {
    title: {
      text: `${props.param} QQ图`, left: 'center', top: 6,
      textStyle: { fontSize: 14, fontWeight: 'bold', color: tc },
    },
    tooltip: {
      trigger: 'item',
      formatter: (p: any) =>
        `理论分位数: ${Number(p.value[0]).toFixed(4)}<br/>观测值: ${Number(p.value[1]).toFixed(4)}`,
    },
    toolbox: { feature: { saveAsImage: { name: `${props.param}_QQ图` } } },
    grid: { top: 50, bottom: 40, left: 55, right: 20 },
    xAxis: {
      type: 'value', name: '理论分位数', nameLocation: 'middle', nameGap: 30,
      nameTextStyle: { color: tc }, axisLabel: { color: tc },
    },
    yAxis: {
      type: 'value', name: '观测值', nameLocation: 'middle', nameGap: 45,
      nameTextStyle: { color: tc }, axisLabel: { color: tc },
    },
    graphic,
    series: [
      { name: '数据点', type: 'scatter', data: scatterData, symbolSize: 5, itemStyle: { color: '#1E88E5' } },
      { name: 'y=x参考线', type: 'line', data: diagonal, lineStyle: { color: '#9E9E9E', type: 'dashed', width: 2 }, symbol: 'none', silent: true },
    ],
  }
}

const { chartRef } = useChart(buildOption, [() => props.result, () => props.visible])
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
