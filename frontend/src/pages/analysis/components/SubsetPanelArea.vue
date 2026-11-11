<template>
  <div v-if="panels.length" class="subset-area" data-subset-area>
    <div
      v-for="panel in panels"
      :key="panel.id"
      class="subset-panel"
      data-subset-panel
      :data-subset-id="panel.id"
      :data-subset-n="panel.result?.total_count ?? ''"
    >
      <div class="subset-panel__h">
        <span class="subset-panel__title">{{ titleOf(panel) }}</span>
        <span class="subset-panel__grow" />
        <button
          type="button"
          class="subset-panel__btn"
          title="关闭"
          aria-label="关闭子集面板"
          @click="remove(panel.id)"
        >×</button>
      </div>
      <StatsSummary v-if="panel.result" :stat-cards="cardsOf(panel)" />
      <div class="subset-panel__b">
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
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useSingleTabStore } from '../../../stores/analysisTabs'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import { subsetPanelTitle } from '../composables/selectionGeometry'
import { useSubsetPanels, type SubsetPanel } from '../composables/useSubsetPanels'
import HistogramChart from './HistogramChart.vue'
import StatsSummary from './StatsSummary.vue'
import ErrorBanner from '../../../components/common/ErrorBanner.vue'

const store = useSingleTabStore()
const { panels, remove, retry } = useSubsetPanels()
const { isDark } = useEChartsTheme()

function titleOf(panel: SubsetPanel) {
  return subsetPanelTitle(panel.param, panel.selection, panel.result?.total_count ?? null)
}

// CPK 色板与 useHistogram 的 clrs 同值（dark/light 双主题）；那边是 composable
// 内部常量，这里只取 5 色映射，不重复其统计逻辑。
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
.subset-area {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 12px;
}
@media (max-width: 900px) {
  .subset-area { grid-template-columns: minmax(0, 1fr); }
}
.subset-panel {
  height: 420px;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--bg-2, #fff);
  border: 1px solid var(--border-2, #e4e7ed);
  border-radius: 6px;
  overflow: hidden;
}
.subset-panel__h {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 28px;
  padding: 0 8px;
  background: var(--bg-3, #f8f9fa);
  border-bottom: 1px solid var(--border-2, #e4e7ed);
  font-size: var(--p-fs-dense);
  font-weight: 600;
  color: var(--text);
  flex: 0 0 auto;
}
.subset-panel__title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.subset-panel__grow { flex: 1; }
.subset-panel__btn {
  border: 0; background: transparent; cursor: pointer;
  color: var(--text-3, #9ca3af); font-size: var(--p-fs-base); line-height: 1;
  padding: 2px 6px; border-radius: 3px;
}
.subset-panel__btn:hover { color: var(--brand); background: color-mix(in srgb, var(--brand) 10%, transparent); }
.subset-panel__b {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr);
  overflow: hidden;
  padding: 4px;
}
</style>
