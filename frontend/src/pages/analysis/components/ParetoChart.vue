<template>
  <div ref="chartRef" class="chart-container" style="width: 100%; height: 500px" />
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import { useThemeStore } from '../../../stores/theme'
const _tc = () => getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#ffffff'
const themeStore = useThemeStore()

interface ParetoData {
  categories: string[]
  values: number[]
  cumulative: number[]
}

const props = defineProps<{
  data: ParetoData | null
  title?: string
}>()

const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

function initChart() {
  if (!chartRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
  }
}

function renderChart() {
  if (!chartInstance || !props.data) return

  chartInstance.clear()

  const { categories, values, cumulative } = props.data

  if (!categories || categories.length === 0) return

  const option: echarts.EChartsOption = {
    title: {
      text: props.title || 'Pareto Chart',
      left: 'center',
      textStyle: {
        fontSize: 16,
        fontWeight: 'bold'
      }
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'cross',
        crossStyle: {
          color: _tc()
        }
      },
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
      }
    },
    legend: {
      data: ['Count', 'Cumulative %'],
      top: 30,
      textStyle: { color: _tc() }
    },
    grid: {
      left: '3%',
      right: '5%',
      bottom: '15%',
      containLabel: true
    },
    xAxis: [
      {
        type: 'category',
        data: categories,
        axisPointer: {
          type: 'shadow'
        },
        axisLabel: {
          rotate: 45,
          interval: 0,
          fontSize: 10,
          color: _tc()
        }
      }
    ],
    yAxis: [
      {
        type: 'value',
        name: 'Count',
        nameTextStyle: { color: _tc() },
        position: 'left',
        axisLabel: {
          formatter: '{value}',
          color: _tc()
        }
      },
      {
        type: 'value',
        name: 'Cumulative %',
        nameTextStyle: { color: _tc() },
        position: 'right',
        min: 0,
        max: 100,
        axisLabel: {
          formatter: '{value}%',
          color: _tc()
        }
      }
    ],
    series: [
      {
        name: 'Count',
        type: 'bar',
        data: values,
        itemStyle: {
          color: '#5470C6'
        },
        barWidth: '60%'
      },
      {
        name: 'Cumulative %',
        type: 'line',
        yAxisIndex: 1,
        data: cumulative,
        itemStyle: {
          color: '#EE6666'
        },
        lineStyle: {
          width: 2
        },
        symbol: 'circle',
        symbolSize: 6,
        markLine: {
          silent: true,
          lineStyle: {
            color: '#91CC75',
            type: 'dashed',
            width: 2
          },
          label: {
            formatter: '80%',
            position: 'end'
          },
          data: [
            {
              yAxis: 80
            }
          ]
        }
      }
    ]
  }

  chartInstance.setOption(option)
}

function handleResize() {
  chartInstance?.resize()
}

onMounted(() => {
  initChart()
  renderChart()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})

watch(() => props.data, () => {
  renderChart()
}, { deep: true })

watch(() => props.title, () => {
  renderChart()
})

watch(() => themeStore.currentTheme, () => {
  nextTick(() => renderChart())
})
</script>

<style scoped>
.chart-container {
  width: 100%;
  height: 100%;
  min-height: 400px;
}
</style>
