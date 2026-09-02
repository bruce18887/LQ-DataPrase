<!-- frontend/src/pages/analysis/components/BoxPlotChart.vue -->
<template>
  <!-- No-data placeholder: avoid ECharts init with min=Infinity/max=-Infinity
       which can throw via Vue's async update chain (emitsOptions null). -->
  <div v-if="!hasValidData" class="boxplot-placeholder">
    <el-icon class="boxplot-placeholder__icon"><InfoFilled /></el-icon>
    <span class="boxplot-placeholder__text">{{ placeholderText }}</span>
  </div>
  <div v-else ref="chartRef" class="chart-container" style="width: 100%; height: 500px" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import { formatAxisValue } from '../../../utils/chart-bar'

interface BoxPlotStats {
  min: number; q1: number; median: number; q3: number; max: number; outliers: number[]; count: number; raw_values?: number[]
}
interface BoxPlotData {
  param: string; overall?: BoxPlotStats; by_site?: Record<string, BoxPlotStats>; by_bin?: Record<string, BoxPlotStats>
}

const props = withDefaults(defineProps<{ data: BoxPlotData | null; title?: string; showJitter?: boolean; visible?: boolean; error?: string | null }>(), {
  showJitter: false,
  visible: true,
  error: null,
})
const { colors } = useEChartsTheme()

// 箱体/异常点固定直方图基准色（风格统一 2026-08-13，双主题恒定）；
// jitter 散点覆盖层保留主题系列色自适应
const boxColor = '#1E88E5'
const jitterColor = computed(() => colors.value.seriesColors[4])
const outlierColor = '#E53935'

const hasValidData = computed(() => {
  if (!props.data) return false
  const { overall, by_site, by_bin } = props.data
  if (overall && typeof overall.min === 'number' && Number.isFinite(overall.min)) return true
  if (by_site && Object.keys(by_site).length > 0) {
    const grp = by_site[Object.keys(by_site)[0]]
    if (grp && typeof grp.min === 'number' && Number.isFinite(grp.min)) return true
  }
  if (by_bin && Object.keys(by_bin).length > 0) {
    const grp = by_bin[Object.keys(by_bin)[0]]
    if (grp && typeof grp.min === 'number' && Number.isFinite(grp.min)) return true
  }
  return false
})

const placeholderText = computed(() => {
  if (props.error) return props.error
  if (!props.data) return '请先选择参数以查看箱线图'
  return '该参数无有效数值数据，无法绘制箱线图'
})

function buildOption() {
  if (!props.data) return {}
  const tc = colors.value.textColor
  const { overall, by_site, by_bin } = props.data
  const hasGroupedData = (by_site && Object.keys(by_site).length > 0) || (by_bin && Object.keys(by_bin).length > 0)
  const groupedData = by_site || by_bin || {}

  let categories: string[] = []
  let boxData: number[][] = []
  let outlierData: number[][] = []
  let jitterSeries: any[] = []
  let yMin = Infinity, yMax = -Infinity

  if (hasGroupedData) {
    const sortedKeys = Object.keys(groupedData).sort((a, b) => {
      const numA = parseFloat(a); const numB = parseFloat(b)
      if (!isNaN(numA) && !isNaN(numB)) return numA - numB
      return a.localeCompare(b)
    })
    categories = sortedKeys.map(key =>
      /^\d+(\.\d+)?$/.test(key) ? `Site ${key}` : key
    )
    sortedKeys.forEach((group, idx) => {
      const s = groupedData[group]
      if (!s || !Number.isFinite(s.min) || !Number.isFinite(s.max)) return
      boxData.push([s.min, s.q1, s.median, s.q3, s.max])
      if (Array.isArray(s.outliers)) {
        s.outliers.forEach(o => outlierData.push([idx, o]))
      }
      yMin = Math.min(yMin, s.min)
      yMax = Math.max(yMax, s.max)

      if (props.showJitter && s.raw_values && s.raw_values.length > 0) {
        jitterSeries.push({
          name: `${categories[idx]} 数据点`,
          type: 'scatter',
          data: s.raw_values.map((v: number) => [idx + (Math.random() - 0.5) * 0.3, v]),
          symbolSize: 3,
          itemStyle: { color: jitterColor.value, opacity: 0.25 },
          silent: true,
        })
      }
    })
  } else if (overall) {
    categories = [props.data.param]
    boxData.push([overall.min, overall.q1, overall.median, overall.q3, overall.max])
    if (Array.isArray(overall.outliers)) {
      overall.outliers.forEach(o => outlierData.push([0, o]))
    }
    yMin = overall.min
    yMax = overall.max

    if (props.showJitter && overall.raw_values && overall.raw_values.length > 0) {
      jitterSeries.push({
        name: '数据点',
        type: 'scatter',
        data: overall.raw_values.map((v: number) => [(Math.random() - 0.5) * 0.3, v]),
        symbolSize: 3,
        itemStyle: { color: jitterColor.value, opacity: 0.25 },
        silent: true,
      })
    }
  }

  if (boxData.length === 0 || !Number.isFinite(yMin) || !Number.isFinite(yMax)) {
    return {}
  }

  // Y-axis: focus on non-outlier range with padding
  const yRange = yMax - yMin
  const yPad = yRange > 0 ? yRange * 0.1 : Math.abs(yMax) * 0.1 || 1

  // X-axis name
  const xAxisName = by_site ? 'Site' : by_bin ? 'Bin' : ''

  return {
    title: {
      text: props.title || `Box Plot - ${props.data.param}`,
      left: 'center',
      textStyle: { fontSize: 15, fontWeight: 'bold', color: tc },
    },
    tooltip: {
      trigger: 'item',
      axisPointer: { type: 'shadow' },
      backgroundColor: colors.value.tooltipBg,
      borderColor: colors.value.tooltipBorder,
      textStyle: { color: colors.value.tooltipText },
    },
    grid: { left: '8%', right: '8%', bottom: '12%', top: '12%', containLabel: true },
    xAxis: {
      type: 'category',
      data: categories,
      boundaryGap: true,
      name: xAxisName,
      nameLocation: 'center',
      nameGap: 35,
      nameTextStyle: { color: tc, fontSize: 13, fontWeight: 500 },
      axisLine: { lineStyle: { color: colors.value.axisLineColor } },
      axisLabel: {
        rotate: categories.length > 10 ? 45 : 0,
        interval: 0,
        fontSize: 11,
        color: tc,
        fontWeight: 500,
        formatter: (val: string) => {
          // Show "Site X" label clearly
          if (val.length > 15) return val.substring(0, 12) + '...'
          return val
        },
      },
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      name: 'Value',
      min: yMin - yPad,
      max: yMax + yPad,
      nameTextStyle: { color: tc, fontSize: 12, fontWeight: 500 },
      axisLabel: { color: tc, fontSize: 9, formatter: formatAxisValue },
      splitLine: { lineStyle: { type: 'dashed', color: colors.value.splitLineColor } },
      splitArea: { show: false },
    },
    series: [
      {
        name: 'Box Plot',
        type: 'boxplot',
        data: boxData,
        itemStyle: {
          color: boxColor + '30',
          borderColor: boxColor,
          borderWidth: 2,
        },
        emphasis: {
          itemStyle: {
            color: boxColor + '50',
            borderColor: boxColor,
            borderWidth: 3,
          },
        },
        tooltip: {
          formatter: (p: any) => {
            const d = p?.data
            if (!Array.isArray(d) || d.length < 5) {
              return p?.name ? `<strong>${p.name}</strong>` : ''
            }
            const fmt = (n: any) => (typeof n === 'number' && Number.isFinite(n) ? n.toFixed(4) : 'N/A')
            return `<strong>${p.name}</strong><br/>` +
              `Max: ${fmt(d[4])}<br/>` +
              `Q3: ${fmt(d[3])}<br/>` +
              `Median: ${fmt(d[2])}<br/>` +
              `Q1: ${fmt(d[1])}<br/>` +
              `Min: ${fmt(d[0])}`
          },
        },
      },
      {
        name: 'Outliers',
        type: 'scatter',
        data: outlierData,
        itemStyle: { color: outlierColor, opacity: 0.8 },
        symbolSize: 7,
        symbol: 'circle',
        tooltip: { formatter: (p: any) => {
          if (!p?.value || !Array.isArray(p.value) || p.value.length < 2) return ''
          const v = p.value[1]
          return `异常值: ${typeof v === 'number' && Number.isFinite(v) ? v.toFixed(4) : 'N/A'}`
        }},
      },
      ...jitterSeries,
    ],
  }
}

const { chartRef } = useChart(buildOption, [() => props.data, () => props.title, () => props.showJitter, () => props.visible])
void chartRef // bound to <div ref="chartRef"> in template
</script>

<style scoped>
.chart-container { width: 100%; height: 100%; min-height: 400px; }
.boxplot-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  height: 500px;
  background: var(--bg-2);
  border: 1px dashed var(--border-2);
  border-radius: 6px;
  color: var(--text-2);
  font-size: 14px;
}
.boxplot-placeholder__icon {
  font-size: 18px;
  color: var(--text-2);
}
.boxplot-placeholder__text {
  color: var(--text-2);
}
</style>
