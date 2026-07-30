<template>
  <div class="site-yield">
    <div class="panel-row panel-row--h320">
      <div class="panel-card">
        <div class="panel-head">📊 Site 良率柱状图</div>
        <div class="panel-body"><div ref="siteYieldBarChart" class="chart-fill" role="img" aria-label="Site良率柱状图" /></div>
      </div>
      <div class="panel-card panel-card--col">
        <div ref="yieldGaugeChart" style="height:130px" role="img" aria-label="整体Yield仪表盘" />
        <div class="yield-stats">
          <div class="yield-stat">
            <span class="yield-stat-tag" style="background:#05966920;color:#059669">{{ siteYieldStats.maxSite }}</span>
            <span class="yield-stat-label">最高</span>
            <span class="yield-stat-value">{{ siteYieldStats.max }}%</span>
          </div>
          <div class="yield-stat">
            <span class="yield-stat-tag" style="background:#dc262620;color:#dc2626">{{ siteYieldStats.minSite }}</span>
            <span class="yield-stat-label">最低</span>
            <span class="yield-stat-value">{{ siteYieldStats.min }}%</span>
          </div>
          <div class="yield-stat">
            <span class="yield-stat-tag" style="background:#6b728020;color:#6b7280">Δ</span>
            <span class="yield-stat-label">差异</span>
            <span class="yield-stat-value">{{ siteYieldStats.diff }}%</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onActivated, onBeforeUnmount } from 'vue'
import { initEchartsWhenReady, type EchartsHandle } from '../../../utils/echarts-init'
import { useThemeStore } from '../../../stores/theme'

const themeStore = useThemeStore()

const props = defineProps<{
  siteYieldData: { Site: string; Yield: string | number; Total: number; PassCount: number }[]
  overallYield: number
}>()

const siteYieldBarChart = ref<HTMLElement>()
const yieldGaugeChart = ref<HTMLElement>()
let siteYieldBarHandle: EchartsHandle | null = null
let yieldGaugeHandle: EchartsHandle | null = null

function _tc() {
  return getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#ffffff'
}

const siteYieldStats = computed(() => {
  const siteData = props.siteYieldData || []
  if (!siteData.length) return { max: 0, min: 0, diff: 0, maxSite: '-', minSite: '-' }

  const yieldsWithSites = siteData.map((d) => {
    const yieldValue = typeof d.Yield === 'string' ? parseFloat(d.Yield) : d.Yield
    return { yield: isNaN(yieldValue) ? 0 : yieldValue, site: d.Site }
  }).filter((item) => !isNaN(item.yield))

  if (!yieldsWithSites.length) return { max: 0, min: 0, diff: 0, maxSite: '-', minSite: '-' }

  const maxItem = yieldsWithSites.reduce((prev, curr) => curr.yield > prev.yield ? curr : prev)
  const minItem = yieldsWithSites.reduce((prev, curr) => curr.yield < prev.yield ? curr : prev)

  return {
    max: Math.round(maxItem.yield * 100) / 100,
    min: Math.round(minItem.yield * 100) / 100,
    diff: Math.round((maxItem.yield - minItem.yield) * 100) / 100,
    maxSite: maxItem.site,
    minSite: minItem.site
  }
})

function buildSiteYieldBarOption() {
  const siteData = props.siteYieldData
  const siteNames = siteData.map(d => d.Site)
  const siteYields = siteData.map(d => {
    const v = typeof d.Yield === 'string' ? parseFloat(d.Yield) : d.Yield
    return isNaN(v) ? 0 : v
  })

  const getYieldColor = (y: number) => y >= 95 ? '#059669' : y < 90 ? '#dc2626' : '#d97706'

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params
        return `<b>${p.name}</b><br/>Yield: <b>${p.value.toFixed(2)}%</b>`
      },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '10%', containLabel: true },
    xAxis: {
      type: 'category',
      data: siteNames,
      axisLabel: { fontSize: 12, color: _tc() },
    },
    yAxis: {
      type: 'value',
      max: 100,
      axisLabel: { formatter: '{value}%', color: _tc() },
    },
    series: [{
      type: 'bar',
      data: siteYields.map(y => ({
        value: y,
        itemStyle: { color: getYieldColor(y) },
      })),
      barWidth: '50%',
      label: { show: true, position: 'top', formatter: '{c}%', fontSize: 12, fontWeight: 'bold' },
    }],
  }
}

function buildYieldGaugeOption() {
  const yieldPct = props.overallYield

  return {
    series: [{
      type: 'gauge',
      startAngle: 180,
      endAngle: 0,
      min: 0,
      max: 100,
      splitNumber: 10,
      axisLine: {
        lineStyle: {
          width: 8,
          color: [
            [0.90, '#dc2626'],
            [0.95, '#d97706'],
            [1, '#059669'],
          ],
        },
      },
      pointer: { icon: 'path://M12.8,0.7l12,40.1H0.7L12.8,0.7z', length: '60%', width: 6 },
      axisTick: { length: 10, lineStyle: { color: 'inherit', width: 2 } },
      splitLine: { length: 15, lineStyle: { color: 'inherit', width: 3 } },
      axisLabel: { color: _tc(), fontSize: 10, distance: -40 },
      title: { offsetCenter: [0, '-20%'], fontSize: 14 },
      detail: { fontSize: 24, offsetCenter: [0, '0%'], valueAnimation: true, formatter: '{value}%', color: 'inherit' },
      data: [{ value: Math.round(yieldPct * 100) / 100, name: '整体Yield' }],
    }],
  }
}

function renderSiteYieldBarChart() {
  if (!siteYieldBarChart.value || !props.siteYieldData?.length) return
  if (siteYieldBarHandle) {
    siteYieldBarHandle.chart?.setOption(buildSiteYieldBarOption() as any, { notMerge: true, lazyUpdate: true })
  } else {
    siteYieldBarHandle = initEchartsWhenReady(siteYieldBarChart.value, { option: buildSiteYieldBarOption() as any, reuse: true })
  }
}

function renderYieldGaugeChart() {
  if (!yieldGaugeChart.value) return
  if (yieldGaugeHandle) {
    yieldGaugeHandle.chart?.setOption(buildYieldGaugeOption() as any, { notMerge: true, lazyUpdate: true })
  } else {
    yieldGaugeHandle = initEchartsWhenReady(yieldGaugeChart.value, { option: buildYieldGaugeOption() as any, reuse: true })
  }
}

function renderAll() {
  nextTick(() => {
    renderSiteYieldBarChart()
    renderYieldGaugeChart()
  })
}

function handleResize() {
  siteYieldBarHandle?.chart?.resize()
  yieldGaugeHandle?.chart?.resize()
}

watch(() => [props.siteYieldData, props.overallYield], () => {
  renderAll()
}, { deep: true, immediate: true })

// 主题切换时重新渲染图表，更新文字颜色
watch(() => themeStore.currentTheme, () => {
  nextTick(() => renderAll())
})

onMounted(() => {
  window.addEventListener('resize', handleResize)
  renderAll()
})

onActivated(() => {
  if (siteYieldBarHandle) { siteYieldBarHandle.dispose(); siteYieldBarHandle = null }
  if (yieldGaugeHandle) { yieldGaugeHandle.dispose(); yieldGaugeHandle = null }
  nextTick(() => renderAll())
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  siteYieldBarHandle?.dispose(); siteYieldBarHandle = null
  yieldGaugeHandle?.dispose(); yieldGaugeHandle = null
})

defineExpose({ handleResize })
</script>

<style scoped>
.panel-row {
  display: flex;
  gap: 16px;
}
.panel-row--h320 {
  min-height: 320px;
}
.panel-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  overflow: hidden;
}
.panel-card--col {
  /* panel-card already sets flex column */
}
.panel-head {
  flex-shrink: 0;
  padding: 10px 16px;
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border-default);
}
.panel-body {
  flex: 1;
  min-height: 0;
  padding: 12px;
}
.chart-fill {
  width: 100%;
  height: 100%;
  min-height: 240px;
}
.yield-stats {
  display: flex;
  justify-content: space-around;
  padding: 8px 12px 12px;
}
.yield-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.yield-stat-tag {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 600;
}
.yield-stat-label {
  font-size: 11px;
  color: var(--text-secondary);
}
.yield-stat-value {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}
</style>
