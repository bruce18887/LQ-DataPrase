<template>
  <div>
    <!-- 顶部 toolbar 盒：文件选择行（与单文件/相关性同位）。
         晶圆图不吃任何筛选（wafer_map 不读筛选字段），故无筛选行。 -->
    <div class="dp-analysis-toolbar wafer-toolbar">
      <AnalysisFilePicker
        v-model="fileId"
        :files="files"
        scope="wafer"
        :loading="listLoading"
      />
      <span class="wafer-note">
        本图按全部 die 的 Pass/Fail 判定，数据筛选不影响本图；
        可选参数取自直方图的测试项列表。
      </span>
    </div>

    <!-- 控制工具条：着色 4 档 + 边界/分区开关 + 高度 + 加载（预览稿形态） -->
    <div class="wafer-controls">
      <span class="ctl-label">着色</span>
      <el-radio-group
        v-model="localColorBy"
        data-wafer-color
        size="small"
        @change="onLoad"
      >
        <el-radio-button value="result">判定结果</el-radio-button>
        <el-radio-button value="site">Site</el-radio-button>
        <el-radio-button value="bin">Bin</el-radio-button>
        <el-radio-button value="param">参数值</el-radio-button>
      </el-radio-group>
      <el-checkbox v-model="localShowEdge" @change="onReRender">边界圆+Notch</el-checkbox>
      <el-checkbox v-model="localZoneMode" @change="onReRender">分区模式</el-checkbox>
      <span class="ctl-spacer" />
      <span class="ctl-label">高度</span>
      <input v-model.number="localHeight" type="range" class="height-range" min="400" max="900" step="50" />
      <span class="height-val">{{ localHeight }}</span>
      <el-button type="primary" @click="onLoad" :loading="waferLoading">加载晶圆图</el-button>
    </div>

    <!-- 缺坐标列等错误：展示提示而非静默空白 -->
    <el-alert
      v-if="waferError"
      :title="waferError"
      type="error"
      show-icon
      :closable="false"
      class="wafer-error-alert"
      style="margin-bottom: 12px"
    />
    <ErrorBanner
      v-if="zonalError"
      :message="zonalError"
      title="分区良率加载失败"
      @retry="fetchZonalYield"
    />

    <div class="wafer-body">
      <!-- 左栏 25%：两张常驻统计表 -->
      <div class="wafer-left">
        <WaferStatTables
          :zones="zonalData?.zones ?? []"
          :zone-error="zonalError"
          :stats="waferData?.stats ?? null"
          :x-col="waferData?.x_col"
          :y-col="waferData?.y_col"
          :die-size="waferData?.wafer?.die_size ?? null"
        />
      </div>

      <!-- 右栏 75%：晶圆图卡 + 自动结论条 -->
      <div class="wafer-right">
        <el-card body-style="padding: 8px">
          <div ref="chartRef" :style="{ height: localHeight + 'px' }" />
          <div v-if="paramFallbackNote" class="wafer-fallback-note">{{ paramFallbackNote }}</div>
        </el-card>
        <div v-if="conclusion" class="wafer-conclusion" data-wafer-conclusion>{{ conclusion }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useWaferTabStore } from '../../../stores/analysisTabs'
import type { DataFile } from '../../../types'
import { useChart } from '../../../composables/useChart'
import { useTabFileParams } from '../composables/useTabFileParams'
import { useEChartsTheme, getChartRenderer } from '../../../utils/echarts-theme'
import { getSiteColors8 } from '../../../utils/chart-bar'
import { formatError } from '../../../utils/error'
import { analysisApi } from '../../../api/analysis'
import AnalysisFilePicker from './AnalysisFilePicker.vue'
import ErrorBanner from '../../../components/common/ErrorBanner.vue'
import WaferStatTables from './WaferStatTables.vue'

const props = defineProps<{ files: DataFile[] }>()
const { colors, isDark } = useEChartsTheme()

// 文件与参数列表是本 tab 自己的（`wafer_map` 不读任何筛选字段，且
// `data_only_bin1` 会把 fail die 全抹掉 → 拉参数列表时不带开关）
const { fileId, params, loading: listLoading } = storeToRefs(useWaferTabStore())
useTabFileParams({
  ctx: { fileId, params, loading: listLoading },
  files: computed(() => props.files),
})

// 判定参数可选：不入 store，换文件/换列表后若已不在候选集里就回到「无」
const localParam = ref('')
watch(params, (list) => {
  if (localParam.value && !list.includes(localParam.value)) localParam.value = ''
})
const localColorBy = ref('result')
const localZoneMode = ref(false)
const localHeight = ref(550)
const localShowEdge = ref(true)
const zonalData = ref<any>(null)
const zonalError = ref('')

// 晶圆图数据（此前挂在 AnalysisPage 上，随文件选择一起下放到本 tab）
const waferData = ref<any>(null)
const waferError = ref<string | null>(null)
const waferLoading = ref(false)

// 「参数值」着色降级注记（value 全空或未选参数时给图内提示，不弹横幅）
const paramFallbackNote = ref('')

// 缺坐标列等错误走 axios 抛错路径（后端 400），不再静默空白。
// 两条数据通道各自维护「最新请求」序号：裸 await 无守卫时，切文件/快速连点
// 后在途旧响应会把旧文件的晶圆图/分区数据写回（2026-09-05 审查 M2）；
// waferLoading 由最新请求独占管理，先完成的一方不再熄灭在途方的加载态。
// loadWafer 写 waferData；fetchZonalYield 写 zonalData，是独立通道，单独
// 计数（不能与晶圆图互斥）。
let waferLoadSeq = 0
let zonalLoadSeq = 0

async function loadWafer() {
  if (!fileId.value) return
  const mySeq = ++waferLoadSeq
  const reqFileId = fileId.value
  waferLoading.value = true
  try {
    const payload: any = { file_id: reqFileId, color_by: localColorBy.value }
    if (localParam.value) payload.param = localParam.value
    const { data } = await analysisApi.postWaferMap(payload)
    if (mySeq !== waferLoadSeq || fileId.value !== reqFileId) return
    if (data.error) {
      // 防御旧后端 200 错误载荷
      waferError.value = formatError({ response: { data } })
    } else {
      waferData.value = data
      waferError.value = null
    }
  } catch (e) {
    if (mySeq !== waferLoadSeq) return
    waferError.value = formatError(e)
  } finally {
    if (mySeq === waferLoadSeq) waferLoading.value = false
  }
}

// 换文件后旧数据不再属于当前选择，直接清掉防止误读
watch(fileId, () => {
  waferData.value = null
  waferError.value = null
  zonalData.value = null
})

/**
 * Pass/Fail/分区/参数值渐变色（双主题）。night 经 CVD 色盲模拟验证：
 * Pass 蓝 #4facfe / Fail 橙 #ff9f43 为主色对（protan+deutan ΔE≥18），
 * 分区 绿/金/粉 与主色对全部 ΔE≥15；light 保持原值。
 */
const waferColors = computed(() => isDark.value
  ? { pass: '#4facfe', fail: '#ff9f43', zoneCenter: '#38ef7d', zoneMid: '#fdd835', zoneEdge: '#fb7185' }
  : { pass: '#2ECC71', fail: '#E74C3C', zoneCenter: '#2ECC71', zoneMid: '#F39C12', zoneEdge: '#E74C3C' })

/* 「参数值」着色的归一区间（双口径自适应，spec 2026-09-08 §后端改动）：
   有真规格限 → LSL→USL；无/退化 → 数据 min→max；全同值 → null 走降级 */
const paramScale = computed(() => {
  const d = waferData.value
  if (!d) return null
  const vals: number[] = (d.points || [])
    .map((p: any) => p.value)
    .filter((v: any) => typeof v === 'number' && Number.isFinite(v))
  if (!vals.length) return null
  let lo: number | null = d.spec_low ?? null
  let hi: number | null = d.spec_high ?? null
  const bySpec = lo != null && hi != null && hi > lo
  if (!bySpec) {
    lo = Math.min(...vals)
    hi = Math.max(...vals)
    if (hi <= lo) return null
  }
  const label = bySpec
    ? '按规格限 LSL→USL 归一'
    : (d.spec_low != null || d.spec_high != null ? '按数据范围归一（规格限退化）' : '按数据范围归一（该参数无规格限）')
  return { lo: lo as number, hi: hi as number, label }
})

/* 自动结论条（预览稿口径）：三区都有数据才出结论；<0.5pp 判无径向梯度 */
const conclusion = computed(() => {
  const zones = zonalData.value?.zones
  if (!zones?.length || zones.length !== 3) return ''
  const yields = zones.map((z: any) => z.yield)
  if (yields.some((y: any) => y == null || !Number.isFinite(y))) return ''
  const lo = Math.min(...yields)
  const hi = Math.max(...yields)
  const span = hi - lo
  const spanText = `三环带良率 ${lo.toFixed(1)}% ~ ${hi.toFixed(1)}%，极差 ${span.toFixed(1)} 个百分点`
  return span < 0.5
    ? `${spanText} → 无径向梯度，失效集中在特定 Site/Bin 分裂（可切单文件 tab 看 Site 分层）。`
    : `${spanText} → 存在径向梯度，可按环带下钻。`
})

async function fetchZonalYield() {
  if (!fileId.value) return
  const mySeq = ++zonalLoadSeq
  const reqFileId = fileId.value
  const reqParam = localParam.value
  zonalError.value = ''
  try {
    const { data } = await analysisApi.getZonalYield(reqFileId, reqParam || undefined)
    if (mySeq !== zonalLoadSeq || fileId.value !== reqFileId || localParam.value !== reqParam) return
    zonalData.value = data
  } catch (e) {
    if (mySeq !== zonalLoadSeq) return
    zonalError.value = formatError(e, '分区良率加载失败')
    zonalData.value = null
  }
}

/* 左栏分区表是常驻的：选文件/换判定参数/有着色变化后都重拉一次
   （原来只在勾选分区模式时发请求） */
function onLoad() {
  loadWafer()
  fetchZonalYield()
}
function onReRender() { /* triggers watch via ref change */ }

// 上万 die 时逐点 SVG rect 是主要卡顿源（与相关性散点同阈值）：强制 canvas
// + large，小晶圆图行为零变更
const isLarge = computed(() => ((waferData.value?.points?.length) ?? 0) >= 5000)

/* die 方块尺寸：按真实 die_size 与坐标 span 的比例换算（预览稿口径，下限 1.6px）。
   旧实现写死 [8,8]，小 die 晶圆挤成一团、大 die 晶圆缝隙过宽 */
const dieSymbolSize = computed(() => {
  const wafer = waferData.value?.wafer
  if (!wafer?.die_size || !waferData.value?.points?.length) return [8, 8]
  const pts = waferData.value.points
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity
  for (const p of pts) {
    if (p.x < x0) x0 = p.x
    if (p.x > x1) x1 = p.x
    if (p.y < y0) y0 = p.y
    if (p.y > y1) y1 = p.y
  }
  const span = Math.max(x1 - x0, y1 - y0) || 1
  // 数据区高约 600px（550 减 title/legend/grid 边距）：
  // die 像素尺寸 ≈ die_size / span * 600，0.86 留缝
  const px = Math.max(1.6, (wafer.die_size / span) * 600 * 0.86)
  return [px, px]
})

function toPt(p: any, normalized?: number) {
  return {
    value: [p.x, p.y, ...(normalized != null ? [normalized] : [])],
    serial: p.serial, bin: p.bin, site: p.site, status: p.status,
  }
}

function pushResultSeries(series: any[], pts: any[], sym: any, largeOpts: any) {
  series.push({ name: 'Pass', type: 'scatter', ...sym, ...largeOpts, data: pts.filter((p: any) => p.status === 'Pass').map((p: any) => toPt(p)), itemStyle: { color: waferColors.value.pass, opacity: 0.9 } })
  series.push({ name: 'Fail', type: 'scatter', ...sym, ...largeOpts, data: pts.filter((p: any) => p.status === 'Fail').map((p: any) => toPt(p)), itemStyle: { color: waferColors.value.fail, opacity: 0.95 } })
}

function buildOption() {
  if (!waferData.value) return {}
  const tc = colors.value.textColor
  const data = waferData.value
  const pts: any[] = data.points || []
  const wafer = data.wafer
  const colorBy = localColorBy.value
  const series: any[] = []
  const largeOpts = isLarge.value ? { large: true } : {}
  const sym = { symbol: 'rect', symbolSize: dieSymbolSize.value }
  paramFallbackNote.value = ''

  if (localZoneMode.value && wafer) {
    /* 分区模式（独立 checkbox，覆盖着色）：按 die 距心半径落 1/3·2/3 环带。
       与后端 compute_wafer_zone_stats 同口径（hypot 距离 + bounds [r/3, 2r/3]，
       末区兜底），否则画的分区和分区良率表对不上 */
    const cx = wafer.center_x
    const cy = wafer.center_y
    const r = wafer.radius
    const zoneDefs = [
      { name: '中心区', color: waferColors.value.zoneCenter, upper: r / 3 },
      { name: '中间区', color: waferColors.value.zoneMid, upper: (r * 2) / 3 },
      { name: '边缘区', color: waferColors.value.zoneEdge, upper: Infinity },
    ]
    if (cx != null && cy != null && r > 0) {
      const buckets = new Map<string, any[]>()
      for (const p of pts) {
        const d = Math.hypot(p.x - cx, p.y - cy)
        const zd = zoneDefs.find((z) => d <= z.upper)!
        if (!buckets.has(zd.name)) buckets.set(zd.name, [])
        buckets.get(zd.name)!.push(toPt(p))
      }
      for (const zd of zoneDefs) {
        series.push({
          name: zd.name, type: 'scatter', ...sym, ...largeOpts,
          data: buckets.get(zd.name) ?? [], itemStyle: { color: zd.color, opacity: 0.9 },
        })
      }
      // 1/3·2/3 虚线环（预览稿形态）
      for (const k of [1 / 3, 2 / 3]) {
        const ringPts: number[][] = []
        for (let i = 0; i < 120; i++) {
          const a = (2 * Math.PI * i) / 120
          ringPts.push([cx + r * k * Math.cos(a), cy + r * k * Math.sin(a)])
        }
        series.push({
          name: `环带 ${k.toFixed(2)}R`, type: 'scatter', symbol: 'circle', symbolSize: 1.5,
          data: ringPts.map((pt) => ({ value: pt })), itemStyle: { color: tc, opacity: 0.5 },
          silent: true, z: 1,
        })
      }
    }
  } else if (colorBy === 'param' && paramScale.value) {
    /* 参数值着色：单系列 + continuous visualMap（绿→红）；NaN 值灰档「无值」 */
    const scale = paramScale.value
    const withVal: any[] = []
    const noVal: any[] = []
    for (const p of pts) {
      const t = typeof p.value === 'number' && Number.isFinite(p.value)
        ? Math.max(0, Math.min(1, (p.value - scale.lo) / (scale.hi - scale.lo)))
        : null
      ;(t == null ? noVal : withVal).push(toPt(p, t ?? undefined))
    }
    if (!withVal.length) {
      // 全 NaN：该档降级回落 Pass/Fail（spec §错误处理），图内给注记
      paramFallbackNote.value = '所选参数在坐标有效点上无有效值，已回落判定结果着色'
      pushResultSeries(series, pts, sym, largeOpts)
    } else {
      series.push({
        name: localParam.value || '参数值', type: 'scatter', ...sym, ...largeOpts,
        data: withVal, itemStyle: { opacity: 0.9 },
      })
      if (noVal.length) {
        series.push({
          name: '无值', type: 'scatter', ...sym, ...largeOpts,
          data: noVal, itemStyle: { color: '#9ca3af', opacity: 0.9 },
        })
      }
    }
  } else if (colorBy === 'param') {
    // 请求里没带逐点值（未选参数就切到该档）：回落并注记
    paramFallbackNote.value = '所选参数在坐标有效点上无有效值，已回落判定结果着色'
    pushResultSeries(series, pts, sym, largeOpts)
  } else if (colorBy === 'bin' && pts.some((p: any) => p.bin != null)) {
    /* Bin 着色：按 bin 分组复用 8 色板（>8 组循环取色） */
    const binMap = new Map<string, any[]>()
    for (const p of pts) {
      const g = p.bin == null ? '无 Bin' : String(p.bin)
      if (!binMap.has(g)) binMap.set(g, [])
      binMap.get(g)!.push(toPt(p))
    }
    const palette = getSiteColors8(isDark.value)
    Array.from(binMap.keys())
      .sort((a, b) => (Number(a) - Number(b)) || a.localeCompare(b))
      .forEach((binName, idx) => {
        series.push({
          name: `Bin ${binName}`, type: 'scatter', ...sym, ...largeOpts,
          data: binMap.get(binName)!, itemStyle: { color: palette[idx % 8], opacity: 0.9 },
        })
      })
  } else if (colorBy === 'site' && pts.some((p: any) => p.color_group)) {
    const siteMap = new Map<string, any[]>()
    for (const p of pts) {
      const g = p.color_group || 'Unknown'
      if (!siteMap.has(g)) siteMap.set(g, [])
      siteMap.get(g)!.push(toPt(p))
    }
    Array.from(siteMap.keys()).sort().forEach((siteName, idx) => {
      series.push({
        name: siteName, type: 'scatter', ...sym, ...largeOpts,
        data: siteMap.get(siteName)!,
        itemStyle: { color: getSiteColors8(isDark.value)[idx % 8], opacity: 0.9 },
      })
    })
  } else {
    pushResultSeries(series, pts, sym, largeOpts)
  }

  // 边界圆 + Notch（原「Wafer Edge」改名，功能不变；分区模式下被环带视觉取代）
  if (wafer && localShowEdge.value && !localZoneMode.value) {
    const cx = wafer.center_x
    const cy = wafer.center_y
    const r = wafer.radius
    if (cx != null && cy != null && r > 0) {
      const circlePoints: number[][] = []
      for (let i = 0; i < 200; i++) {
        const a = (2 * Math.PI * i) / 200
        circlePoints.push([cx + r * Math.cos(a), cy + r * Math.sin(a)])
      }
      series.push({ name: 'Wafer Edge', type: 'scatter', symbol: 'circle', symbolSize: 1, data: circlePoints.map((pt) => ({ value: pt })), itemStyle: { color: '#B0BEC5', borderColor: '#78909C', borderWidth: 1.5 }, silent: true, z: 0 })
      const notchPoints: number[][] = []
      for (let i = 0; i < 20; i++) {
        const a = Math.PI / 2 - 0.02 + (0.04 * i) / 19
        notchPoints.push([cx + r * Math.cos(a), cy + r * Math.sin(a)])
      }
      series.push({ name: 'Notch', type: 'scatter', symbol: 'circle', symbolSize: 1, data: notchPoints.map((pt) => ({ value: pt })), itemStyle: { color: '#90A4AE' }, silent: true, z: 0 })
    }
  }

  const stats = data.stats || {}
  const yieldRate = pts.length > 0 ? ((100 * (stats.pass_count || 0)) / pts.length).toFixed(1) : '0.0'
  // 参数值着色时把归一口径写进副标题（spec：口径必须可见）
  let subtext = `Total: ${pts.length} | Yield: ${yieldRate}%`
  if (colorBy === 'param' && paramScale.value && !localZoneMode.value) subtext += ` | ${paramScale.value.label}`
  const option: any = {
    // 上万 symbol 的入场/更新动画是纯开销，大晶圆直接关掉
    animation: !isLarge.value,
    title: { text: 'Wafer Map', subtext, left: 'center' },
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        if (!p.value || !Array.isArray(p.value)) return p.name
        const d = p.data
        let h = `<b>${d.status || p.seriesName}</b><br/>X: ${p.value[0]} | Y: ${p.value[1]}<br/>`
        if (d.serial != null) h += `Serial: ${d.serial}<br/>`
        if (d.bin != null) h += `Bin: ${d.bin}<br/>`
        if (d.site != null) h += `Site: ${d.site}<br/>`
        return h
      },
      backgroundColor: colors.value.tooltipBg,
      borderColor: colors.value.tooltipBorder,
      textStyle: { color: colors.value.tooltipText },
      extraCssText: 'box-shadow:0 2px 8px rgba(0,0,0,0.15);border-radius:4px;padding:8px 12px;',
    },
    legend: { data: series.map((s: any) => s.name), bottom: 10, type: 'scroll', textStyle: { color: tc } },
    toolbox: { feature: { saveAsImage: { title: '保存', pixelRatio: 2 }, dataZoom: { title: { zoom: '缩放', back: '还原' } }, restore: { title: '还原' } }, right: 20, top: 20 },
    grid: { left: 50, right: 60, top: 60, bottom: 50 },
    xAxis: { type: 'value', name: data.x_col ?? 'X', nameTextStyle: { color: tc }, scale: true, axisLabel: { formatter: (v: number) => v.toFixed(0), color: tc } },
    yAxis: { type: 'value', name: data.y_col ?? 'Y', nameTextStyle: { color: tc }, scale: true, axisLabel: { formatter: (v: number) => v.toFixed(0), color: tc } },
    dataZoom: [{ type: 'slider', xAxisIndex: 0, start: 0, end: 100 }, { type: 'slider', yAxisIndex: 0, start: 0, end: 100 }, { type: 'inside', xAxisIndex: 0 }, { type: 'inside', yAxisIndex: 0 }],
    series,
  }
  if (colorBy === 'param' && paramScale.value && !localZoneMode.value) {
    option.visualMap = {
      show: false, min: 0, max: 1, calculable: false,
      inRange: { color: [colors.value.successColor, colors.value.warnColor, colors.value.errorColor] },
      // dimension 2 = toPt 塞进 value[2] 的归一值
      dimension: 2,
      seriesIndex: 0,
    }
  }
  return option
}

const { chartRef } = useChart(
  buildOption,
  [waferData, localShowEdge, localColorBy, localZoneMode, zonalData],
  'chartRef',
  () => (isLarge.value ? 'canvas' : getChartRenderer()),
)
void chartRef // bound to <div ref="chartRef"> in template
</script>

<style scoped>
/* 晶圆图 toolbar 盒：选择器定宽，说明文字占余宽换行 */
.wafer-toolbar {
  flex-wrap: wrap;
}
.wafer-toolbar > .dp-analysis-filepicker {
  flex: 0 0 360px;
  min-width: 240px;
}

/* 晶圆图不吃数据筛选的例外说明（与左栏筛选区同屏时防用户误以为会影响本图） */
.wafer-note {
  font-size: 12px;
  /* 同 DataFilterSection 的提示文字：浅色下 --text-3 在白底仅 2.54:1 */
  color: var(--text-2);
  line-height: 1.5;
}

/* 控制工具条（预览稿 .toolbar 形态） */
.wafer-controls {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin: 12px 0;
  padding: 8px 12px;
  background: var(--bg-3);
  border: 1px solid var(--border-2);
  border-radius: 6px;
}
.ctl-label {
  font-size: 12px;
  color: var(--text-2);
  font-weight: 500;
  white-space: nowrap;
}
.ctl-spacer {
  flex: 1;
}
.height-range {
  width: 120px;
  accent-color: var(--brand);
}
.height-val {
  font-size: 11px;
  color: var(--text);
  font-weight: 600;
  font-family: var(--font-mono);
  min-width: 28px;
}

/* 左 25% / 右 75% 分栏（对齐预览稿 .row .col-l/.col-r） */
.wafer-body {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.wafer-left {
  flex: 0 0 25%;
  min-width: 0;
}
.wafer-right {
  flex: 1 1 75%;
  min-width: 0;
}
.wafer-left > :deep(.wafer-stat-tables) {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 自动结论条（预览稿 .diag 形态） */
.wafer-conclusion {
  margin-top: 10px;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--text-2);
  border-left: 3px solid var(--info);
  background: color-mix(in srgb, var(--info) 9%, transparent);
  border-radius: 0 4px 4px 0;
}
.wafer-fallback-note {
  margin-top: 6px;
  padding: 4px 10px;
  font-size: 11.5px;
  color: var(--warn-2, var(--warn));
  text-align: center;
}
</style>
