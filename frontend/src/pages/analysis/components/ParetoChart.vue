<template>
  <div ref="chartRef" class="chart-container" style="width: 100%; height: 500px" />
</template>

<script setup lang="ts">
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'

interface ParetoData {
  categories: string[]
  values: number[]
  cumulative: number[]
}

const props = defineProps<{
  data: ParetoData | null
  title?: string
}>()

const { colors } = useEChartsTheme()

function buildOption() {
  const tc = colors.value.textColor
  const d = props.data
  if (!d || !d.categories || d.categories.length === 0) {
    return {}
  }

  return {
    title: {
      text: props.title || 'Pareto Chart',
      left: 'center',
      textStyle: { fontSize: 16, fontWeight: 'bold' },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', crossStyle: { color: tc } },
      formatter: (params: any) => {
        if (!Array.isArray(params)) return ''
        let result = `<strong>${params[0].axisValue}</strong><br/>`
        params.forEach((item: any) => {
          if (item.seriesName === 'Count') {
            result += `${item.marker} ${item.seriesName}: ${item.value}<br/>`
          } else {
            result += `${item.marker} ${item.seriesName}: ${item.value.toFixed(2)}%<br/>`
          }
        })
        return result
      },
    },
    legend: {
      data: ['Count', 'Cumulative %'],
      top: 30,
      textStyle: { color: tc },
    },
    grid: { left: '3%', right: '5%', bottom: '15%', containLabel: true },
    xAxis: [
      {
        type: 'category',
        data: d.categories,
        axisPointer: { type: 'shadow' },
        axisLabel: { rotate: 45, interval: 0, fontSize: 10, color: tc },
      },
    ],
    yAxis: [
      {
        type: 'value',
        name: 'Count',
        nameTextStyle: { color: tc },
        position: 'left',
        axisLabel: { formatter: '{value}', color: tc },
      },
      {
        type: 'value',
        name: 'Cumulative %',
        nameTextStyle: { color: tc },
        position: 'right',
        min: 0,
        max: 100,
        axisLabel: { formatter: '{value}%', color: tc },
      },
    ],
    series: [
      {
        name: 'Count',
        type: 'bar',
        data: d.values,
        itemStyle: { color: '#5470C6' },
        barWidth: '60%',
      },
      {
        name: 'Cumulative %',
        type: 'line',
        yAxisIndex: 1,
        data: d.cumulative,
        itemStyle: { color: '#EE6666' },
        lineStyle: { width: 2 },
        symbol: 'circle',
        symbolSize: 6,
        markLine: {
          silent: true,
          lineStyle: { color: '#91CC75', type: 'dashed', width: 2 },
          label: { formatter: '80%', position: 'end' },
          data: [{ yAxis: 80 }],
        },
      },
    ],
  }
}

const { chartRef } = useChart(buildOption, [() => props.data, () => props.title])
</script>

<style scoped>
.chart-container {
  width: 100%;
  height: 100%;
  min-height: 400px;
}
</style>
