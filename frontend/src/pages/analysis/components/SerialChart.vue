<template>
  <div class="serial-chart-wrapper">
    <!-- 多候选序列列（Serial_No 与 Dut_No 并存等）：显示选择器供用户手动切换，
         单选 = 自动检测（优先级 Serial_No > Dut_No > PART_ID） -->
    <div v-if="showSelector" class="serial-col-selector">
      <span class="serial-col-selector__label">序列列</span>
      <el-select
        :model-value="activeSerialCol"
        size="small"
        style="width: 200px"
        @update:model-value="(v: string) => emit('update:serialCol', v)"
      >
        <el-option
          v-for="c in serialCandidates"
          :key="c"
          :label="c"
          :value="c"
        />
      </el-select>
    </div>
    <!-- 高度由外层 .chart-wrapper--serial（单文件 440px）决定；本容器 flex 列，
         画布 flex:1 吃掉选择器/离群条以外的空间。底部三层需容纳 轴名+图例+滑块
         （grid.bottom≈150），过矮会挤压绘图区 -->
    <div ref="chartRef" class="serial-canvas" />
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
import { formatAxisValue, getSiteColors8, buildChartToolbox } from '../../../utils/chart-bar'
import OutlierHintBar from './OutlierHintBar.vue'

const props = withDefaults(defineProps<{
  data: any
  outlierHandling?: 'clip' | 'exclude' | 'off'
  /** 用户显式选择的序列列（空串 = 自动检测） */
  serialCol?: string
  /** 后端返回的候选列（>1 时显示选择器） */
  serialCandidates?: string[]
}>(), { serialCol: '', serialCandidates: () => [] })
const emit = defineEmits<{ (e: 'update:serialCol', value: string): void }>()
const { colors, isDark } = useEChartsTheme()

// 选择器显示当前生效的列：显式选择优先，否则回退到后端自动检测结果
const activeSerialCol = computed(() => props.serialCol || props.data?.serial_col || '')
const showSelector = computed(() => (props.serialCandidates?.length ?? 0) > 1)

// 大数据量（≥5000 点）启用 ECharts 官方 large 模式：每个系列只渲染 1 个
// path 元素（类型化数组 + 单次绘制），SVG/canvas 渲染器下均生效，避免
// 上万散点产生上万 DOM 节点拖垮首屏/缩放/切参数。
const pointCount = computed(() =>
  (props.data?.series_data || []).reduce(
    (sum: number, sd: { data?: unknown[] }) => sum + (sd.data?.length ?? 0), 0))
const isLarge = computed(() => pointCount.value >= 5000)

// —— 重叠可读性（spec 2026-09-12 §1.1）：按总点数自适应点径/透明度，
// 大文件散点不再糊成实色带；slider 覆盖在后续任务接入 ——
function autoPointStyle(count: number): { size: number; opacity: number } {
  if (count < 5000) return { size: 6, opacity: 0.85 }
  if (count <= 20000) return { size: 4, opacity: 0.5 }
  return { size: 3, opacity: 0.35 }
}
const autoStyle = computed(() => autoPointStyle(pointCount.value))
const effSize = computed(() => autoStyle.value.size)
const effOpacity = computed(() => autoStyle.value.opacity)

function buildOption() {
  if (!props.data) return {}
  const tc = colors.value.textColor
  const d = props.data
  const param = d.param || ''
  const unit = d.unit || ''
  const serialCol = d.serial_col || 'Serial'
  const continuousSerials = d.continuous_serials || []

  // category 轴上数值 x 会被 ECharts 当作**索引**而不是类别名匹配：序列号从
  // 1 开始（本项目 e2e fixture 即 Serial_No=1..6）时每个点右移一格，末颗 die
  // 画出绘图区外；有序号空洞时错位量 = 最小序列号，tooltip 的真实序列号与
  // 轴标签互相矛盾。统一映射 serial → 轴下标；字符串序列号路径本就按 label
  // 匹配，不走此映射。映射不到的值（不应发生）保持原值兜底。
  const serialIndex = new Map<number, number>()
  continuousSerials.forEach((s: unknown, i: number) => {
    if (typeof s === 'number') serialIndex.set(s, i)
  })

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
  function toPoint(p: number[], siteName: string) {
    const [s, v, isFail, anchor] = p
    const a = anchor ?? 0
    const fail = (isFail ?? 0) === 1
    if (a === 1) return null
    const y = a === 2 ? (yAxisMax ?? 0) : (a === 3 ? (yAxisMin ?? 0) : v)
    const x = typeof s === 'number' ? (serialIndex.get(s) ?? s) : s
    return {
      value: [x, y, isFail ?? 0, a],
      realY: v,
      realSerial: s,
      isFail: fail,
      anchor: a,
      site: siteName,
    }
  }

  // —— pass/fail 拆分：fail/超界点抽到置顶强调层（spec §1.3；large 模式
  // 不支持逐点样式，强调只能靠独立系列）——
  const siteSeriesRaw: { name: string; data: number[][] }[] = d.series_data || []
  const siteColors = getSiteColors8(isDark.value)
  const passData: any[][] = siteSeriesRaw.map(() => [])
  const failDataBySite: any[][] = siteSeriesRaw.map(() => [])
  siteSeriesRaw.forEach((sd, idx) => {
    ;(sd.data || []).forEach((p: number[]) => {
      const pt = toPoint(p, sd.name)
      if (!pt) return
      if (pt.isFail || pt.anchor !== 0) failDataBySite[idx].push(pt)
      else passData[idx].push(pt)
    })
  })
  const failAll = failDataBySite.flat()
  // 绘制序：最密垫底（spec §1.2）——按点数降序赋 z；数组序保持 site 升序
  // （图例顺序与直方图等其它图表一致的既有约定）。密度口径取**实际绘制的
  // pass 点数**（fail/超界点已抽到独立置顶层，不参与 site 带层叠），与视觉
  // 上的散点带浓淡一致；用原始点数会在 fail/无值点分布不均时排出反的层叠序。
  const counts = passData.map((pd) => pd.length)
  const zOfSite = new Map<number, number>()
  counts
    .map((_, i) => i)
    .sort((a, b) => counts[b] - counts[a])
    .forEach((idx, rank) => zOfSite.set(idx, 2 + rank))

  const series: any[] = siteSeriesRaw.map((sd, idx) => ({
    name: sd.name, type: 'scatter',
    data: passData[idx],
    symbolSize: effSize.value,
    itemStyle: { color: siteColors[idx % 8], opacity: effOpacity.value },
    z: zOfSite.get(idx),
    ...(isLarge.value ? { large: true } : {}),
  }))
  if (failAll.length) {
    series.push({
      name: 'Fail/超界', type: 'scatter', data: failAll,
      symbolSize: effSize.value + 2,
      itemStyle: { color: colors.value.errorColor, opacity: 1 },
      // 高于所有 site 系列（site z = 2..N+1）；site 数 >8 时 10 不够，随 N 抬
      z: Math.max(10, 2 + siteSeriesRaw.length),
      ...(isLarge.value ? { large: true } : {}),
    })
  }

  // marks（LSL/USL/σ 参考线）图例 marker 与线色严格对应：itemStyle.color 取
  // 线色（后端 serial_distribution 每条线颜色一致），缺省时回退主题色板。
  // 参考线恒在数据带之上：markLine 的 z 取自身模型（echarts 默认 5），不继承
  // 宿主 series 的 z，故须在 markLine 内显式抬到 20（site z = 2..N+1，N≥4 时
  // 只靠 series z 会被半透明散点带压住）。
  for (const mark of d.marks || []) {
    const lineColor = mark.markLine?.data?.[0]?.lineStyle?.color
    series.push({
      name: mark.name, type: mark.type || 'scatter', data: mark.data || [],
      markLine: mark.markLine ? { ...mark.markLine, z: 20 } : mark.markLine,
      silent: true, z: 20,
      ...(lineColor ? { itemStyle: { color: lineColor } } : {}),
    })
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
    title: { text: `${param} Serial分布`, subtext, left: 'center', textStyle: { fontSize: 15, fontWeight: 'bold', color: tc }, subtextStyle: { fontSize: 12 } },
    tooltip: {
      trigger: 'item',
      backgroundColor: colors.value.tooltipBg,
      borderColor: colors.value.tooltipBorder,
      textStyle: { color: colors.value.tooltipText },
      formatter: (p: any) => {
        const pt = p.data || {}
        const anchor = pt.anchor ?? 0
        // value[0] 是轴下标（category 映射），真实序列号在 realSerial
        let html = `${p.seriesName}`
        if (p.seriesName === 'Fail/超界' && pt.site) html += ` · ${pt.site}`
        html += `<br/>${serialCol}: ${pt.realSerial ?? p.value[0]}<br/>结果: ${pt.isFail ? 'FAIL' : 'PASS'}`
        html += `<br/>Value: ${Number(pt.realY ?? p.value[1]).toFixed(4)}`
        if (anchor === 2) html += '<br/>超出显示范围（真实值偏大）'
        if (anchor === 3) html += '<br/>超出显示范围（真实值偏小）'
        return html
      },
    },
    // 图例在最底（与直方图同款：底部只留 图例 + 轴标签，无 dataZoom 滑块占位）
    legend: { data: series.map((s: any) => s.name), bottom: 5, type: 'scroll', textStyle: { color: tc } },
    toolbox: buildChartToolbox({ name: `${param}_Serial分布` }),
    xAxis: {
      type: 'category', data: continuousSerials, name: serialCol,
      nameTextStyle: { color: tc }, nameLocation: 'middle', nameGap: 30,
      axisLine: { lineStyle: { color: colors.value.axisLineColor } },
      axisLabel: { rotate: 45, interval: 'auto', fontSize: 9, color: tc },
    },
    yAxis: {
      type: 'value', name: unit ? `${param} (${unit})` : param,
      nameTextStyle: { color: tc }, nameLocation: 'middle', nameGap: 40,
      min: yAxisMin, max: yAxisMax,
      axisLine: { lineStyle: { color: colors.value.axisLineColor } },
      axisLabel: { formatter: formatAxisValue, fontSize: 9, color: tc },
    },
    // 缩放改为纯 inside（滚轮/拖拽平移），去掉锚底的 slider：slider 与图例同锚容器
    // 底、矮面板下会挤没 X 轴。inside 缩放不占布局 → 与直方图同款、resize 纯比例缩放。
    dataZoom: [
      { type: 'inside', xAxisIndex: 0 },
    ],
    // grid.bottom 收小（图例 + 轴标签，无滑块），绘图区随容器高等比缩放、X 轴不被遮
    grid: { top: 60, bottom: 85 },
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

<style scoped>
/* 填满外层 .chart-wrapper--serial；选择器与离群条为固定高度，画布 flex:1 占剩余 */
.serial-chart-wrapper {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
}
.serial-canvas {
  flex: 1;
  min-height: 0;
  width: 100%;
}
.serial-col-selector {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-bottom: 8px;
}
.serial-col-selector__label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
