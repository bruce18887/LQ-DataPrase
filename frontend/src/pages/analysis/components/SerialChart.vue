<template>
  <div class="serial-chart-wrapper">
    <!-- 底部需容纳 轴名+图例+滑块 三层（≈135px），450px 会把绘图区挤到 ~240px；600px 时绘图区 ≈390px -->
    <div ref="chartRef" style="height: 600px" />
    <OutlierHintBar
      :mode="outlierHandling || 'off'"
      :outlier-info="data?.outlier_info ?? null"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme, getChartRenderer } from '../../../utils/echarts-theme'
import OutlierHintBar from './OutlierHintBar.vue'

const props = defineProps<{
  data: any
  outlierHandling?: 'clip' | 'exclude' | 'off'
}>()
const { colors } = useEChartsTheme()

const SITE_COLORS = [
  '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
  '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#5383e0',
]

// 大数据量（≥5000 点）启用 ECharts 官方 large 模式：每个系列只渲染 1 个
// path 元素（类型化数组 + 单次绘制），SVG/canvas 渲染器下均生效，避免
// 上万散点产生上万 DOM 节点拖垮首屏/缩放/切参数。
const pointCount = computed(() =>
  (props.data?.series_data || []).reduce(
    (sum: number, sd: { data?: unknown[] }) => sum + (sd.data?.length ?? 0), 0))
const isLarge = computed(() => pointCount.value >= 5000)

function buildOption() {
  if (!props.data) return {}
  const tc = colors.value.textColor
  const d = props.data
  const param = d.param || ''
  const unit = d.unit || ''
  const serialCol = d.serial_col || 'Serial'
  const continuousSerials = d.continuous_serials || []

  // Apply outlier clipping to y-axis (must precede point mapping: anchored
  // points are placed on the *visible* axis edges)
  const outlierInfo = d.outlier_info
  const handlingMode = props.outlierHandling || 'off'
  let yAxisMin = d.y_min
  let yAxisMax = d.y_max
  if (handlingMode !== 'off' && outlierInfo?.has_outliers) {
    yAxisMin = outlierInfo.lower_bound
    yAxisMax = outlierInfo.upper_bound
    const pad = (yAxisMax - yAxisMin) * 0.1
    yAxisMin -= pad
    yAxisMax += pad
  }

  /**
   * 点格式 [serial, value|null, is_fail, anchor]（无 bin 列的文件为 [serial, value]）。
   * anchor: 0=正常 1=无测量值 2=值>y_max 3=值<y_min。超界点锚定到可见轴边缘——
   * 显式 yAxis min/max 不会随数据扩展，不锚定的话巨大的 fail 值（如 Kelvin 10000）
   * 会被整段裁切，图上根本看不到 fail 点。无测量值（anchor=1）不绘制：画在 X 轴
   * 底部会被误读成 0 值数据点（其颗数仍计入副标题 Pass/Fail）。
   */
  function toPoint(p: number[], _idx: number) {
    const [s, v, isFail, anchor] = p
    const a = anchor ?? 0
    const fail = (isFail ?? 0) === 1
    if (a === 1) return null
    const y = a === 2 ? (yAxisMax ?? 0) : (a === 3 ? (yAxisMin ?? 0) : v)
    return {
      value: [s, y, isFail ?? 0, a],
      realY: v,
      isFail: fail,
      anchor: a,
    }
  }

  // 颜色按系列统一（图例一致；large 模式不支持逐点样式，必须放 series 级）
  const series: any[] = (d.series_data || []).map(
    (sd: { name: string; data: number[][]; type?: string; symbolSize?: number }, idx: number) => ({
      name: sd.name, type: sd.type || 'scatter',
      data: (sd.data || []).map((p: number[]) => toPoint(p, idx)).filter((pt: any) => pt !== null),
      symbolSize: sd.symbolSize || 6,
      itemStyle: { color: SITE_COLORS[idx % SITE_COLORS.length] },
      ...(isLarge.value ? { large: true } : {}),
    }),
  )

  for (const mark of d.marks || []) {
    series.push({ name: mark.name, type: mark.type || 'scatter', data: mark.data || [], markLine: mark.markLine, silent: true })
  }

  let subtext = unit ? `Unit: ${unit}` : ''
  if (d.lower_limit != null && d.upper_limit != null) {
    subtext += ` [${d.lower_limit.toFixed(4)}, ${d.upper_limit.toFixed(4)}]`
  }
  // 颗数口径与文件 bin 汇总一致（die 级、按最终 bin 判定，含无测量值/超界 fail）
  if (d.fail_count != null) {
    subtext += `  |  Pass: ${d.pass_count ?? '-'} · Fail: ${d.fail_count}`
  }

  return {
    // large 模式下上万 symbol 的入场/更新动画是纯开销，直接关闭
    animation: !isLarge.value,
    title: { text: `${param} Serial分布`, subtext, left: 'center', subtextStyle: { fontSize: 12 } },
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        const pt = p.data || {}
        const anchor = pt.anchor ?? 0
        let html = `${p.seriesName}<br/>${serialCol}: ${p.value[0]}<br/>结果: ${pt.isFail ? 'FAIL' : 'PASS'}`
        html += `<br/>Value: ${Number(pt.realY ?? p.value[1]).toFixed(4)}`
        if (anchor === 2) html += '<br/>超出显示范围（真实值偏大）'
        if (anchor === 3) html += '<br/>超出显示范围（真实值偏小）'
        return html
      },
    },
    // 底部三层各自独立、互不重叠（实测：ECharts 不会自动堆叠锚定容器底部的组件）：
    // grid.bottom 预留 x 轴标签/轴名区域 → dataZoom(bottom:45) 在中间层 → legend(bottom:5) 最底层
    legend: { data: series.map((s: any) => s.name), bottom: 5, type: 'scroll', textStyle: { color: tc } },
    toolbox: { feature: { saveAsImage: { name: `${param}_Serial分布` } } },
    xAxis: {
      type: 'category', data: continuousSerials, name: serialCol,
      nameTextStyle: { color: tc }, nameLocation: 'middle', nameGap: 30,
      axisLabel: { rotate: 45, interval: 'auto', color: tc },
    },
    yAxis: {
      type: 'value', name: unit ? `${param} (${unit})` : param,
      nameTextStyle: { color: tc }, nameLocation: 'middle', nameGap: 40,
      min: yAxisMin, max: yAxisMax, axisLabel: { formatter: (v: number) => v.toFixed(4), color: tc },
    },
    dataZoom: [
      // slider 提到图例上方：bottom:45（滑块高 30，图例高 25 在最底层 bottom:5）
      { type: 'slider', xAxisIndex: 0, start: 0, end: 100, bottom: 45 },
      { type: 'inside', xAxisIndex: 0 },
    ],
    // left/right 保持默认（15%/10%）：y 轴大数值标签（如 -12320.0079）宽度可达 ~70px，
    // 固定 60px 会被裁切；bottom 需容纳 轴名(≈35) + 图例(≈40) + 滑块(≈35)
    grid: { top: 60, bottom: 150 },
    series,
  }
}

// 大数据量强制 canvas（SVG 渲染器对 large 符号仍会为每点发射 DOM 元素；
// canvas 无 DOM 节点，官方推荐大数据散点必用 canvas）；小数据量跟随用户全局设置
const { chartRef } = useChart(
  buildOption,
  [() => props.data, () => props.outlierHandling],
  'chartRef',
  () => (isLarge.value ? 'canvas' : getChartRenderer()),
)
void chartRef // bound to <div ref="chartRef"> in template
</script>
