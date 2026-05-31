<template>
  <div>
    <el-row :gutter="12" style="margin-bottom: 12px" align="middle">
      <el-col :span="3">
        <el-button type="primary" @click="onLoad" :loading="loading" style="width: 100%">
          加载晶圆图
        </el-button>
      </el-col>
      <el-col :span="4">
        <el-select v-model="localParam" placeholder="判定参数(可选)" clearable style="width: 100%" @change="onLoad">
          <el-option v-for="p in params" :key="p" :label="p" :value="p" />
        </el-select>
      </el-col>
      <el-col :span="5">
        <el-radio-group v-model="localColorBy" @change="onLoad" style="padding-top: 4px">
          <el-radio-button value="result">按结果</el-radio-button>
          <el-radio-button value="site">按 Site</el-radio-button>
        </el-radio-group>
      </el-col>
      <el-col :span="6">
        <span style="font-size: 12px; color: #909399; margin-right: 8px">图表高度</span>
        <el-slider v-model="localHeight" :min="400" :max="900" :step="50" show-input style="flex: 1" />
      </el-col>
      <el-col :span="3">
        <el-checkbox v-model="localShowEdge" @change="onReRender">Wafer Edge</el-checkbox>
      </el-col>
      <el-col :span="3">
        <el-button type="success" size="small" @click="onLoadGlobal">
          全局判定
        </el-button>
      </el-col>
    </el-row>

    <!-- 良率统计卡片 -->
    <el-row v-if="waferData" :gutter="12" style="margin-bottom: 12px">
      <el-col :span="6">
        <el-card shadow="hover">
          <div style="font-size: 12px; color: #909399">Total Dies</div>
          <div style="font-size: 18px; font-weight: bold">{{ waferData.stats?.total ?? '-' }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div style="font-size: 12px; color: #909399">Pass Dies</div>
          <div style="font-size: 18px; font-weight: bold; color: #2ECC71">{{ waferData.stats?.pass_count ?? '-' }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div style="font-size: 12px; color: #909399">Fail Dies</div>
          <div style="font-size: 18px; font-weight: bold; color: #E74C3C">{{ waferData.stats?.fail_count ?? '-' }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <div style="font-size: 12px; color: #909399">Yield</div>
          <div :style="{ fontSize: '18px', fontWeight: 'bold', color: (waferData.stats?.yield_pct ?? 0) >= 95 ? '#2ECC71' : (waferData.stats?.yield_pct ?? 0) >= 85 ? '#F39C12' : '#E74C3C' }">
            {{ waferData.stats?.yield_pct?.toFixed(1) ?? '-' }}%
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card style="margin-top: 12px">
      <div ref="chartRef" :style="{ height: localHeight + 'px' }" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'

const props = defineProps<{
  params: string[]
  loading: boolean
  waferData: any
}>()

const emit = defineEmits<{
  load: [param: string, colorBy: string]
  loadGlobal: [colorBy: string]
}>()

const localParam = ref('')
const localColorBy = ref('result')
const localHeight = ref(550)
const localShowEdge = ref(true)
const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

const COLORS_WAFER_SITE_8 = ['#2ECC71', '#3498DB', '#9B59B6', '#E67E22', '#1ABC9C', '#F39C12', '#E74C3C', '#34495E']

function onLoad() {
  emit('load', localParam.value, localColorBy.value)
}

function onLoadGlobal() {
  emit('loadGlobal', localColorBy.value)
}

function onReRender() {
  if (props.waferData) {
    renderChart()
  }
}

function initChart() {
  if (!chartRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
  }
}

function renderChart() {
  if (!chartInstance || !props.waferData) return
  chartInstance.clear()

  const data = props.waferData
  const pts: any[] = data.points || []
  const wafer = data.wafer
  const colorBy = localColorBy.value

  const series: any[] = []

  if (colorBy === 'site' && pts.some((p: any) => p.color_group)) {
    const siteMap = new Map<string, any[]>()
    for (const p of pts) {
      const g = p.color_group || 'Unknown'
      if (!siteMap.has(g)) siteMap.set(g, [])
      siteMap.get(g)!.push(p)
    }
    const sortedSites = Array.from(siteMap.keys()).sort()
    sortedSites.forEach((siteName, idx) => {
      const sitePts = siteMap.get(siteName)!
      series.push({
        name: siteName,
        type: 'scatter',
        symbol: 'rect',
        symbolSize: [8, 8],
        data: sitePts.map((p: any) => ({
          value: [p.x, p.y],
          serial: p.serial,
          bin: p.bin,
          site: p.site,
          status: p.status,
        })),
        itemStyle: { color: COLORS_WAFER_SITE_8[idx % COLORS_WAFER_SITE_8.length], opacity: 0.9 },
      })
    })
  } else {
    const passPts = pts
      .filter((p: any) => p.status === 'Pass')
      .map((p: any) => ({
        value: [p.x, p.y],
        serial: p.serial,
        bin: p.bin,
        site: p.site,
        status: p.status,
      }))
    const failPts = pts
      .filter((p: any) => p.status === 'Fail')
      .map((p: any) => ({
        value: [p.x, p.y],
        serial: p.serial,
        bin: p.bin,
        site: p.site,
        status: p.status,
      }))

    series.push({
      name: 'Pass',
      type: 'scatter',
      symbol: 'rect',
      symbolSize: [8, 8],
      data: passPts,
      itemStyle: { color: '#2ECC71', opacity: 0.9 },
    })
    series.push({
      name: 'Fail',
      type: 'scatter',
      symbol: 'rect',
      symbolSize: [8, 8],
      data: failPts,
      itemStyle: { color: '#E74C3C', opacity: 0.95 },
    })
  }

  if (wafer && localShowEdge.value) {
    const cx = wafer.center_x
    const cy = wafer.center_y
    const r = wafer.radius

    const circlePoints: number[][] = []
    const n = 200
    for (let i = 0; i < n; i++) {
      const angle = (2 * Math.PI * i) / n
      circlePoints.push([cx + r * Math.cos(angle), cy + r * Math.sin(angle)])
    }

    const notchPoints: number[][] = []
    const notchCenter = Math.PI / 2
    const notchWidth = 0.04
    for (let i = 0; i < 20; i++) {
      const angle = notchCenter - notchWidth / 2 + notchWidth * i / 19
      notchPoints.push([cx + r * Math.cos(angle), cy + r * Math.sin(angle)])
    }

    series.push({
      name: 'Wafer Edge',
      type: 'scatter',
      symbol: 'circle',
      symbolSize: 1,
      data: circlePoints.map((pt) => ({ value: pt })),
      itemStyle: { color: '#B0BEC5', borderColor: '#78909C', borderWidth: 1.5 },
      silent: true,
      z: 0,
    })

    series.push({
      name: 'Notch',
      type: 'scatter',
      symbol: 'circle',
      symbolSize: 1,
      data: notchPoints.map((pt) => ({ value: pt })),
      itemStyle: { color: '#90A4AE' },
      silent: true,
      z: 0,
    })
  }

  const stats = data.stats || {}
  const yieldRate = pts.length > 0 ? ((100 * (stats.pass_count || 0)) / pts.length).toFixed(1) : '0.0'
  const legendData = series.map((s: any) => s.name)

  chartInstance.setOption({
    title: {
      text: 'Wafer Map',
      subtext: `Total: ${pts.length} | Yield: ${yieldRate}%`,
      left: 'center',
    },
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        if (!p.value || !Array.isArray(p.value)) return p.name
        const d = p.data
        let html = `<b>${d.status || p.seriesName}</b><br/>`
        html += `X: ${p.value[0]} | Y: ${p.value[1]}<br/>`
        if (d.serial != null) html += `Serial: ${d.serial}<br/>`
        if (d.bin != null) html += `Bin: ${d.bin}<br/>`
        if (d.site != null) html += `Site: ${d.site}<br/>`
        return html
      },
      backgroundColor: 'rgba(255, 255, 255, 0.95)',
      borderColor: '#ccc',
      textStyle: { color: '#333' },
      extraCssText: 'box-shadow: 0 2px 8px rgba(0,0,0,0.15); border-radius: 4px; padding: 8px 12px;',
    },
    legend: {
      data: legendData,
      bottom: 10,
      type: 'scroll',
    },
    toolbox: {
      feature: {
        saveAsImage: { title: '保存', pixelRatio: 2 },
        dataZoom: { title: { zoom: '缩放', back: '还原' } },
        restore: { title: '还原' },
      },
      right: 20,
      top: 20,
    },
    grid: { left: 50, right: 60, top: 60, bottom: 50 },
    xAxis: {
      type: 'value',
      name: data.x_col ?? 'X',
      scale: true,
      axisLabel: { formatter: (v: number) => v.toFixed(0) },
    },
    yAxis: {
      type: 'value',
      name: data.y_col ?? 'Y',
      scale: true,
      axisLabel: { formatter: (v: number) => v.toFixed(0) },
    },
    dataZoom: [
      { type: 'slider', xAxisIndex: 0, start: 0, end: 100 },
      { type: 'slider', yAxisIndex: 0, start: 0, end: 100 },
      { type: 'inside', xAxisIndex: 0 },
      { type: 'inside', yAxisIndex: 0 },
    ],
    series,
  })
}

function resize() {
  chartInstance?.resize()
}

watch(() => props.waferData, () => {
  nextTick(() => {
    initChart()
    renderChart()
  })
})

onMounted(() => {
  window.addEventListener('resize', resize)
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>
