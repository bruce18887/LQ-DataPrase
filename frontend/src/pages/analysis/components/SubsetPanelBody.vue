<template>
  <div class="subset-body">
    <StatsSummary v-if="panel.result" :stat-cards="cardsOf(panel)" />
    <div class="subset-body__chart">
      <el-skeleton v-if="panel.loading" :rows="5" animated />
      <ErrorBanner
        v-else-if="panel.error"
        :message="panel.error"
        title="子集数据加载失败"
        @retry="retry(panel.id)"
      />
      <HistogramChart
        v-else-if="panel.result"
        :result="panel.result"
        :chart-config="store.chartConfig"
        range-type="DR"
        :bar-width-percent="store.barWidthPercent"
        :bar-overlap-percent="store.barOverlapPercent"
        :selected-param="panel.param"
        outlier-handling="off"
        enable-data-zoom
      />
      <el-empty v-else :image-size="64" description="选区内无有效数值数据" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { useSingleTabStore } from '../../../stores/analysisTabs'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import { useSubsetPanels, type SubsetPanel } from '../composables/useSubsetPanels'
import HistogramChart from './HistogramChart.vue'
import StatsSummary from './StatsSummary.vue'
import ErrorBanner from '../../../components/common/ErrorBanner.vue'

defineProps<{ panel: SubsetPanel }>()

const store = useSingleTabStore()
const { retry } = useSubsetPanels()
const { isDark } = useEChartsTheme()

// CPK 色板与 useHistogram 的 clrs 同值（dark/light 双主题）
function cpkColor(name?: string) {
  if (!name) return undefined
  const light: Record<string, string> = { green: '#047857', orange: '#7c3aed', darkorange: '#a21caf', red: '#b91c1c', gray: '#475569' }
  const dark: Record<string, string> = { green: '#14b8a6', orange: '#fcd34d', darkorange: '#a78bfa', red: '#fb7185', gray: '#e2e8f0' }
  return (isDark.value ? dark : light)[name]
}

function cardsOf(panel: SubsetPanel) {
  const r = panel.result
  if (!r) return []
  const cpk = r.cpk != null ? `${r.cpk.toFixed(4)} (${r.cpk_level})` : '-'
  const limits = r.lower_limit != null && r.upper_limit != null
    ? `[${r.lower_limit}, ${r.upper_limit}]` : '-'
  return [
    { label: 'N', value: r.total_count?.toLocaleString() ?? '-' },
    { label: 'Mean', value: r.mean?.toFixed(4) ?? '-' },
    { label: 'STD', value: r.std?.toFixed(4) ?? '-' },
    { label: 'CPK', value: cpk, color: cpkColor(r.cpk_color) },
    { label: '规格限', value: limits },
  ]
}
</script>

<style scoped>
.subset-body {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
}
.subset-body__chart {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  overflow: hidden;
  padding: 4px;
}
.subset-body__chart :deep(.el-empty) {
  --el-empty-description-color: var(--text-2);
  padding: 8px 0;
}
.subset-body__chart :deep(.el-empty__description p) {
  font-size: var(--p-fs-dense);
}
</style>