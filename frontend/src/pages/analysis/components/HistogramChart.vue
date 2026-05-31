<template>
  <div ref="chartRef" class="chart-container" />
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import { useThemeStore } from '../../../stores/theme'
const _tc = () => getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#ffffff'
const themeStore = useThemeStore()

const props = defineProps<{
  result: any
  chartConfig: string[]
  rangeType: string
  barWidthPercent: number
  selectedParam: string
}>()

const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

const COLORS_SITE_8 = ['#E53935', '#1E88E5', '#43A047', '#F9A825', '#8E24AA', '#00ACC1', '#F57C00', '#D81B60']

function initChart() {
  if (!chartRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
  }
}

function renderChart() {
  if (!chartInstance || !props.result) return

  chartInstance.clear()

  const r = props.result

  const binCenters: number[] = r.bin_centers || []
  if (binCenters.length === 0) return

  const dMin = binCenters[0]
  const dMax = binCenters[binCenters.length - 1]

  const series: any[] = []

  const siteHists = r.site_histograms
  const hasSiteData = siteHists && Object.keys(siteHists).length > 1

  if (hasSiteData) {
    const sites = Object.keys(siteHists).sort((a, b) => Number(a) - Number(b))
    for (let idx = 0; idx < sites.length; idx++) {
      const site = sites[idx]
      const hists: number[] = siteHists[site] || []
      const barData = binCenters.map((center: number, i: number) => [center, hists[i] ?? 0])
      series.push({
        name: `Site${site}`,
        type: 'bar',
        data: barData,
        itemStyle: { color: COLORS_SITE_8[idx % COLORS_SITE_8.length] },
        barWidth: `${props.barWidthPercent}%`,
      })
    }
  } else {
    const barData = binCenters.map((center: number, i: number) => [center, r.bin_percentages?.[i] || 0])
    series.push({
      name: '数据分布',
      type: 'bar',
      data: barData,
      itemStyle: { color: '#1E88E5' },
      barWidth: `${props.barWidthPercent}%`,
    })
  }

  const mk: any[] = []

  let limitMin = r.lower_limit
  let limitMax = r.upper_limit
  switch (props.rangeType) {
    case 'DR':
    case 'CL':
      limitMin = r.data_min
      limitMax = r.data_max
      break
    case 'S3':
      limitMin = r.sigma3_min ?? r.lower_limit
      limitMax = r.sigma3_max ?? r.upper_limit
      break
    case 'S4':
      limitMin = r.mean - 4 * r.std
      limitMax = r.mean + 4 * r.std
      break
    case 'S6':
      limitMin = r.sigma6_min ?? r.lower_limit
      limitMax = r.sigma6_max ?? r.upper_limit
      break
  }

  const showLimit = props.chartConfig.includes('limit')
  if (showLimit && limitMin != null && limitMax != null) {
    mk.push(
      {
        xAxis: limitMin,
        lineStyle: { color: '#C62828', width: 3, type: 'dashed' },
        label: { show: true, formatter: 'LSL', position: 'end' },
      },
      {
        xAxis: limitMax,
        lineStyle: { color: '#C62828', width: 3, type: 'dashed' },
        label: { show: true, formatter: 'USL', position: 'end' },
      },
    )
  }
  if (props.chartConfig.includes('s3') && r.sigma3_min != null && r.sigma3_max != null) {
    mk.push(
      { xAxis: r.sigma3_min, lineStyle: { color: '#1565C0', width: 3, type: 'dotted' }, label: { show: true, formatter: '3σ下限', position: 'insideEndTop' } },
      { xAxis: r.sigma3_max, lineStyle: { color: '#1565C0', width: 3, type: 'dotted' }, label: { show: true, formatter: '3σ上限', position: 'insideEndTop' } },
    )
  }
  if (props.chartConfig.includes('s4') && r.std > 0) {
    const s4min = r.mean - 4 * r.std
    const s4max = r.mean + 4 * r.std
    mk.push(
      { xAxis: s4min, lineStyle: { color: '#00838F', width: 3, type: 'dotted' }, label: { show: true, formatter: '4σ下限', position: 'insideEndTop' } },
      { xAxis: s4max, lineStyle: { color: '#00838F', width: 3, type: 'dotted' }, label: { show: true, formatter: '4σ上限', position: 'insideEndTop' } },
    )
  }
  if (props.chartConfig.includes('s6') && r.sigma6_min != null && r.sigma6_max != null) {
    mk.push(
      { xAxis: r.sigma6_min, lineStyle: { color: '#E65100', width: 3, type: 'dotted' }, label: { show: true, formatter: '6σ下限', position: 'insideEndTop' } },
      { xAxis: r.sigma6_max, lineStyle: { color: '#E65100', width: 3, type: 'dotted' }, label: { show: true, formatter: '6σ上限', position: 'insideEndTop' } },
    )
  }

  if (mk.length) {
    series.push({
      name: '规格限',
      type: 'line',
      data: [],
      markLine: { symbol: 'none', precision: 4, data: mk },
    })
  }

  const showNormal = props.chartConfig.includes('normal')
  let hasNormal = false
  if (showNormal && r.std > 0) {
    const xVals: number[] = binCenters
    const pdf = xVals.map(
      (x: number) =>
        (1 / (r.std * Math.sqrt(2 * Math.PI))) *
        Math.exp(-0.5 * ((x - r.mean) / r.std) ** 2)
    )

    series.push({
      name: '正态分布',
      type: 'line',
      data: xVals.map((x: number, i: number) => [x, pdf[i]]),
      smooth: true,
      lineStyle: { color: '#F57F17', width: 3 },
      symbol: 'none',
      yAxisIndex: 1,
      z: 10,
    })
    hasNormal = true
  }

  const yAxes: any[] = [
    {
      type: 'value',
      name: '百分比 (%)',
      nameTextStyle: { color: _tc() },
      position: 'left',
      min: 0,
      max: 100,
      axisLabel: { formatter: '{value}%', color: _tc() },
    },
  ]

  if (hasNormal) {
    yAxes.push({
      type: 'value',
      name: '概率密度',
      nameTextStyle: { color: _tc() },
      position: 'right',
      min: 0,
      axisLabel: { formatter: (v: number) => v.toExponential(2), color: _tc() },
      splitLine: { show: false },
    })
  }

  // Build chart title: param name + unit + limit in center-top
  const unitStr = r.unit || ''
  const limitStr = (r.lower_limit != null && r.upper_limit != null)
    ? `Limit [${r.lower_limit.toFixed(4)}, ${r.upper_limit.toFixed(4)}]`
    : ''
  const titleText = `{name|${props.selectedParam}}  {unit|${unitStr ? `(${unitStr})` : ''}}  {limit|${limitStr || ''}}`

  chartInstance.setOption({
    title: {
      text: titleText,
      left: 'center',
      top: 6,
      textStyle: {
        rich: {
          name: {
            fontSize: 15,
            fontWeight: 'bold',
            color: _tc(),
          },
          unit: {
            fontSize: 12,
            color: _tc(),
            fontWeight: 500,
          },
          limit: {
            fontSize: 12,
            color: '#E65100',
            fontWeight: 600,
            backgroundColor: '#FFF3E0',
            padding: [2, 6],
            borderRadius: 3,
          },
        },
      },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params: any) => {
        const items = Array.isArray(params) ? params : [params]
        let html = `值: ${Number(items[0].data[0]).toFixed(4)}<br/>`
        for (const p of items) {
          if (p.seriesName !== '规格限' && p.seriesName !== '正态分布' && p.data[1] != null) {
            html += `${p.seriesName}: ${Number(p.data[1]).toFixed(2)}%<br/>`
          }
        }
        return html
      },
    },
    legend: { data: series.map((s: any) => s.name), top: 'bottom', type: 'scroll', textStyle: { color: _tc() } },
    toolbox: { feature: { saveAsImage: { name: `${props.selectedParam}_分析` } } },
    grid: { top: 55, bottom: 70, left: 55, right: hasNormal ? 75 : 55 },
    xAxis: {
      type: 'value',
      name: '',
      nameLocation: 'middle',
      nameGap: 28,
      min: dMin,
      max: dMax,
      axisLabel: { rotate: 45, show: true, interval: 0, fontSize: 9, formatter: (v: number) => v.toFixed(4), color: _tc() },
      splitNumber: 24,
    },
    yAxis: yAxes,
    series,
  })
}

function resize() {
  chartInstance?.resize()
}

watch(() => props.result, () => {
  nextTick(() => renderChart())
})

watch(() => props.chartConfig, () => {
  nextTick(() => renderChart())
}, { deep: true })

watch(() => props.rangeType, () => {
  nextTick(() => renderChart())
})

watch(() => props.barWidthPercent, () => {
  nextTick(() => renderChart())
})

watch(() => themeStore.currentTheme, () => {
  nextTick(() => renderChart())
})

onMounted(() => {
  initChart()
  if (props.result) {
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
.chart-container {
  width: 100%;
  height: 100%;
  min-height: 400px;
}
</style>
