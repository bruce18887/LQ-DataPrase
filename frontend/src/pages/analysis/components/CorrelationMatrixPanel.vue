<template>
  <el-card header="🔗 相关性矩阵" style="margin-top:16px">
    <el-row :gutter="12" style="margin-bottom: 12px">
      <el-col :span="6">
        <el-button type="primary" @click="onCalculate" :loading="loading">
          计算相关性矩阵
        </el-button>
      </el-col>
    </el-row>
    <div v-if="matrixData" ref="chartRef" style="height: 500px" />
    <el-empty v-else description="点击按钮计算所有有 Limit 测试项的 Pearson 相关系数矩阵" />
  </el-card>
</template>

<script setup lang="ts">
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'

const props = defineProps<{ loading: boolean; matrixData: any }>()
const emit = defineEmits<{ calculate: [] }>()
const { colors } = useEChartsTheme()

function onCalculate() { emit('calculate') }

function buildOption() {
  if (!props.matrixData) return {}
  const tc = colors.value.textColor
  const data = props.matrixData
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

const { chartRef } = useChart(buildOption, [() => props.matrixData])
</script>
