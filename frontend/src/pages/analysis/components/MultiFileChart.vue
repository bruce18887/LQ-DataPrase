<template>
  <div ref="chartRef" class="chart-container" />
</template>

<script setup lang="ts">
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import { clampBarValue, formatPercent } from '../../../utils/chart-bar'

const props = defineProps<{
  /** /analysis/multi_lot/ 带 param 的响应 */
  lotData: any
  chartConfig: string[]
  barWidthPercent: number
  /** file_id → 自定义图例名 */
  fileNames: Record<number, string>
  selectedParam: string
}>()

const { colors } = useEChartsTheme()

function displayName(lot: any): string {
  return props.fileNames[lot.file_id] || lot.name || `File ${lot.file_id}`
}

/** 智能格式化 X 轴刻度：整数不显示小数，非整数最多 4 位 */
function formatAxisValue(v: number): string {
  if (Number.isInteger(v)) return v.toString()
  const s = v.toFixed(4)
  return s.replace(/\.?0+$/, '')
}

/** 计算正态分布概率密度函数 */
function normalPDF(x: number, mean: number, std: number): number {
  if (std === 0) return 0
  return (1 / (std * Math.sqrt(2 * Math.PI))) * Math.exp(-0.5 * ((x - mean) / std) ** 2)
}

function buildOption() {
  const r = props.lotData
  if (!r || !Array.isArray(r.lot_data) || r.lot_data.length === 0) return {}
  const tc = colors.value.textColor
  const lots: any[] = r.lot_data
  const showLimit = props.chartConfig.includes('limit')
  const showNormal = props.chartConfig.includes('normal')
  const binCenters: number[] = r.bin_centers || []

  const series: any[] = []
  const legendData: string[] = []

  // 添加柱状图系列（每个文件独立颜色，显示百分比标签）
  for (const lot of lots) {
    const dn = displayName(lot)
    legendData.push(dn)
    series.push({
      name: dn,
      type: 'bar',
      // 小百分比（如 0.002%）钳制到最小可见柱高，真实值存 data[2] 供 tooltip/标签
      data: lot.bar_data.map((d: number[]) => [d[0], clampBarValue(d[1]), d[1]]),
      itemStyle: { color: lot.color },
      barWidth: `${props.barWidthPercent}%`,
      barGap: '10%',
      label: {
        show: true,
        position: 'top',
        formatter: (params: any) => {
          const real = params.data?.[2] ?? params.data?.[1]
          return real > 0 ? `${formatPercent(real)}%` : ''
        },
        fontSize: 10,
        color: lot.color,
        fontWeight: 'bold',
      },
    })
  }

  // Limit 线：每个文件独立图例
  if (showLimit) {
    for (const lot of lots) {
      const dn = displayName(lot)
      const mk: any[] = []
      const upperLimit = lot.display_upper ?? lot.upper_limit
      const lowerLimit = lot.display_lower ?? lot.lower_limit
      if (upperLimit != null) {
        mk.push({
          xAxis: upperLimit,
          lineStyle: { color: lot.color, width: 3, type: 'dashed' },
          label: {
            show: true,
            formatter: `${dn} USL`,
            position: 'end',
            color: lot.color,
            fontSize: 10,
            fontWeight: 'bold',
          },
        })
      }
      if (lowerLimit != null) {
        mk.push({
          xAxis: lowerLimit,
          lineStyle: { color: lot.color, width: 3, type: 'dashed' },
          label: {
            show: true,
            formatter: `${dn} LSL`,
            position: 'end',
            color: lot.color,
            fontSize: 10,
            fontWeight: 'bold',
          },
        })
      }
      if (mk.length) {
        const limitX = upperLimit ?? lowerLimit ?? binCenters[0]
        series.push({
          name: `${dn} 规格限`,
          type: 'scatter',
          data: [[limitX, 0]],
          symbol: 'circle',
          symbolSize: 0,
          itemStyle: { color: lot.color },
          markLine: { symbol: 'none', precision: 4, data: mk },
        })
        legendData.push(`${dn} 规格限`)
      }
    }
  }

  // 正态分布曲线：每个文件独立颜色
  if (showNormal) {
    for (const lot of lots) {
      const dn = displayName(lot)
      if (lot.std > 0 && binCenters.length > 0) {
        // 生成平滑的正态分布曲线
        const xMin = binCenters[0]
        const xMax = binCenters[binCenters.length - 1]
        const step = (xMax - xMin) / 100
        const normalData: [number, number][] = []
        for (let x = xMin; x <= xMax; x += step) {
          normalData.push([x, normalPDF(x, lot.mean, lot.std)])
        }
        series.push({
          name: `${dn} 正态分布`,
          type: 'line',
          data: normalData,
          smooth: true,
          lineStyle: { color: lot.color, width: 3, type: 'dotted' },
          itemStyle: { color: lot.color },
          symbol: 'none',
          yAxisIndex: 1, // 使用独立的概率密度Y轴
          z: 10,
        })
        legendData.push(`${dn} 正态分布`)
      }
    }
  }

  const titleText = `${props.selectedParam}  ${r.global_mean != null ? `(μ=${r.global_mean})` : ''}`

  // 构建Y轴配置
  const yAxisConfig: any[] = [
    {
      type: 'value',
      name: '百分比 (%)',
      nameTextStyle: { color: 'var(--color-primary, #1E88E5)', fontWeight: 'bold' },
      position: 'left',
      min: 0,
      axisLabel: { formatter: '{value}%', color: 'var(--color-primary, #1E88E5)' },
      axisLine: { show: true, lineStyle: { color: 'var(--color-primary, #1E88E5)' } },
    },
  ]

  // 如果显示正态分布曲线，添加概率密度Y轴
  if (showNormal) {
    yAxisConfig.push({
      type: 'value',
      name: '概率密度',
      nameTextStyle: { color: 'var(--color-warning, #F57F17)', fontWeight: 'bold' },
      position: 'right',
      min: 0,
      axisLabel: { formatter: (v: number) => v.toExponential(2), color: 'var(--color-warning, #F57F17)' },
      axisLine: { show: true, lineStyle: { color: 'var(--color-warning, #F57F17)' } },
      splitLine: { show: false },
    })
  }

  return {
    title: {
      text: titleText,
      left: 'center',
      top: 6,
      textStyle: { fontSize: 15, fontWeight: 'bold', color: tc },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const items = Array.isArray(params) ? params : [params]
        if (!items.length) return ''
        let html = `值: ${Number(items[0].data?.[0]).toFixed(4)}<br/>`
        for (const p of items) {
          if (p.data && p.data[1] != null && p.seriesType === 'bar') {
            // data[1] 是钳制后的渲染值，data[2] 才是真实百分比
            const real = p.data[2] ?? p.data[1]
            html += `${p.seriesName}: ${formatPercent(Number(real))}%<br/>`
          }
        }
        return html
      },
    },
    legend: { data: legendData, top: 'bottom', type: 'scroll', textStyle: { color: tc } },
    toolbox: { feature: { saveAsImage: { name: `${props.selectedParam}_多文件对比` } } },
    grid: { top: 55, bottom: 70, left: 55, right: showNormal ? 80 : 55 },
    xAxis: {
      type: 'value',
      min: binCenters.length > 0 ? binCenters[0] : r.chart_min,
      max: binCenters.length > 0 ? binCenters[binCenters.length - 1] : r.chart_max,
      axisLabel: {
        rotate: 45,
        show: true,
        interval: 0,
        fontSize: 9,
        formatter: formatAxisValue,
        color: tc,
      },
      splitNumber: 24,
    },
    yAxis: yAxisConfig,
    series,
  }
}

const { chartRef } = useChart(buildOption, [
  () => props.lotData,
  () => props.chartConfig,
  () => props.barWidthPercent,
  () => props.fileNames,
  () => props.selectedParam,
])
void chartRef // bound to <div ref="chartRef"> in template
</script>

<style scoped>
.chart-container {
  width: 100%;
  height: 100%;
  min-height: 480px;
}
</style>
