<template>
  <div class="serial-chart-wrapper">
    <!-- 工具栏：点径/透明度 slider + 序列列选择器（spec §3；拆分开关见后续任务） -->
    <div class="serial-header">
      <el-checkbox v-if="siteCount >= 2" v-model="splitBySite" size="small">按 Site 拆分</el-checkbox>
      <div class="serial-header__slider">
        <span class="serial-header__label">点径 {{ effSize }} {{ sizeAutoHint }}</span>
        <el-slider
          :model-value="effSize" :min="2" :max="8" :step="1" size="small"
          class="serial-header__range"
          @update:model-value="(v: number | [number, number]) => (pointSizeOverride = Array.isArray(v) ? v[0] : v)"
        />
      </div>
      <div class="serial-header__slider">
        <span class="serial-header__label">透明度 {{ effOpacityPct }}% {{ opacityAutoHint }}</span>
        <el-slider
          :model-value="effOpacityPct" :min="10" :max="100" :step="5" size="small"
          class="serial-header__range"
          @update:model-value="(v: number | [number, number]) => (opacityOverridePct = Array.isArray(v) ? v[0] : v)"
        />
      </div>
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
import { computed, ref, watch } from 'vue'
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
/** 按 Site 拆分小多图开关（spec §2；会话级偏好，不随数据重载重置） */
const splitBySite = ref(false)
const siteCount = computed(() => (props.data?.series_data || []).length)

// 大数据量（≥5000 点）启用 ECharts 官方 large 模式：每个系列只渲染 1 个
// path 元素（类型化数组 + 单次绘制），SVG/canvas 渲染器下均生效，避免
// 上万散点产生上万 DOM 节点拖垮首屏/缩放/切参数。
const pointCount = computed(() =>
  (props.data?.series_data || []).reduce(
    (sum: number, sd: { data?: unknown[] }) => sum + (sd.data?.length ?? 0), 0))
const isLarge = computed(() => pointCount.value >= 5000)

// —— 重叠可读性（spec 2026-09-12 §1.1）：按总点数自适应点径/透明度，
// 大文件散点不再糊成实色带；slider 手动覆盖见下方 override 语义（§3） ——
function autoPointStyle(count: number): { size: number; opacity: number } {
  if (count < 5000) return { size: 6, opacity: 0.85 }
  if (count <= 20000) return { size: 4, opacity: 0.5 }
  return { size: 3, opacity: 0.35 }
}
const autoStyle = computed(() => autoPointStyle(pointCount.value))
/** 手动覆盖（null = 自动）：每次数据重载清零，避免手动值毁掉小文件（spec §3） */
const pointSizeOverride = ref<number | null>(null)
const opacityOverridePct = ref<number | null>(null) // 百分比 10-100
watch(() => props.data, () => {
  pointSizeOverride.value = null
  opacityOverridePct.value = null
})
const effSize = computed(() => pointSizeOverride.value ?? autoStyle.value.size)
const effOpacityPct = computed(() => opacityOverridePct.value ?? Math.round(autoStyle.value.opacity * 100))
const effOpacity = computed(() => effOpacityPct.value / 100)
const sizeAutoHint = computed(() => (pointSizeOverride.value == null ? '(自动)' : ''))
const opacityAutoHint = computed(() => (opacityOverridePct.value == null ? '(自动)' : ''))

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
  function toPoint(p: number[]) {
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
    }
  }

  // —— fail/超界点不拆独立强调层：随 Site 系列着色（2026-09-13 按用户反馈回退
  // §1.3 强调层：并集层名易被误读为「红点=超界」）；anchor=1（无值）仍不绘制 ——
  const siteSeriesRaw: { name: string; data: number[][] }[] = d.series_data || []
  const siteColors = getSiteColors8(isDark.value)
  const siteData: any[][] = siteSeriesRaw.map((sd) =>
    (sd.data || []).map((p: number[]) => toPoint(p)).filter((pt: any) => pt !== null))
  // 绘制序：最密垫底（spec §1.2）——按点数降序赋 z；数组序保持 site 升序
  // （图例顺序与直方图等其它图表一致的既有约定）。密度口径取实际绘制点数
  // （fail/超界点随 Site 系列着色、参与带层叠），与视觉上的散点带浓淡一致。
  const counts = siteData.map((sd) => sd.length)
  const zOfSite = new Map<number, number>()
  counts
    .map((_, i) => i)
    .sort((a, b) => counts[b] - counts[a])
    .forEach((idx, rank) => zOfSite.set(idx, 2 + rank))

  const split = splitBySite.value && siteSeriesRaw.length >= 2
  const laneCount = split ? siteSeriesRaw.length : 1

  const series: any[] = siteSeriesRaw.map((sd, idx) => ({
    name: sd.name, type: 'scatter',
    data: siteData[idx],
    ...(split ? { xAxisIndex: idx, yAxisIndex: idx } : {}),
    symbolSize: effSize.value,
    itemStyle: { color: siteColors[idx % 8], opacity: effOpacity.value },
    ...(split ? {} : { z: zOfSite.get(idx) }),
    ...(isLarge.value ? { large: true } : {}),
  }))

  // —— 轴/网格：合并单面板；拆分 N 条同步 lane（spec §2：top 16% 留标题+副标题、
  // bottom 24% 留 X 标签+图例，其余 N 等分、lane 间距 2%）——
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
  function yAxisDef(i: number, laneName: string | null, laneColor?: string) {
    return {
      type: 'value', gridIndex: i, min: yAxisMin, max: yAxisMax,
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

  let grids: any[]
  let xAxes: any[]
  let yAxes: any[]
  let dataZoom: any[]
  if (split) {
    const lanePct = 60 / laneCount
    grids = siteSeriesRaw.map((_, i) => ({
      left: 70, right: 30,
      top: `${16 + i * lanePct}%`,
      height: `${Math.max(lanePct - 2, 4)}%`,
    }))
    xAxes = siteSeriesRaw.map((_, i) => xAxisDef(i, i === laneCount - 1))
    yAxes = siteSeriesRaw.map((sd, i) => yAxisDef(i, sd.name, siteColors[i % 8]))
    dataZoom = [{ type: 'inside', xAxisIndex: siteSeriesRaw.map((_, i) => i) }]
  } else {
    grids = [{ top: 60, bottom: 85 }]
    xAxes = [xAxisDef(0, true)]
    yAxes = [yAxisDef(0, null)]
    dataZoom = [{ type: 'inside', xAxisIndex: [0] }]
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
        // 默认 5）——site z 可达 N+1，必须显式抬到 markZ 保证参考线恒在数据带之上
        markLine: mark.markLine ? { ...mark.markLine, z: markZ } : mark.markLine, silent: true,
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
    // split 模式 grid top 16% 仅≈45px，默认标题块（y≈21-54）会压首 lane：
    // 仅拆分态把标题块上移收紧（top 4 / itemGap 6 → 块底≈37），合并模式保持默认零改动
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
  [() => props.data, () => props.outlierHandling, () => effSize.value, () => effOpacityPct.value, () => splitBySite.value],
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
.serial-header__slider {
  display: flex;
  align-items: center;
  gap: 6px;
}
.serial-header__label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}
.serial-header__range {
  width: 110px;
}
</style>
