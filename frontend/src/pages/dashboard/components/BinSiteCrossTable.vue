<template>
  <div class="bin-site-cross">
    <!-- Table: full width, horizontal scroll for 8 sites -->
    <div class="panel-card" style="margin-bottom: 12px;">
      <el-table :data="formattedBinTableData" stripe size="small" max-height="300" border class="panel-table">
        <el-table-column prop="bin" label="Bin" width="70" align="center" fixed="left">
          <template #default="{ row }">
            <el-tag :type="row.bin.includes('1') ? 'success' : row.bin === 'Total' ? 'info' : 'danger'" size="small">{{ row.bin }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column v-for="col in binSiteColumns" :key="col" :prop="col" :label="`Site ${col}`" align="center" min-width="90">
          <template #default="{ row }">
            <span class="cell-count">{{ row[col] }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="all_site" label="ALL Site" align="center" min-width="100" fixed="right">
          <template #default="{ row }">
            <el-tag :type="row.bin === 'Total' ? 'info' : 'primary'" size="small" effect="plain">{{ row.all_site }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <!-- Chart: full width below table -->
    <div class="panel-card">
      <div class="panel-head">📊 Bin × Site 柱状图</div>
      <div class="panel-body"><div ref="binBarChart" class="chart-fill" role="img" aria-label="Bin×Site柱状图" /></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { initEchartsWhenReady, type EchartsHandle } from '../../../utils/echarts-init'
import { useThemeStore } from '../../../stores/theme'

const themeStore = useThemeStore()

const props = defineProps<{
  binTableData: any[]
  binSiteColumns: string[]
}>()

const binBarChart = ref<HTMLElement>()
let binBarHandle: EchartsHandle | null = null

function _tc() {
  return getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#ffffff'
}

/** Bin × Site 交叉表 — 格式化为 "count (pct%)" */
const formattedBinTableData = computed(() => {
  const raw = props.binTableData
  const cols = props.binSiteColumns
  if (!raw.length || !cols.length) return raw

  const totalRow = raw.find(r => r.bin === 'Total')
  if (!totalRow) return raw

  return raw.map(row => {
    const formatted: Record<string, any> = { bin: row.bin, all_site: row.all_site }
    for (const col of cols) {
      const val = row[col] || 0
      const colTotal = totalRow[col] || 1
      const pct = colTotal > 0 ? ((val / colTotal) * 100).toFixed(1) : '0.0'
      formatted[col] = `${val} (${pct}%)`
    }
    const grandTotal = totalRow.all_site || 1
    const allPct = grandTotal > 0 ? ((row.all_site / grandTotal) * 100).toFixed(1) : '0.0'
    if (row.bin === 'Total') {
      formatted.all_site = row.all_site
    } else {
      formatted.all_site = `${row.all_site || 0} (${allPct}%)`
    }
    return formatted
  })
})

function buildBinBarOption() {
  const chartRows = props.binTableData.filter(r => r.bin !== 'Total').reverse()
  const bins = chartRows.map(r => r.bin)
  const sites = props.binSiteColumns

  const sitePalette = ['#11998e', '#f5576c', '#f9a825', '#4facfe', '#a8edea', '#ff6b6b', '#74b9ff', '#fd79a8']

  const series = sites.map((site, idx) => ({
    name: `Site ${site}`,
    type: 'bar' as const,
    data: chartRows.map(r => r[site] || 0),
    itemStyle: { color: sitePalette[idx % sitePalette.length] },
    barGap: '10%',
    emphasis: { focus: 'series' as const },
  }))

  return {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: any) => {
        const items = Array.isArray(params) ? params : [params]
        const total = items.reduce((s: number, p: any) => s + (p.value || 0), 0)
        let html = `<b>${items[0].axisValue}</b><br/>`
        items.forEach((p: any) => {
          html += `${p.marker} ${p.seriesName}: <b>${p.value}</b><br/>`
        })
        html += `<hr style="margin:4px 0"/>合计: <b>${total}</b>`
        return html
      },
    },
    legend: {
      bottom: 0,
      textStyle: { color: _tc(), fontSize: 12 },
    },
    grid: { left: '3%', right: '4%', bottom: '12%', top: '5%', containLabel: true },
    xAxis: { type: 'value', axisLabel: { color: _tc() } },
    yAxis: {
      type: 'category',
      data: bins,
      axisLabel: { color: _tc(), fontSize: 12 },
      inverse: true,
    },
    series,
  }
}

function renderBinBarChart() {
  if (!binBarChart.value || !props.binTableData.length || !props.binSiteColumns.length) return
  if (binBarHandle) {
    binBarHandle.chart?.setOption(buildBinBarOption() as any, { notMerge: true, lazyUpdate: true })
  } else {
    binBarHandle = initEchartsWhenReady(binBarChart.value, { option: buildBinBarOption() as any, reuse: true })
  }
}

function handleResize() {
  binBarHandle?.chart?.resize()
}

watch(() => [props.binTableData, props.binSiteColumns], () => {
  nextTick(() => renderBinBarChart())
}, { deep: true, immediate: true })

// 主题切换时重新渲染图表，更新文字颜色
watch(() => themeStore.currentTheme, () => {
  nextTick(() => renderBinBarChart())
})

onMounted(() => {
  window.addEventListener('resize', handleResize)
  nextTick(() => renderBinBarChart())
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  binBarHandle?.dispose(); binBarHandle = null
})

defineExpose({ handleResize })
</script>

<style scoped>
.panel-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  overflow: hidden;
}
.panel-head {
  padding: 10px 16px;
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border-default);
}
.panel-body {
  padding: 12px;
  height: calc(100% - 42px);
}
.chart-fill {
  width: 100%;
  height: 100%;
  min-height: 340px;
}
.panel-table {
  width: 100%;
}
.cell-count {
  font-size: 13px;
}
</style>
