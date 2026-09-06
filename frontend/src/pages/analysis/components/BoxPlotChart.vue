<!-- frontend/src/pages/analysis/components/BoxPlotChart.vue -->
<template>
  <!-- No-data placeholder: avoid ECharts init with min=Infinity/max=-Infinity
       which can throw via Vue's async update chain (emitsOptions null). -->
  <div v-if="!hasValidData" class="boxplot-placeholder">
    <el-icon class="boxplot-placeholder__icon"><InfoFilled /></el-icon>
    <span class="boxplot-placeholder__text">{{ placeholderText }}</span>
  </div>
  <div v-else ref="chartRef" class="chart-container" />
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

const props = withDefaults(defineProps<{ data: BoxPlotData | null; title?: string; showJitter?: boolean; visible?: boolean; error?: string | null; /** 分组来源：决定数值类目的前缀（by_bin 曾被错标成 "Site N"） */ groupKind?: 'site' | 'bin' }>(), {
  showJitter: false,
  visible: true,
  error: null,
  groupKind: 'site',
})
const { colors } = useEChartsTheme()

// 箱体/离群点跟随主题（不再写死 #1E88E5/#E53935，对齐原型 C.series[0] / C.error）：
// 箱体用系列主色（浅=蓝 / 暗=金），离群点用语义红，二者颜色分明
const boxColor = computed(() => colors.value.seriesColors[0])
const outlierColor = computed(() => colors.value.errorColor)

const groupOk = (grp?: BoxPlotStats) =>
  !!grp && typeof grp.min === 'number' && Number.isFinite(grp.min)

// 只要有**任一**有效组即可渲染（旧实现只看第一组：第一组全 NaN 会把整图
// 误判成无数据）
const hasValidData = computed(() => {
  if (!props.data) return false
  const { overall, by_site, by_bin } = props.data
  if (groupOk(overall)) return true
  const grouped = by_site ?? by_bin
  if (grouped && Object.keys(grouped).length > 0) {
    return Object.values(grouped).some(groupOk)
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
  let yMin = Infinity, yMax = -Infinity

  if (hasGroupedData) {
    const sortedKeys = Object.keys(groupedData).sort((a, b) => {
      const numA = parseFloat(a); const numB = parseFloat(b)
      if (!isNaN(numA) && !isNaN(numB)) return numA - numB
      return a.localeCompare(b)
    })
    // 全 NaN 组（后端 NaN→null → min/max 非有限）必须**整组剔除且不占类别
    // 位**：旧写法跳过箱体但保留原始 idx，箱体紧缩前移而异常点/jitter 钉在
    // 原下标，画到别的 Site 名下（2026-09-05 审查 M4）
    const validKeys = sortedKeys.filter((key) => groupOk(groupedData[key]))
    const prefix = props.groupKind === 'bin' ? 'Bin' : 'Site'
    categories = validKeys.map(key =>
      /^\d+(\.\d+)?$/.test(key) ? `${prefix} ${key}` : key
    )
    validKeys.forEach((group, idx) => {
      const s = groupedData[group]
      boxData.push([s.min, s.q1, s.median, s.q3, s.max])
      // 离群点横向抖动落在本组名下（对齐原型）；仅在「离群点」勾选时随 series 显示
      if (Array.isArray(s.outliers)) {
        s.outliers.forEach(o => outlierData.push([idx + (Math.random() - 0.5) * 0.3, o]))
      }
      yMin = Math.min(yMin, s.min)
      yMax = Math.max(yMax, s.max)
    })
  } else if (overall) {
    categories = [props.data.param]
    boxData.push([overall.min, overall.q1, overall.median, overall.q3, overall.max])
    if (Array.isArray(overall.outliers)) {
      overall.outliers.forEach(o => outlierData.push([(Math.random() - 0.5) * 0.3, o]))
    }
    yMin = overall.min
    yMax = overall.max
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
          color: boxColor.value + '30',
          borderColor: boxColor.value,
          borderWidth: 2,
        },
        emphasis: {
          itemStyle: {
            color: boxColor.value + '50',
            borderColor: boxColor.value,
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
            // d[0]/d[4] 是「须端」（非离群范围的 min/max），不叫「最小/最大值」（对齐统计表口径）
            return `<strong>${p.name}</strong><br/>` +
              `上须端: ${fmt(d[4])}<br/>` +
              `Q3: ${fmt(d[3])}<br/>` +
              `Median: ${fmt(d[2])}<br/>` +
              `Q1: ${fmt(d[1])}<br/>` +
              `下须端: ${fmt(d[0])}`
          },
        },
      },
      // 「离群点」勾选时才显示：真实离群值横向抖动、语义红（原型 drawBox 口径）
      ...(props.showJitter ? [{
        name: '离群点',
        type: 'scatter',
        data: outlierData,
        itemStyle: { color: outlierColor.value, opacity: 0.7 },
        symbolSize: 6,
        symbol: 'circle',
        tooltip: { formatter: (p: any) => {
          if (!p?.value || !Array.isArray(p.value) || p.value.length < 2) return ''
          const v = p.value[1]
          return `离群点: ${typeof v === 'number' && Number.isFinite(v) ? v.toFixed(4) : 'N/A'}`
        }},
      }] : []),
    ],
  }
}

const { chartRef } = useChart(buildOption, [() => props.data, () => props.title, () => props.showJitter, () => props.visible])
void chartRef // bound to <div ref="chartRef"> in template
</script>

<style scoped>
.chart-container { width: 100%; height: 100%; min-height: 0; }
.boxplot-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  height: 100%;
  min-height: 200px;
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
