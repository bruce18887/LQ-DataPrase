<template>
  <div class="serial-chart-wrapper">
    <!-- 序列列选择器保留内联（点径/透明度/按 Site 拆分已移入标题栏齿轮面板，2026-09-13） -->
    <div v-if="showSelector" class="serial-header">
      <!-- 多候选序列列（Serial_No 与 Dut_No 并存等）：显示选择器供用户手动切换，
           单选 = 自动检测（优先级 Serial_No > Dut_No > PART_ID） -->
      <div class="serial-col-selector">
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
  /** 按 Site 拆分小多图（状态由父级 useSerialChartSettings 持有） */
  splitBySite?: boolean
  /** 生效点径（自动档或手动覆盖后） */
  symbolSize?: number
  /** 生效透明度 0-1 */
  opacity?: number
}>(), { serialCol: '', serialCandidates: () => [], splitBySite: false, symbolSize: 6, opacity: 0.85 })
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

// 点径/透明度/按 Site 拆分的状态与「自动档」逻辑上提到 useSerialChartSettings
// （齿轮面板在标题栏、由 SingleParamTab 渲染），本组件只消费 props.symbolSize/
// props.opacity/props.splitBySite。

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

  // —— Y 轴范围：默认按数据自适应（2026-09-13）——
  // 后端 y_min/y_max = 规格限 ±10% padding；规格限离数据很远时（如某参数 USL/LSL
  // 远于数据带），整个绘图区被撑成「数据窄带 + 大片空白」。改为由 anchor==0 点的
  // 实际值算紧凑范围，规格限/σ 线超出视野时在 markLine 层贴边钳制并加 ↑/↓。
  //
  // 不变量（勿破坏）：后端 _anchor() 以 [spec_lower, spec_upper]±10% 标记 anchor，
  // 而 anchor==0 的定义就是落在该范围内 → 前端自适应范围必是后端范围的**子集**。
  // 因此 anchor=2/3 点仍必落在自适应范围之外、贴边钳制继续正确；anchor=0 点永不
  // 被裁掉。若把 marks（规格限/σ）的绝对值并入范围，此性质即被破坏。
  const outlierInfo = d.outlier_info
  const handlingMode = props.outlierHandling || 'off'

  /** 一组原始点（[serial, value, is_fail, anchor]）→ 该组 anchor==0 值的紧凑范围 */
  function rangeOfPoints(points: number[][], fbLo: number, fbHi: number): [number, number] {
    let mn = Infinity
    let mx = -Infinity
    for (const p of points) {
      if ((p[3] ?? 0) !== 0) continue // 超界点锚到轴边，不参与范围计算（否则极值炸开）
      const v = p[1]
      if (typeof v !== 'number' || !Number.isFinite(v)) continue
      if (v < mn) mn = v
      if (v > mx) mx = v
    }
    if (mn === Infinity) return [fbLo, fbHi] // 无有效值 → 回退后端范围
    if (mx > mn) {
      const pad = (mx - mn) * 0.08
      return [mn - pad, mx + pad]
    }
    const dlt = Math.max(Math.abs(mx) * 0.05, 1e-9) // 单值/全等退化
    return [mn - dlt, mx + dlt]
  }

  const siteSeriesRaw: { name: string; data: number[][] }[] = d.series_data || []
  const siteColors = getSiteColors8(isDark.value)
  const split = props.splitBySite && siteSeriesRaw.length >= 2
  const laneCount = split ? siteSeriesRaw.length : 1

  // 离群处理开启且确有异常值：沿用 IQR 栅栏范围（有意的裁剪口径，不改成数据自适应，
  // 否则「异常值处理」的视觉语义丢失）。否则按数据自适应。
  const useIqrRange = handlingMode !== 'off' && outlierInfo?.has_outliers
  let iqrBounds: [number, number] | null = null
  if (useIqrRange) {
    const pad = (outlierInfo.upper_bound - outlierInfo.lower_bound) * 0.1
    iqrBounds = [outlierInfo.lower_bound - pad, outlierInfo.upper_bound + pad]
  }
  // 合并：全体 anchor=0 值并集；拆分：每 lane 各自贴合其数据范围
  const laneBounds: [number, number][] = laneCount === 1
    ? [iqrBounds ?? rangeOfPoints(siteSeriesRaw.flatMap((sd) => sd.data || []), d.y_min, d.y_max)]
    : siteSeriesRaw.map((sd) => iqrBounds ?? rangeOfPoints(sd.data || [], d.y_min, d.y_max))

  /**
   * 点格式 [serial, value|null, is_fail, anchor]（无 bin 列的文件为 [serial, value]）。
   * anchor: 0=正常 1=无测量值 2=值>后端 y_max 3=值<后端 y_min。超界点锚定到**可见**
   * 轴边缘——自适应 yAxis min/max 不随数据扩展，不锚定的话巨大的 fail 值（如 Kelvin
   * 10000）会被整段裁切，图上根本看不到 fail 点。无测量值（anchor=1）不绘制：画在
   * X 轴底部会被误读成 0 值数据点（其颗数仍计入副标题 Pass/Fail）。
   */
  function toPoint(p: number[], lo: number, hi: number) {
    const [s, v, isFail, anchor] = p
    const a = anchor ?? 0
    const fail = (isFail ?? 0) === 1
    if (a === 1) return null
    const y = a === 2 ? hi : (a === 3 ? lo : v)
    const x = typeof s === 'number' ? (serialIndex.get(s) ?? s) : s
    return {
      value: [x, y, isFail ?? 0, a],
      realY: v,
      realSerial: s,
      isFail: fail,
      anchor: a,
    }
  }

  // —— fail/超界点不拆独立强调层：随 Site 系列着色（2026-09-13 按用户反馈回退
  // §1.3 强调层：并集层名易被误读为「红点=超界」）；anchor=1（无值）仍不绘制 ——
  const siteData: any[][] = siteSeriesRaw.map((sd, idx) => {
    const bounds = laneBounds[split ? idx : 0]
    return (sd.data || [])
      .map((p: number[]) => toPoint(p, bounds[0], bounds[1]))
      .filter((pt: any) => pt !== null)
  })
  // 绘制序：最密垫底（spec §1.2）——按点数降序赋 z；数组序保持 site 升序
  // （图例顺序与直方图等其它图表一致的既有约定）。密度口径取实际绘制点数
  // （fail/超界点随 Site 系列着色、参与带层叠），与视觉上的散点带浓淡一致。
  const counts = siteData.map((sd) => sd.length)
  const zOfSite = new Map<number, number>()
  counts
    .map((_, i) => i)
    .sort((a, b) => counts[b] - counts[a])
    .forEach((idx, rank) => zOfSite.set(idx, 2 + rank))

  const series: any[] = siteSeriesRaw.map((sd, idx) => ({
    name: sd.name, type: 'scatter',
    data: siteData[idx],
    ...(split ? { xAxisIndex: idx, yAxisIndex: idx } : {}),
    symbolSize: props.symbolSize,
    itemStyle: { color: siteColors[idx % 8], opacity: props.opacity },
    ...(split ? {} : { z: zOfSite.get(idx) }),
    ...(isLarge.value ? { large: true } : {}),
  }))

  let grids: any[]
  let xAxes: any[]
  let yAxes: any[]
  let dataZoom: any[]
  // —— 轴/网格：合并单面板；拆分 N 条 lane（每 lane 贴合自身数据范围，2026-09-13）——
  if (split) {
    // 拆分小多图：纵向可用区从旧的 60% 提到 68%（lane 更高）；bottom 22% 需容纳
    // 末 lane 的 45° X 标签 + 轴名(nameGap 30) + 图例(绝对 bottom:5，否则会压轴名)
    const topStart = 10
    const bottomReserve = 22
    const lanePct = (100 - topStart - bottomReserve) / laneCount
    const laneGap = Math.min(1.5, lanePct * 0.15)
    grids = siteSeriesRaw.map((_, i) => ({
      left: 60, right: 16,
      top: `${topStart + i * lanePct}%`,
      height: `${Math.max(lanePct - laneGap, 3)}%`,
    }))
    xAxes = siteSeriesRaw.map((_, i) => xAxisDef(i, i === laneCount - 1))
    yAxes = siteSeriesRaw.map((sd, i) => yAxisDef(i, laneBounds[i], sd.name, siteColors[i % 8]))
    dataZoom = [{ type: 'inside', xAxisIndex: siteSeriesRaw.map((_, i) => i) }]
  } else {
    // 合并单面板：显式收紧四边留白（旧实现 left/right 走 ECharts 默认 10%，
    // 超宽屏下左右各浪费上百像素）；right 留出 markLine 的 end 位置标签
    grids = [{ left: 60, right: 48, top: 58, bottom: 68 }]
    xAxes = [xAxisDef(0, true)]
    yAxes = [yAxisDef(0, laneBounds[0], null)]
    dataZoom = [{ type: 'inside', xAxisIndex: [0] }]
  }

  /** markLine 贴边钳制：超出该 lane 可见范围的参考线钉到轴边并加 ↑/↓（副标题
      已显示数值 LSL/USL，箭头只提示「贴边且真实值更外」）。不改 d.marks 本体。 */
  function clampMarkLine(ml: any, lo: number, hi: number) {
    if (!ml?.data) return ml
    return {
      ...ml,
      data: ml.data.map((it: any) => {
        if (it.yAxis == null) return it
        let v = it.yAxis
        let suf = ''
        if (v > hi) { v = hi; suf = ' ↑' } else if (v < lo) { v = lo; suf = ' ↓' }
        if (!suf) return it
        const f = it.label?.formatter
        return {
          ...it,
          yAxis: v,
          label: it.label ? { ...it.label, formatter: `${typeof f === 'string' ? f : ''}${suf}` } : it.label,
        }
      }),
    }
  }

  function xAxisDef(i: number, showLabel: boolean) {
    return {
      type: 'category', data: continuousSerials, gridIndex: i,
      axisLine: { lineStyle: { color: colors.value.axisLineColor } },
      ...(showLabel
        ? {
            name: serialCol, nameTextStyle: { color: tc },
            nameLocation: 'middle', nameGap: 30,
            axisLabel: { rotate: 45, interval: 'auto', fontSize: 9, color: tc },
          }
        : { axisLabel: { show: false }, axisTick: { show: false } }),
    }
  }
  function yAxisDef(i: number, bounds: [number, number], laneName: string | null, laneColor?: string) {
    return {
      type: 'value', gridIndex: i, min: bounds[0], max: bounds[1],
      axisLine: { lineStyle: { color: colors.value.axisLineColor } },
      axisLabel: { formatter: formatAxisValue, fontSize: 9, color: tc },
      ...(laneName
        ? {
            name: laneName, nameLocation: 'middle', nameGap: 48, nameRotate: 90,
            nameTextStyle: { color: laneColor, fontSize: 10, fontWeight: 'bold' },
          }
        : {
            name: unit ? `${param} (${unit})` : param,
            nameTextStyle: { color: tc }, nameLocation: 'middle', nameGap: 40,
          }),
    }
  }

  // 参考线 z 恒高于 site 层（2..N+1）：N≤16 时 20 够，
  // 更大 site 数随 N 抬升（极端边界防御）
  const markZ = Math.max(20, siteSeriesRaw.length + 4)
  // 参考线按 lane 复制（同名系列，图例单项控制全 lane）
  for (const mark of d.marks || []) {
    const lineColor = mark.markLine?.data?.[0]?.lineStyle?.color
    for (let lane = 0; lane < laneCount; lane++) {
      series.push({
        name: mark.name, type: mark.type || 'scatter', data: mark.data || [],
        // markLine 的 z 不继承宿主 series（ECharts MarkerView 取 MarkLineModel 自身 z，
        // 默认 5）——site z 可达 N+1，必须显式抬到 markZ 保证参考线恒在数据带之上。
        // 参考线按本 lane 的可见范围贴边钳制（超出则钉到轴边 + ↑/↓）。
        markLine: mark.markLine
          ? { ...clampMarkLine(mark.markLine, laneBounds[lane][0], laneBounds[lane][1]), z: markZ }
          : mark.markLine,
        silent: true,
        xAxisIndex: lane, yAxisIndex: lane, z: markZ,
        ...(lineColor ? { itemStyle: { color: lineColor } } : {}),
      })
    }
  }

  // 拆分模式图例只留参考线条目（lane 即 site 图例，去重复表达）
  const markNames = (d.marks || []).map((m: any) => m.name)
  const legendData = split ? markNames : series.map((s: any) => s.name)

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
    // split 模式 grid 从 top 10% 起（lane 区 ≈74%），首 lane 顶距标题块仍有富余；
    // 仅拆分态把标题块上移收紧（top 4 / itemGap 6），合并模式保持默认
    title: { text: `${param} Serial分布`, subtext, left: 'center', textStyle: { fontSize: 15, fontWeight: 'bold', color: tc }, subtextStyle: { fontSize: 12 }, ...(split ? { top: 4, itemGap: 6 } : {}) },
    tooltip: {
      trigger: 'item',
      backgroundColor: colors.value.tooltipBg,
      borderColor: colors.value.tooltipBorder,
      textStyle: { color: colors.value.tooltipText },
      formatter: (p: any) => {
        const pt = p.data || {}
        const anchor = pt.anchor ?? 0
        // value[0] 是轴下标（category 映射），真实序列号在 realSerial
        let html = `${p.seriesName}<br/>${serialCol}: ${pt.realSerial ?? p.value[0]}<br/>结果: ${pt.isFail ? 'FAIL' : 'PASS'}`
        html += `<br/>Value: ${Number(pt.realY ?? p.value[1]).toFixed(4)}`
        if (anchor === 2) html += '<br/>超出显示范围（真实值偏大）'
        if (anchor === 3) html += '<br/>超出显示范围（真实值偏小）'
        return html
      },
    },
    // 图例在最底（与直方图同款：底部只留 图例 + 轴标签，无 dataZoom 滑块占位）
    legend: { data: legendData, bottom: 5, type: 'scroll', textStyle: { color: tc } },
    toolbox: buildChartToolbox({ name: `${param}_Serial分布` }),
    xAxis: xAxes,
    yAxis: yAxes,
    dataZoom,
    grid: grids,
    series,
  }
}

// 大数据量强制 canvas（SVG 渲染器对 large 符号仍会为每点发射 DOM 元素；
// canvas 无 DOM 节点，官方推荐大数据散点必用 canvas）；小数据量跟随用户全局设置
const { chartRef } = useChart(
  buildOption,
  [() => props.data, () => props.outlierHandling, () => props.symbolSize, () => props.opacity, () => props.splitBySite],
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
}
.serial-col-selector__label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.serial-header {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
</style>
