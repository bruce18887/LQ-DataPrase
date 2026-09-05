<template>
  <div>
    <!-- 本 tab 自己选文件：与单文件分析/相关性/多文件四个 tab 互不影响 -->
    <el-row :gutter="12" style="margin-bottom: 10px" align="middle">
      <el-col :span="10">
        <AnalysisFilePicker
          v-model="fileId"
          :files="files"
          scope="wafer"
          :loading="listLoading"
        />
      </el-col>
      <el-col :span="14">
        <span class="wafer-note">
          本图按全部 die 的 Pass/Fail 判定，数据筛选不影响本图；
          可选参数取自直方图的测试项列表。
        </span>
      </el-col>
    </el-row>

    <el-row :gutter="12" style="margin-bottom: 12px" align="middle">
      <el-col :span="3">
        <el-button type="primary" @click="onLoad" :loading="waferLoading" style="width: 100%">加载晶圆图</el-button>
      </el-col>
      <el-col :span="4">
        <el-select v-model="localParam" placeholder="判定参数(可选)" clearable style="width: 100%" @change="onLoad">
          <el-option v-for="p in params" :key="p" :label="p" :value="p" />
        </el-select>
      </el-col>
      <el-col :span="7">
        <el-radio-group v-model="localColorBy" @change="onLoad" style="padding-top: 4px">
          <el-radio-button value="result">按结果</el-radio-button>
          <el-radio-button value="site">按 Site</el-radio-button>
          <el-radio-button value="zone">分区模式</el-radio-button>
        </el-radio-group>
      </el-col>
      <el-col :span="6">
        <span style="font-size: 12px; color: var(--text-2); margin-right: 8px">图表高度</span>
        <el-slider v-model="localHeight" :min="400" :max="900" :step="50" show-input style="flex: 1" />
      </el-col>
      <el-col :span="3">
        <el-checkbox v-model="localShowEdge" @change="onReRender">Wafer Edge</el-checkbox>
      </el-col>
      <el-col :span="3">
        <el-button type="success" size="small" @click="onLoadGlobal">全局判定</el-button>
      </el-col>
    </el-row>

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

    <!-- 良率统计卡片 -->
    <el-row v-if="waferData" :gutter="12" style="margin-bottom: 12px">
      <el-col :span="6"><el-card shadow="hover"><div style="font-size: 12px; color: var(--text-2)">Total Dies</div><div style="font-size: 18px; font-weight: bold">{{ waferData.stats?.total ?? '-' }}</div></el-card></el-col>
      <el-col :span="6"><el-card shadow="hover"><div style="font-size: 12px; color: var(--text-2)">Pass Dies</div><div style="font-size: 18px; font-weight: bold; color: waferColors.pass">{{ waferData.stats?.pass_count ?? '-' }}</div></el-card></el-col>
      <el-col :span="6"><el-card shadow="hover"><div style="font-size: 12px; color: var(--text-2)">Fail Dies</div><div style="font-size: 18px; font-weight: bold; color: waferColors.fail">{{ waferData.stats?.fail_count ?? '-' }}</div></el-card></el-col>
      <el-col :span="6"><el-card shadow="hover"><div style="font-size: 12px; color: var(--text-2)">Yield</div><div :style="{ fontSize: '18px', fontWeight: 'bold', color: (waferData.stats?.yield_pct ?? 0) >= 95 ? waferColors.pass : (waferData.stats?.yield_pct ?? 0) >= 85 ? waferColors.zoneMid : waferColors.zoneEdge }">{{ waferData.stats?.yield_pct?.toFixed(1) ?? '-' }}%</div></el-card></el-col>
    </el-row>

    <ErrorBanner
      v-if="zonalError && localColorBy === 'zone'"
      :message="zonalError"
      title="分区良率加载失败"
      @retry="fetchZonalYield"
    />

    <!-- 分区良率统计 -->
    <el-row v-if="localColorBy === 'zone' && zonalData?.zones?.length" :gutter="12" style="margin-bottom: 12px">
      <el-col :span="8"><el-card shadow="hover" :style="{ borderLeft: '3px solid ' + waferColors.zoneCenter }"><div style="font-size: 11px; color: var(--text-2)">中心区 Center Zone</div><div style="font-size: 16px; font-weight: bold; color: waferColors.zoneCenter">{{ getZoneYield('中心区') }}%</div><div style="font-size: 11px; color: var(--text-2)">{{ getZoneStat('中心区', 'pass') }} / {{ getZoneStat('中心区', 'total') }}</div></el-card></el-col>
      <el-col :span="8"><el-card shadow="hover" :style="{ borderLeft: '3px solid ' + waferColors.zoneMid }"><div style="font-size: 11px; color: var(--text-2)">中间区 Middle Zone</div><div style="font-size: 16px; font-weight: bold; color: waferColors.zoneMid">{{ getZoneYield('中间区') }}%</div><div style="font-size: 11px; color: var(--text-2)">{{ getZoneStat('中间区', 'pass') }} / {{ getZoneStat('中间区', 'total') }}</div></el-card></el-col>
      <el-col :span="8"><el-card shadow="hover" :style="{ borderLeft: '3px solid ' + waferColors.zoneEdge }"><div style="font-size: 11px; color: var(--text-2)">边缘区 Edge Zone</div><div style="font-size: 16px; font-weight: bold; color: waferColors.zoneEdge">{{ getZoneYield('边缘区') }}%</div><div style="font-size: 11px; color: var(--text-2)">{{ getZoneStat('边缘区', 'pass') }} / {{ getZoneStat('边缘区', 'total') }}</div></el-card></el-col>
    </el-row>

    <el-card style="margin-top: 12px">
      <div ref="chartRef" :style="{ height: localHeight + 'px' }" />
    </el-card>
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
const localHeight = ref(550)
const localShowEdge = ref(true)
const zonalData = ref<any>(null)
const zonalError = ref('')

// 晶圆图数据（此前挂在 AnalysisPage 上，随文件选择一起下放到本 tab）
const waferData = ref<any>(null)
const waferError = ref<string | null>(null)
const waferLoading = ref(false)

// 缺坐标列等错误走 axios 抛错路径（后端 400），不再静默空白
async function loadWafer() {
  if (!fileId.value) return
  waferLoading.value = true
  try {
    const payload: any = { file_id: fileId.value, color_by: localColorBy.value }
    if (localParam.value) payload.param = localParam.value
    const { data } = await analysisApi.postWaferMap(payload)
    if (data.error) {
      // 防御旧后端 200 错误载荷
      waferError.value = formatError({ response: { data } })
    } else {
      waferData.value = data
      waferError.value = null
    }
  } catch (e) {
    waferError.value = formatError(e)
  } finally {
    waferLoading.value = false
  }
}

/**
 * 全局判定：不带参数重取——与「不选判定参数」同口径。
 * 旧实现额外发一个 `global_judgment` 字段，但后端从不读它（
 * docs/specs/2026-09-02 §1 的「死字段」），因此这里不再透传。
 */
async function loadWaferGlobal() {
  if (!fileId.value) return
  waferLoading.value = true
  try {
    const { data } = await analysisApi.postWaferMap({
      file_id: fileId.value,
      color_by: localColorBy.value,
    })
    if (data.error) {
      waferError.value = formatError({ response: { data } })
    } else {
      waferData.value = data
      waferError.value = null
    }
  } catch (e) {
    waferError.value = formatError(e)
  } finally {
    waferLoading.value = false
  }
}

// 换文件后旧数据不再属于当前选择，直接清掉防止误读
watch(fileId, () => {
  waferData.value = null
  waferError.value = null
  zonalData.value = null
})

/**
 * Pass/Fail/分区色（双主题）。night 经 CVD 色盲模拟验证：
 * Pass 蓝 #4facfe / Fail 橙 #ff9f43 为主色对（protan+deutan ΔE≥18），
 * 分区 绿/金/粉 与主色对全部 ΔE≥15；light 保持原值。
 */
const waferColors = computed(() => isDark.value
  ? { pass: '#4facfe', fail: '#ff9f43', zoneCenter: '#38ef7d', zoneMid: '#fdd835', zoneEdge: '#fb7185' }
  : { pass: '#2ECC71', fail: '#E74C3C', zoneCenter: '#2ECC71', zoneMid: '#F39C12', zoneEdge: '#E74C3C' })

function getZoneYield(name: string): string { const zone = zonalData.value?.zones?.find((z: any) => z.name === name); return zone && Number.isFinite(zone.yield) ? zone.yield.toFixed(1) : '-' }
function getZoneStat(name: string, key: string): string | number { const zone = zonalData.value?.zones?.find((z: any) => z.name === name); return zone ? (zone[key] ?? '-') : '-' }

async function fetchZonalYield() {
  if (!fileId.value) return
  zonalError.value = ''
  try { const { data } = await analysisApi.getZonalYield(fileId.value, localParam.value || undefined); zonalData.value = data } catch (e) { zonalError.value = formatError(e, '分区良率加载失败'); zonalData.value = null }
}

function onLoad() { zonalData.value = null; loadWafer(); if (localColorBy.value === 'zone') fetchZonalYield() }
function onLoadGlobal() { zonalData.value = null; loadWaferGlobal(); if (localColorBy.value === 'zone') fetchZonalYield() }
function onReRender() { /* triggers watch via localShowEdge change */ }

// 上万 die 时逐点 SVG rect 是主要卡顿源（与相关性散点同阈值）：强制 canvas
// + large，小晶圆图行为零变更
const isLarge = computed(() => ((waferData.value?.points?.length) ?? 0) >= 5000)

function buildOption() {
  if (!waferData.value) return {}
  const tc = colors.value.textColor
  const data = waferData.value
  const pts: any[] = data.points || []
  const wafer = data.wafer
  const colorBy = localColorBy.value
  const series: any[] = []

  if (colorBy === 'site' && pts.some((p: any) => p.color_group)) {
    const siteMap = new Map<string, any[]>()
    for (const p of pts) { const g = p.color_group || 'Unknown'; if (!siteMap.has(g)) siteMap.set(g, []); siteMap.get(g)!.push(p) }
    Array.from(siteMap.keys()).sort().forEach((siteName, idx) => {
      series.push({ name: siteName, type: 'scatter', symbol: 'rect', symbolSize: [8, 8], ...(isLarge.value ? { large: true } : {}), data: siteMap.get(siteName)!.map((p: any) => ({ value: [p.x, p.y], serial: p.serial, bin: p.bin, site: p.site, status: p.status })), itemStyle: { color: getSiteColors8(isDark.value)[idx % 8], opacity: 0.9 } })
    })
  } else {
    const toPt = (p: any) => ({ value: [p.x, p.y], serial: p.serial, bin: p.bin, site: p.site, status: p.status })
    const largeOpts = isLarge.value ? { large: true } : {}
    series.push({ name: 'Pass', type: 'scatter', symbol: 'rect', symbolSize: [8, 8], ...largeOpts, data: pts.filter((p: any) => p.status === 'Pass').map(toPt), itemStyle: { color: waferColors.value.pass, opacity: 0.9 } })
    series.push({ name: 'Fail', type: 'scatter', symbol: 'rect', symbolSize: [8, 8], ...largeOpts, data: pts.filter((p: any) => p.status === 'Fail').map(toPt), itemStyle: { color: waferColors.value.fail, opacity: 0.95 } })
  }

  if (wafer && localShowEdge.value) {
    const cx = wafer.center_x, cy = wafer.center_y, r = wafer.radius
    const circlePoints: number[][] = []; for (let i = 0; i < 200; i++) { const a = (2 * Math.PI * i) / 200; circlePoints.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]) }
    series.push({ name: 'Wafer Edge', type: 'scatter', symbol: 'circle', symbolSize: 1, data: circlePoints.map(pt => ({ value: pt })), itemStyle: { color: '#B0BEC5', borderColor: '#78909C', borderWidth: 1.5 }, silent: true, z: 0 })
    const notchPoints: number[][] = []; for (let i = 0; i < 20; i++) { const a = Math.PI / 2 - 0.02 + 0.04 * i / 19; notchPoints.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]) }
    series.push({ name: 'Notch', type: 'scatter', symbol: 'circle', symbolSize: 1, data: notchPoints.map(pt => ({ value: pt })), itemStyle: { color: '#90A4AE' }, silent: true, z: 0 })
  }

  if (colorBy === 'zone' && wafer && zonalData.value?.zones?.length) {
    const cx = wafer.center_x, cy = wafer.center_y, r = wafer.radius
    if (cx != null && cy != null && r > 0) {
      for (const zd of [{ name: '中心区', ratio: 1.0 / 3.0, color: waferColors.value.zoneCenter }, { name: '中间区', ratio: 2.0 / 3.0, color: waferColors.value.zoneMid }, { name: '边缘区', ratio: 1.0, color: waferColors.value.zoneEdge }]) {
        const pts2: number[][] = []; const actualR = r * zd.ratio; for (let i = 0; i < 120; i++) { const a = (2 * Math.PI * i) / 120; pts2.push([cx + actualR * Math.cos(a), cy + actualR * Math.sin(a)]) }
        series.push({ name: zd.name, type: 'scatter', symbol: 'circle', symbolSize: 2, data: pts2.map(pt => ({ value: pt })), itemStyle: { color: zd.color, opacity: 0.6 }, silent: true, z: 1 })
      }
    }
  }

  const stats = data.stats || {}; const yieldRate = pts.length > 0 ? ((100 * (stats.pass_count || 0)) / pts.length).toFixed(1) : '0.0'
  return {
    // 上万 symbol 的入场/更新动画是纯开销，大晶圆直接关掉
    animation: !isLarge.value,
    title: { text: 'Wafer Map', subtext: `Total: ${pts.length} | Yield: ${yieldRate}%`, left: 'center' },
    tooltip: { trigger: 'item', formatter: (p: any) => { if (!p.value || !Array.isArray(p.value)) return p.name; const d = p.data; let h = `<b>${d.status || p.seriesName}</b><br/>X: ${p.value[0]} | Y: ${p.value[1]}<br/>`; if (d.serial != null) h += `Serial: ${d.serial}<br/>`; if (d.bin != null) h += `Bin: ${d.bin}<br/>`; if (d.site != null) h += `Site: ${d.site}<br/>`; return h }, backgroundColor: colors.value.tooltipBg, borderColor: colors.value.tooltipBorder, textStyle: { color: colors.value.tooltipText }, extraCssText: 'box-shadow:0 2px 8px rgba(0,0,0,0.15);border-radius:4px;padding:8px 12px;' },
    legend: { data: series.map((s: any) => s.name), bottom: 10, type: 'scroll', textStyle: { color: tc } },
    toolbox: { feature: { saveAsImage: { title: '保存', pixelRatio: 2 }, dataZoom: { title: { zoom: '缩放', back: '还原' } }, restore: { title: '还原' } }, right: 20, top: 20 },
    grid: { left: 50, right: 60, top: 60, bottom: 50 },
    xAxis: { type: 'value', name: data.x_col ?? 'X', nameTextStyle: { color: tc }, scale: true, axisLabel: { formatter: (v: number) => v.toFixed(0), color: tc } },
    yAxis: { type: 'value', name: data.y_col ?? 'Y', nameTextStyle: { color: tc }, scale: true, axisLabel: { formatter: (v: number) => v.toFixed(0), color: tc } },
    dataZoom: [{ type: 'slider', xAxisIndex: 0, start: 0, end: 100 }, { type: 'slider', yAxisIndex: 0, start: 0, end: 100 }, { type: 'inside', xAxisIndex: 0 }, { type: 'inside', yAxisIndex: 0 }],
    series,
  }
}

const { chartRef } = useChart(
  buildOption,
  [waferData, localShowEdge, localColorBy, zonalData],
  'chartRef',
  () => (isLarge.value ? 'canvas' : getChartRenderer()),
)
void chartRef // bound to <div ref="chartRef"> in template
</script>

<style scoped>
/* 晶圆图不吃数据筛选的例外说明（与左栏筛选区同屏时防用户误以为会影响本图） */
.wafer-note {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.5;
}
</style>
