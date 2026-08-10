<template>
  <div>
    <el-row :gutter="12" style="margin-bottom: 12px" align="middle">
      <el-col :span="3">
        <el-button type="primary" @click="onLoad" :loading="loading" style="width: 100%">加载晶圆图</el-button>
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
        <span style="font-size: 12px; color: var(--text-secondary); margin-right: 8px">图表高度</span>
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
      <el-col :span="6"><el-card shadow="hover"><div style="font-size: 12px; color: var(--text-secondary)">Total Dies</div><div style="font-size: 18px; font-weight: bold">{{ waferData.stats?.total ?? '-' }}</div></el-card></el-col>
      <el-col :span="6"><el-card shadow="hover"><div style="font-size: 12px; color: var(--text-secondary)">Pass Dies</div><div style="font-size: 18px; font-weight: bold; color: #2ECC71">{{ waferData.stats?.pass_count ?? '-' }}</div></el-card></el-col>
      <el-col :span="6"><el-card shadow="hover"><div style="font-size: 12px; color: var(--text-secondary)">Fail Dies</div><div style="font-size: 18px; font-weight: bold; color: #E74C3C">{{ waferData.stats?.fail_count ?? '-' }}</div></el-card></el-col>
      <el-col :span="6"><el-card shadow="hover"><div style="font-size: 12px; color: var(--text-secondary)">Yield</div><div :style="{ fontSize: '18px', fontWeight: 'bold', color: (waferData.stats?.yield_pct ?? 0) >= 95 ? '#2ECC71' : (waferData.stats?.yield_pct ?? 0) >= 85 ? '#F39C12' : '#E74C3C' }">{{ waferData.stats?.yield_pct?.toFixed(1) ?? '-' }}%</div></el-card></el-col>
    </el-row>

    <!-- 分区良率统计 -->
    <el-row v-if="localColorBy === 'zone' && zonalData?.zones?.length" :gutter="12" style="margin-bottom: 12px">
      <el-col :span="8"><el-card shadow="hover" :style="{ borderLeft: '3px solid #2ECC71' }"><div style="font-size: 11px; color: var(--text-secondary)">中心区 Center Zone</div><div style="font-size: 16px; font-weight: bold; color: #2ECC71">{{ getZoneYield('中心区') }}%</div><div style="font-size: 11px; color: var(--text-secondary)">{{ getZoneStat('中心区', 'pass') }} / {{ getZoneStat('中心区', 'total') }}</div></el-card></el-col>
      <el-col :span="8"><el-card shadow="hover" :style="{ borderLeft: '3px solid #F39C12' }"><div style="font-size: 11px; color: var(--text-secondary)">中间区 Middle Zone</div><div style="font-size: 16px; font-weight: bold; color: #F39C12">{{ getZoneYield('中间区') }}%</div><div style="font-size: 11px; color: var(--text-secondary)">{{ getZoneStat('中间区', 'pass') }} / {{ getZoneStat('中间区', 'total') }}</div></el-card></el-col>
      <el-col :span="8"><el-card shadow="hover" :style="{ borderLeft: '3px solid #E74C3C' }"><div style="font-size: 11px; color: var(--text-secondary)">边缘区 Edge Zone</div><div style="font-size: 16px; font-weight: bold; color: #E74C3C">{{ getZoneYield('边缘区') }}%</div><div style="font-size: 11px; color: var(--text-secondary)">{{ getZoneStat('边缘区', 'pass') }} / {{ getZoneStat('边缘区', 'total') }}</div></el-card></el-col>
    </el-row>

    <el-card style="margin-top: 12px">
      <div ref="chartRef" :style="{ height: localHeight + 'px' }" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import { analysisApi } from '../../../api/analysis'

const props = defineProps<{ params: string[]; loading: boolean; waferData: any; waferError?: string | null; fileId?: number }>()
const emit = defineEmits<{ load: [param: string, colorBy: string]; loadGlobal: [colorBy: string] }>()
const { colors } = useEChartsTheme()

const localParam = ref('')
const localColorBy = ref('result')
const localHeight = ref(550)
const localShowEdge = ref(true)
const zonalData = ref<any>(null)
const COLORS_WAFER_SITE_8 = ['#2ECC71', '#3498DB', '#9B59B6', '#E67E22', '#1ABC9C', '#F39C12', '#E74C3C', '#34495E']

function getZoneYield(name: string): string { const zone = zonalData.value?.zones?.find((z: any) => z.name === name); return zone ? zone.yield.toFixed(1) : '-' }
function getZoneStat(name: string, key: string): string | number { const zone = zonalData.value?.zones?.find((z: any) => z.name === name); return zone ? (zone[key] ?? '-') : '-' }

async function fetchZonalYield() {
  if (!props.fileId) return
  try { const { data } = await analysisApi.getZonalYield(props.fileId, localParam.value || undefined); zonalData.value = data } catch { zonalData.value = null }
}

function onLoad() { zonalData.value = null; emit('load', localParam.value, localColorBy.value); if (localColorBy.value === 'zone' && props.fileId) fetchZonalYield() }
function onLoadGlobal() { zonalData.value = null; emit('loadGlobal', localColorBy.value); if (localColorBy.value === 'zone' && props.fileId) fetchZonalYield() }
function onReRender() { /* triggers watch via localShowEdge change */ }

function buildOption() {
  if (!props.waferData) return {}
  const tc = colors.value.textColor
  const data = props.waferData
  const pts: any[] = data.points || []
  const wafer = data.wafer
  const colorBy = localColorBy.value
  const series: any[] = []

  if (colorBy === 'site' && pts.some((p: any) => p.color_group)) {
    const siteMap = new Map<string, any[]>()
    for (const p of pts) { const g = p.color_group || 'Unknown'; if (!siteMap.has(g)) siteMap.set(g, []); siteMap.get(g)!.push(p) }
    Array.from(siteMap.keys()).sort().forEach((siteName, idx) => {
      series.push({ name: siteName, type: 'scatter', symbol: 'rect', symbolSize: [8, 8], data: siteMap.get(siteName)!.map((p: any) => ({ value: [p.x, p.y], serial: p.serial, bin: p.bin, site: p.site, status: p.status })), itemStyle: { color: COLORS_WAFER_SITE_8[idx % COLORS_WAFER_SITE_8.length], opacity: 0.9 } })
    })
  } else {
    const toPt = (p: any) => ({ value: [p.x, p.y], serial: p.serial, bin: p.bin, site: p.site, status: p.status })
    series.push({ name: 'Pass', type: 'scatter', symbol: 'rect', symbolSize: [8, 8], data: pts.filter((p: any) => p.status === 'Pass').map(toPt), itemStyle: { color: '#2ECC71', opacity: 0.9 } })
    series.push({ name: 'Fail', type: 'scatter', symbol: 'rect', symbolSize: [8, 8], data: pts.filter((p: any) => p.status === 'Fail').map(toPt), itemStyle: { color: '#E74C3C', opacity: 0.95 } })
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
      for (const zd of [{ name: '中心区', ratio: 1.0 / 3.0, color: '#2ECC71' }, { name: '中间区', ratio: 2.0 / 3.0, color: '#F39C12' }, { name: '边缘区', ratio: 1.0, color: '#E74C3C' }]) {
        const pts2: number[][] = []; const actualR = r * zd.ratio; for (let i = 0; i < 120; i++) { const a = (2 * Math.PI * i) / 120; pts2.push([cx + actualR * Math.cos(a), cy + actualR * Math.sin(a)]) }
        series.push({ name: zd.name, type: 'scatter', symbol: 'circle', symbolSize: 2, data: pts2.map(pt => ({ value: pt })), itemStyle: { color: zd.color, opacity: 0.6 }, silent: true, z: 1 })
      }
    }
  }

  const stats = data.stats || {}; const yieldRate = pts.length > 0 ? ((100 * (stats.pass_count || 0)) / pts.length).toFixed(1) : '0.0'
  return {
    title: { text: 'Wafer Map', subtext: `Total: ${pts.length} | Yield: ${yieldRate}%`, left: 'center' },
    tooltip: { trigger: 'item', formatter: (p: any) => { if (!p.value || !Array.isArray(p.value)) return p.name; const d = p.data; let h = `<b>${d.status || p.seriesName}</b><br/>X: ${p.value[0]} | Y: ${p.value[1]}<br/>`; if (d.serial != null) h += `Serial: ${d.serial}<br/>`; if (d.bin != null) h += `Bin: ${d.bin}<br/>`; if (d.site != null) h += `Site: ${d.site}<br/>`; return h }, backgroundColor: 'rgba(255,255,255,0.95)', borderColor: '#ccc', textStyle: { color: '#333' }, extraCssText: 'box-shadow:0 2px 8px rgba(0,0,0,0.15);border-radius:4px;padding:8px 12px;' },
    legend: { data: series.map((s: any) => s.name), bottom: 10, type: 'scroll', textStyle: { color: tc } },
    toolbox: { feature: { saveAsImage: { title: '保存', pixelRatio: 2 }, dataZoom: { title: { zoom: '缩放', back: '还原' } }, restore: { title: '还原' } }, right: 20, top: 20 },
    grid: { left: 50, right: 60, top: 60, bottom: 50 },
    xAxis: { type: 'value', name: data.x_col ?? 'X', nameTextStyle: { color: tc }, scale: true, axisLabel: { formatter: (v: number) => v.toFixed(0), color: tc } },
    yAxis: { type: 'value', name: data.y_col ?? 'Y', nameTextStyle: { color: tc }, scale: true, axisLabel: { formatter: (v: number) => v.toFixed(0), color: tc } },
    dataZoom: [{ type: 'slider', xAxisIndex: 0, start: 0, end: 100 }, { type: 'slider', yAxisIndex: 0, start: 0, end: 100 }, { type: 'inside', xAxisIndex: 0 }, { type: 'inside', yAxisIndex: 0 }],
    series,
  }
}

const { chartRef } = useChart(buildOption, [() => props.waferData, localShowEdge, localColorBy, zonalData])
void chartRef // bound to <div ref="chartRef"> in template
</script>
