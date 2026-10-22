<script setup lang="ts">
import { computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useWeightPlot } from './composables/useWeightPlot'
import { useEChartsTheme } from '../../utils/echarts-theme'
import { slotCount } from './weightChartOption'
import WeightChartPanel from './components/WeightChartPanel.vue'
import WeightEmptyState from './components/WeightEmptyState.vue'
import WeightTableView from './components/WeightTableView.vue'
import WeightWorkspaceCard from './components/WeightWorkspaceCard.vue'

const { store, loadFile, exportXlsx, toggleMean, toggleLegend } = useWeightPlot()
const { doc, visible, visibleSlots, showMean, showLegend, errorText, busy, filename } = storeToRefs(store)
const { colors } = useEChartsTheme()

const fileInput = ref<HTMLInputElement | null>(null)
const view = ref<'chart' | 'table'>('chart')

/** 每个可见测试项一张图（顺序跟文件里的组序，不跟勾选顺序）。 */
const visibleGroups = computed(() =>
  doc.value ? doc.value.groups.filter((g) => visible.value.includes(g.index)) : [])

/** 「组内曲线」那排的个数：该文件最长组有几条就几个 chip。 */
const slotTotal = computed(() => (doc.value ? slotCount(doc.value) : 0))

const rowCount = computed(() =>
  doc.value ? doc.value.series_count + (showMean.value ? doc.value.group_count : 0) : 0)

function pickFile() {
  fileInput.value?.click()
}

async function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) await loadFile(file)
  input.value = ''            // 允许再次选择同一个文件
}
</script>

<template>
  <div class="weight-page">
    <input
      id="weight-file-input"
      ref="fileInput"
      type="file"
      accept=".csv,.txt,.h,.c"
      class="sr-only"
      @change="onFileChange"
    >

    <el-alert
      v-if="errorText"
      data-testid="weight-error"
      type="error"
      :closable="false"
      show-icon
      :title="errorText"
      class="weight-error"
    />

    <template v-if="doc">
      <WeightWorkspaceCard
        :filename="filename"
        :group-count="doc.group_count"
        :series-count="doc.series_count"
        :code-max="doc.code_max"
        :show-mean="showMean"
        :show-legend="showLegend"
        :busy="busy"
        :groups="doc.groups"
        :visible="visible"
        :slot-total="slotTotal"
        :visible-slots="visibleSlots"
        :colors="colors.seriesColors"
        @pick="pickFile"
        @toggle-mean="toggleMean"
        @toggle-legend="toggleLegend"
        @export="exportXlsx"
        @update:visible="(value) => (store.visible = value)"
        @update:visible-slots="(value) => (store.visibleSlots = value)"
      />

      <!-- 页签只做导航，内容由下面两块按 view 自己渲染（同 BinSiteCrossTable 的写法）：
           画廊用 v-show 保住 14 个 ECharts 实例（切回来只 resize，不重新 init），
           明细表用 v-if，70 行 × 全 Code 列只在进入该页签时才构建。 -->
      <el-tabs v-model="view" class="weight-tabs">
        <el-tab-pane label="图表" name="chart">
          <template #label>
            图表<span class="tab-badge">{{ visibleGroups.length }}</span>
          </template>
        </el-tab-pane>
        <el-tab-pane label="数值明细" name="table">
          <template #label>
            数值明细<span class="tab-badge">{{ rowCount }}</span>
          </template>
        </el-tab-pane>
      </el-tabs>

      <main v-show="view === 'chart'" class="weight-gallery" aria-label="每个测试项一张图">
        <WeightChartPanel
          v-for="g in visibleGroups"
          :key="g.index"
          :group="g"
          :show-mean="showMean"
          :show-legend="showLegend"
          :visible-slots="visibleSlots"
        />

        <div v-if="!visibleGroups.length" class="weight-gallery-empty">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 3v18h18" />
            <path d="m7 15 4-5 3 3 5-7" />
          </svg>
          <span class="title">未选择测试项</span>
          <span class="desc">在「测试项」里勾选要画的项，或点“全选”。</span>
        </div>
      </main>

      <WeightTableView
        v-if="view === 'table'"
        :doc="doc"
        :show-mean="showMean"
        :colors="colors.seriesColors"
      />
    </template>

    <WeightEmptyState v-else @pick="pickFile" />
  </div>
</template>

<style scoped>
.weight-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
}

.weight-error {
  flex: 0 0 auto;
}

.weight-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
}

.weight-tabs :deep(.el-tabs__item) {
  font-size: var(--p-fs-small);
  font-weight: 600;
}

/* 空 pane 只当导航用，别留 EP 默认的内容盒高度 */
.weight-tabs :deep(.el-tabs__content) {
  padding: 0;
}

.tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  margin-left: 6px;
  padding: 0 5px;
  border-radius: var(--p-radius-full);
  background: color-mix(in srgb, var(--brand) 14%, transparent);
  color: var(--brand);
  font-size: var(--p-fs-micro);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.weight-gallery {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(460px, 1fr));
  gap: 14px;
  align-items: start;
}

.weight-gallery-empty {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  min-height: 260px;
  border: 1px dashed var(--border-2);
  border-radius: var(--p-radius-lg);
  background: color-mix(in srgb, var(--bg-2) 35%, transparent);
  color: var(--text-2);
}

.weight-gallery-empty svg {
  width: 30px;
  height: 30px;
  color: var(--text-3);
  opacity: 0.7;
}

.weight-gallery-empty .title {
  font-size: var(--p-fs-small);
  font-weight: 600;
  color: var(--text);
}

.weight-gallery-empty .desc {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
}
</style>
