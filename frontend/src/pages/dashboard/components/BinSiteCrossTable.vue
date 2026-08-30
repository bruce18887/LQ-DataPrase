<template>
  <!-- Bin × Site 交叉表（指南 §11.1）：同卡「表格 / 热力图」页签。
       表格：热力格等宽居中 `数量(行内占比%)`、合计列 `数量 (占总记录%)`；
       热力图：仅 Fail Bin，色深 = 行内集中度（ECharts heatmap）。
       embedded（批次 Bin 卡内嵌）：卡片壳由父级提供，仅渲染页签与内容。 -->
  <div class="bin-site-cross" :class="{ 'bin-site-cross--bare': embedded }">
    <div v-if="!embedded" class="panel-card">
      <div class="panel-head">
        <h3>📊 Bin × Site 交叉表</h3>
        <span class="panel-desc">卡内页签切换：精确读数 / 一眼定位问题 Site</span>
      </div>
      <div class="panel-body">
        <el-tabs v-model="view" class="bs-tabs">
          <el-tab-pane label="表格" name="table" />
          <el-tab-pane label="热力图" name="heatmap" />
        </el-tabs>
        <el-table
          v-if="view === 'table'"
          :data="formattedRows"
          size="small"
          max-height="320"
          class="bs-table"
          data-testid="bin-site-table"
        >
          <el-table-column prop="bin" label="Bin" width="80" align="center" fixed="left">
            <template #default="{ row }">
              <span v-if="row.bin === 'Total'" class="bs-total-label">Total</span>
              <span v-else class="bs-bin-label">{{ row.bin }}</span>
            </template>
          </el-table-column>
          <el-table-column v-for="col in binSiteColumns" :key="col" :label="`Site ${col}`" align="center" min-width="104">
            <template #default="{ row }">
              <span v-if="row.bin === 'Total'" class="bs-total-num">{{ row[col] }}</span>
              <span v-else class="heat-cell" :style="heatStyle(row, col)">{{ row[col] }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="all_site" label="合计" align="center" min-width="110" fixed="right">
            <template #default="{ row }">
              <span class="bs-total-num" :class="{ 'bs-fail': row._fail && row.bin !== 'Total' }">{{ row.all_site }}</span>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="view === 'heatmap'" class="bs-heatmap-wrap">
          <div v-if="heatRows.length" ref="heatmapChart" class="bs-heatmap" :style="{ height: heatHeight + 'px' }" role="img" aria-label="Bin×Site热力图" />
          <el-empty v-else :image-size="60" description="无 Fail Bin，无需热力图" />
          <p v-if="heatRows.length" class="bs-note">仅展示 Fail Bin；色深 = 行内集中度（按行最大值归一），最深格 = 问题 Site</p>
        </div>
      </div>
    </div>
    <template v-else>
      <el-tabs v-model="view" class="bs-tabs">
        <el-tab-pane label="表格" name="table" />
        <el-tab-pane label="热力图" name="heatmap" />
      </el-tabs>
      <el-table
        v-if="view === 'table'"
        :data="formattedRows"
        size="small"
        max-height="320"
        class="bs-table"
        data-testid="bin-site-table"
      >
        <el-table-column prop="bin" label="Bin" width="80" align="center" fixed="left">
          <template #default="{ row }">
            <span v-if="row.bin === 'Total'" class="bs-total-label">Total</span>
            <span v-else class="bs-bin-label">{{ row.bin }}</span>
          </template>
        </el-table-column>
        <el-table-column v-for="col in binSiteColumns" :key="col" :label="`Site ${col}`" align="center" min-width="104">
          <template #default="{ row }">
            <span v-if="row.bin === 'Total'" class="bs-total-num">{{ row[col] }}</span>
            <span v-else class="heat-cell" :style="heatStyle(row, col)">{{ row[col] }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="all_site" label="合计" align="center" min-width="110" fixed="right">
          <template #default="{ row }">
            <span class="bs-total-num" :class="{ 'bs-fail': row._fail && row.bin !== 'Total' }">{{ row.all_site }}</span>
          </template>
        </el-table-column>
      </el-table>
      <div v-if="view === 'heatmap'" class="bs-heatmap-wrap">
        <div v-if="heatRows.length" ref="heatmapChart" class="bs-heatmap" :style="{ height: heatHeight + 'px' }" role="img" aria-label="Bin×Site热力图" />
        <el-empty v-else :image-size="60" description="无 Fail Bin，无需热力图" />
        <p v-if="heatRows.length" class="bs-note">仅展示 Fail Bin；色深 = 行内集中度（按行最大值归一），最深格 = 问题 Site</p>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onActivated, onBeforeUnmount } from 'vue'
import { initEchartsWhenReady, observeContainerResize, type EchartsHandle } from '../../../utils/echarts-init'
import { useThemeStore } from '../../../stores/theme'
import { formatPercent } from '../../../utils/chart-bar'

const themeStore = useThemeStore()

const props = withDefaults(defineProps<{
  binTableData: any[]
  binSiteColumns: string[]
  /** 内嵌模式（批次 Bin 分布卡内）：不渲染卡片壳与标题 */
  embedded?: boolean
}>(), {
  embedded: false,
})

const view = ref<'table' | 'heatmap'>('table')
const heatmapChart = ref<HTMLElement>()
let heatHandle: EchartsHandle | null = null
let stopHeatObserve: (() => void) | null = null
let heatObservedEl: HTMLElement | null = null

/** 热力图容器为 v-if 条件渲染：RO 按元素身份挂载（重建后重挂） */
function attachHeatObserve() {
  const el = heatmapChart.value
  if (!el || el === heatObservedEl) return
  stopHeatObserve?.()
  heatObservedEl = el
  stopHeatObserve = observeContainerResize(el, handleResize)
}

function _tc() {
  return getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#ffffff'
}

function _token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

/** hex → rgba：visualMap 插值只认具体色值（var()/color-mix 不参与插值） */
function hexToRgba(hex: string, alpha: number): string {
  let h = hex.replace('#', '')
  if (h.length === 3) h = h.split('').map((c) => c + c).join('')
  const n = parseInt(h, 16)
  if (h.length !== 6 || Number.isNaN(n)) return `rgba(220, 38, 38, ${alpha})`
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
}

const isPassBin = (bin: string) => bin.includes('1')

/** 行内占比：该 Bin 在该 Site 的数量 ÷ 该 Bin 合计 */
const formattedRows = computed(() => {
  const raw = props.binTableData
  const cols = props.binSiteColumns
  if (!raw.length || !cols.length) return raw

  const totalRow = raw.find(r => r.bin === 'Total')
  const grandTotal = totalRow?.all_site || 0

  return raw.map(row => {
    const rowTotal = row.all_site || 0
    const formatted: Record<string, any> = { bin: row.bin, _fail: !isPassBin(row.bin) && row.bin !== 'Total' }
    for (const col of cols) {
      const val = row[col] || 0
      if (row.bin === 'Total') {
        formatted[col] = val.toLocaleString()
      } else {
        const pct = rowTotal > 0 ? (val / rowTotal) * 100 : 0
        formatted[col] = `${val.toLocaleString()}(${formatPercent(pct)}%)`
        formatted[`_pct_${col}`] = pct
      }
    }
    if (row.bin === 'Total') {
      formatted.all_site = (row.all_site || 0).toLocaleString()
    } else {
      const allPct = grandTotal > 0 ? (rowTotal / grandTotal) * 100 : 0
      formatted.all_site = `${rowTotal.toLocaleString()} (${formatPercent(allPct)}%)`
    }
    return formatted
  })
})

/** 热力格染色：仅 Fail Bin，色深随行内占比加深（10%–40%） */
function heatStyle(row: Record<string, any>, col: string) {
  if (!row._fail) return {}
  const pct = row[`_pct_${col}`] || 0
  const depth = Math.min(10 + pct * 0.75, 40)
  return { background: `color-mix(in srgb, var(--error) ${depth.toFixed(0)}%, transparent)` }
}

/** 热力图数据：仅 Fail Bin；value = [siteIdx, binIdx, count, 行内集中度] */
const heatRows = computed(() => {
  const raw = props.binTableData
  const cols = props.binSiteColumns
  const failBins = raw.filter(r => r.bin !== 'Total' && !isPassBin(r.bin))
  return failBins.map((row, bi) => {
    const rowMax = Math.max(1, ...cols.map(c => row[c] || 0))
    return cols.map((c, si) => ({
      value: [si, bi, row[c] || 0, (row[c] || 0) / rowMax],
      bin: row.bin,
      site: c,
    }))
  }).flat()
})

const heatBinNames = computed(() =>
  props.binTableData.filter(r => r.bin !== 'Total' && !isPassBin(r.bin)).map(r => r.bin)
)

const heatHeight = computed(() => 70 + heatBinNames.value.length * 42)

function buildHeatOption() {
  const sites = props.binSiteColumns
  const bins = heatBinNames.value
  const err = _token('--error') || '#dc2626'
  return {
    tooltip: {
      formatter: (p: any) => {
        const [si, bi, count] = p.value
        return `<b>${bins[bi]}</b> · Site ${sites[si]}<br/>数量: <b>${count}</b>`
      },
    },
    grid: { left: '3%', right: '4%', top: 8, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: sites.map(s => `Site ${s}`),
      splitArea: { show: true },
      axisLabel: { color: _tc(), fontSize: 12 },
    },
    yAxis: {
      type: 'category',
      data: bins,
      splitArea: { show: true },
      axisLabel: { color: _tc(), fontSize: 12 },
    },
    // 笛卡尔热力图必须配 visualMap，否则 ECharts 抛
    // “Heatmap must use with visualMap” 整系列不渲染（2026-08-30 修复）；
    // show:false 仅按行内集中度（dimension 3）着色。
    visualMap: {
      show: false,
      min: 0,
      max: 1,
      dimension: 3,
      inRange: { color: [hexToRgba(err, 0.1), hexToRgba(err, 0.45)] },
    },
    series: [{
      type: 'heatmap',
      data: heatRows.value.map(d => ({ value: d.value })),
      // 数值标签：具体色值，保证双主题可读
      label: { show: true, formatter: (p: any) => `${p.value[2]}`, color: _tc(), fontSize: 12, fontWeight: 600 },
      emphasis: { itemStyle: { shadowBlur: 6, shadowColor: 'rgba(0,0,0,0.25)' } },
    }],
  }
}

function renderHeatmap() {
  if (view.value !== 'heatmap') return
  nextTick(() => {
    if (!heatmapChart.value || !heatRows.value.length) return
    if (heatHandle) {
      heatHandle.chart?.setOption(buildHeatOption() as any, { notMerge: true, lazyUpdate: true })
    } else {
      heatHandle = initEchartsWhenReady(heatmapChart.value, { option: buildHeatOption() as any, reuse: true })
    }
    attachHeatObserve()
  })
}

function handleResize() {
  heatHandle?.chart?.resize()
}

// 页签切换 → 切到热力图时渲染（容器此前 v-show 隐藏，尺寸为 0）
watch(view, (v) => {
  if (v === 'heatmap') {
    // 新容器/隐藏切换后实例可能失效，重建
    if (heatHandle) { heatHandle.dispose(); heatHandle = null }
    renderHeatmap()
  }
})

watch(() => [props.binTableData, props.binSiteColumns], () => {
  if (view.value === 'heatmap') {
    if (heatHandle) { heatHandle.dispose(); heatHandle = null }
    renderHeatmap()
  }
}, { deep: true })

// 主题切换重建热力图（颜色/文字跟随语义层）
watch(() => themeStore.currentTheme, () => {
  if (view.value === 'heatmap') {
    if (heatHandle) { heatHandle.dispose(); heatHandle = null }
    renderHeatmap()
  }
})

onActivated(() => {
  if (heatHandle) { heatHandle.dispose(); heatHandle = null }
  renderHeatmap()
})

onBeforeUnmount(() => {
  stopHeatObserve?.()
  stopHeatObserve = null
  heatObservedEl = null
  heatHandle?.dispose(); heatHandle = null
})

defineExpose({ handleResize })
</script>

<style scoped>
/* Section 卡（§10.4 定稿） */
.panel-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  margin-bottom: 14px;
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
.panel-desc {
  font-size: 11px;
  color: var(--text-3);
}
.panel-body {
  padding: 12px 16px 14px;
}
/* embedded：外层卡片由父级提供 */
.bin-site-cross--bare .bs-tabs { margin-top: 0; }

.bs-tabs { margin-bottom: 4px; }
.bs-tabs :deep(.el-tabs__header) { margin-bottom: 8px; }

.bs-table { width: 100%; }
/* T2 纯分隔：去斑马纹由 EP 主题覆写承担 */

/* 热力格：统一等宽居中，消除纯文字/色块混排错位 */
.heat-cell {
  display: inline-block;
  width: 96px;
  padding: 1px 0;
  border-radius: 5px;
  text-align: center;
  font-variant-numeric: tabular-nums;
  font-size: 12.5px;
  color: var(--text);
}

.bs-total-num {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: var(--text);
}
.bs-total-label {
  font-weight: 700;
  color: var(--text-2);
}
/* Bin 列纯文字（2026-08-30 用户定稿：交叉表 Bin 值不用徽标勾，避免误解） */
.bs-bin-label {
  font-weight: 600;
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
.bs-fail {
  color: var(--error);
  font-weight: 700;
}

.bs-heatmap-wrap { padding: 6px 0 2px; }
.bs-heatmap { width: 100%; }
.bs-note {
  margin: 10px 0 0;
  font-size: 11.5px;
  color: var(--text-3);
}
</style>
