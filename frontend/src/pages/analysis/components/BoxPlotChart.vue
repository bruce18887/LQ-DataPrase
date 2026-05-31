<template>
  <div ref="chartRef" class="chart-container" style="width: 100%; height: 500px" />
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'

interface BoxPlotStats {
  min: number
  q1: number
  median: number
  q3: number
  max: number
  outliers: number[]
  count: number
}

interface BoxPlotData {
  param: string
  overall?: BoxPlotStats
  by_site?: Record<string, BoxPlotStats>
  by_bin?: Record<string, BoxPlotStats>
}

const props = defineProps<{
  data: BoxPlotData | null
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

  const { overall, by_site, by_bin } = props.data

  // Determine if we have grouped data
  const hasGroupedData = (by_site && Object.keys(by_site).length > 0) || (by_bin && Object.keys(by_bin).length > 0)
  const groupedData = by_site || by_bin || {}

  let categories: string[] = []
  let boxData: number[][] = []
  let outlierData: number[][] = []

  if (hasGroupedData) {
    // Grouped box plots
    categories = Object.keys(groupedData).sort((a, b) => {
      const numA = parseFloat(a)
      const numB = parseFloat(b)
      if (!isNaN(numA) && !isNaN(numB)) return numA - numB
      return a.localeCompare(b)
    })

    categories.forEach((group, idx) => {
      const stats = groupedData[group]
      boxData.push([stats.min, stats.q1, stats.median, stats.q3, stats.max])

      // Add outliers
      stats.outliers.forEach(outlier => {
        outlierData.push([idx, outlier])
      })
    })
  } else if (overall) {
    // Single box plot
    categories = [props.data.param]
    boxData.push([overall.min, overall.q1, overall.median, overall.q3, overall.max])

    // Add outliers
    overall.outliers.forEach(outlier => {
      outlierData.push([0, outlier])
    })
  }

  const option: echarts.EChartsOption = {
    title: {
      text: props.title || `Box Plot - ${props.data.param}`,
      left: 'center',
      textStyle: {
        fontSize: 16,
        fontWeight: 'bold'
      }
    },
    tooltip: {
      trigger: 'item',
      axisPointer: {
        type: 'shadow'
      },
      formatter: (params: any) => {
        if (params.seriesName === 'Outliers') {
          return `Outlier: ${params.value[1].toFixed(4)}`
        }
        const data = params.value
        return `
          <strong>${params.name}</strong><br/>
          Max: ${data[5].toFixed(4)}<br/>
          Q3: ${data[4].toFixed(4)}<br/>
          Median: ${data[3].toFixed(4)}<br/>
          Q1: ${data[2].toFixed(4)}<br/>
          Min: ${data[1].toFixed(4)}
        `
      }
    },
    grid: {
      left: '10%',
      right: '10%',
      bottom: '15%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: categories,
      boundaryGap: true,
      nameGap: 30,
      splitArea: {
        show: false
      },
      axisLabel: {
        rotate: categories.length > 10 ? 45 : 0,
        interval: 0,
        fontSize: 10
      },
      splitLine: {
        show: false
      }
    },
    yAxis: {
      type: 'value',
      name: 'Value',
      splitArea: {
        show: true
      }
    },
    series: [
      {
        name: 'Box Plot',
        type: 'boxplot',
        data: boxData,
        itemStyle: {
          color: '#5470C6',
          borderColor: '#2c3e50'
        },
        tooltip: {
          formatter: (param: any) => {
            return `
              <strong>${param.name}</strong><br/>
              Max: ${param.data[5].toFixed(4)}<br/>
              Q3: ${param.data[4].toFixed(4)}<br/>
              Median: ${param.data[3].toFixed(4)}<br/>
              Q1: ${param.data[2].toFixed(4)}<br/>
              Min: ${param.data[1].toFixed(4)}
            `
          }
        }
      },
      {
        name: 'Outliers',
        type: 'scatter',
        data: outlierData,
        itemStyle: {
          color: '#EE6666'
        },
        symbolSize: 6
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
</script>

<style scoped>
.chart-container {
  width: 100%;
  height: 100%;
  min-height: 400px;
}
</style>
