<template>
  <!-- Site 良率 = 柱线组合（指南 §11.1）：柱色阶（≥95 绿/≥90 琥珀/<90 红）
       + --info 良率折线；卡头右侧 3 pills（最高/最低/Δ）。
       gauge 仪表盘与最高/最低统计列已删除（overallYield 由总览条承载）。 -->
  <div class="panel-card">
    <div class="panel-head">
      <h3>🟢 Site 良率</h3>
      <div v-if="siteYieldData.length" class="yield-pills">
        <span class="yield-pill yield-pill--max" title="最高 Site 良率">
          最高 {{ siteYieldStats.maxSite }} · {{ siteYieldStats.max }}%
        </span>
        <span class="yield-pill yield-pill--min" title="最低 Site 良率">
          最低 {{ siteYieldStats.minSite }} · {{ siteYieldStats.min }}%
        </span>
        <span class="yield-pill yield-pill--diff" title="最高与最低差异">
          Δ {{ siteYieldStats.diff }}%
        </span>
      </div>
    </div>
    <div class="panel-body">
      <div v-if="siteYieldData.length" ref="siteYieldBarChart" class="chart-fill" role="img" aria-label="Site良率柱线组合图" />
      <el-empty v-else :image-size="60" description="该阶段无 Site 数据" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onActivated, onBeforeUnmount } from 'vue'
import { initEchartsWhenReady, observeContainerResize, type EchartsHandle } from '../../../utils/echarts-init'
import { useThemeStore } from '../../../stores/theme'
import { formatPercent } from '../../../utils/chart-bar'

const themeStore = useThemeStore()

const props = withDefaults(defineProps<{
  siteYieldData: { Site: string; Yield: string | number; Total: number; PassCount: number }[]
  overallYield: number
  /** 兼容保留：gauge 删除后单文件/批次均为紧凑形态，参数不再生效 */
  compact?: boolean
}>(), {
  compact: false,
})

const siteYieldBarChart = ref<HTMLElement>()
let siteYieldBarHandle: EchartsHandle | null = null
let stopObserve: (() => void) | null = null

function _tc() {
  return getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#ffffff'
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

  const getYieldColor = (y: number) => y >= 95 ? 'var(--success)' : y < 90 ? 'var(--error)' : 'var(--warn)'

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const items = Array.isArray(params) ? params : [params]
        const bar = items.find((p: any) => p.seriesType === 'bar') || items[0]
        return `<b>${bar.name}</b><br/>Yield: <b>${Number(bar.value).toFixed(2)}%</b>`
      },
    },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '14%', containLabel: true },
    xAxis: {
      type: 'category',
      data: siteNames,
      axisLabel: { fontSize: 12, color: _tc(), interval: 0 },
    },
    yAxis: {
      type: 'value',
      max: 100,
      axisLabel: { formatter: '{value}%', color: _tc() },
    },
    series: [
      {
        type: 'bar',
        data: siteYields.map(y => ({
          value: y,
          itemStyle: { color: getYieldColor(y) },
        })),
        barWidth: '50%',
        label: { show: true, position: 'top', formatter: (p: any) => `${formatPercent(Number(p.value))}%`, fontSize: 12, fontWeight: 'bold' },
      },
      {
        // 良率折线：串起各 Site 走势（--info 蓝）
        type: 'line',
        data: siteYields,
        symbol: 'circle',
        symbolSize: 6,
        lineStyle: { color: 'var(--info)', width: 2 },
        itemStyle: { color: 'var(--info)' },
        tooltip: { show: false },
        z: 3,
      },
    ],
  }
}

function renderSiteYieldBarChart() {
  if (!siteYieldBarChart.value || !props.siteYieldData?.length) return
  if (siteYieldBarHandle) {
    siteYieldBarHandle.chart?.setOption(buildSiteYieldBarOption() as any, { notMerge: true, lazyUpdate: true })
  } else {
    siteYieldBarHandle = initEchartsWhenReady(siteYieldBarChart.value, { option: buildSiteYieldBarOption() as any, reuse: true })
  }
  // 数据后到时容器才挂载：RO 补挂（onMounted 时 el 可能尚不存在）
  if (!stopObserve) stopObserve = observeContainerResize(siteYieldBarChart.value, handleResize)
}

function renderAll() {
  nextTick(() => {
    renderSiteYieldBarChart()
  })
}

function handleResize() {
  siteYieldBarHandle?.chart?.resize()
}

watch(() => [props.siteYieldData, props.overallYield], () => {
  renderAll()
}, { deep: true, immediate: true })

// 主题切换时重新渲染图表，更新文字颜色
watch(() => themeStore.currentTheme, () => {
  nextTick(() => renderAll())
})

onMounted(() => {
  // 容器级 RO：隐藏 Tab 切回/缩放均可靠 resize（window resize 覆盖不到 display:none 场景）
  stopObserve = observeContainerResize(siteYieldBarChart.value, handleResize)
  renderAll()
})

onActivated(() => {
  if (siteYieldBarHandle) { siteYieldBarHandle.dispose(); siteYieldBarHandle = null }
  nextTick(() => renderAll())
})

onBeforeUnmount(() => {
  stopObserve?.()
  stopObserve = null
  siteYieldBarHandle?.dispose(); siteYieldBarHandle = null
})

defineExpose({ handleResize })
</script>

<style scoped>
/* Section 卡（§10.4 定稿：浅底带卡头） */
.panel-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg-2) 60%, var(--card));
  flex-shrink: 0;
}
.panel-head h3 {
  margin: 0;
  font-size: 13.5px;
  font-weight: 700;
  color: var(--text);
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

/* —— 卡头内联 GAP pills（批次 compact 同款） —— */
.yield-pills {
  display: flex;
  justify-content: flex-end;
  gap: 7px;
  margin-left: auto;
}
.yield-pill {
  font-size: 11.5px;
  font-weight: 600;
  padding: 2.5px 10px;
  border-radius: 999px;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.yield-pill--max {
  background: color-mix(in srgb, var(--success) 14%, transparent);
  color: var(--success);
}
.yield-pill--min {
  background: color-mix(in srgb, var(--error) 14%, transparent);
  color: var(--error);
}
.yield-pill--diff {
  background: color-mix(in srgb, var(--text-2) 16%, transparent);
  color: var(--text-2);
}
</style>
