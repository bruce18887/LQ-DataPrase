<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useWeightPlot } from './composables/useWeightPlot'
import { useEChartsTheme } from '../../utils/echarts-theme'
import WeightChartPanel from './components/WeightChartPanel.vue'
import WeightGroupChips from './components/WeightGroupChips.vue'
import WeightSeriesTable from './components/WeightSeriesTable.vue'

const { store, loadFile, exportXlsx, toggleMean } = useWeightPlot()
const { doc, visible, showMean, errorText, busy, filename } = storeToRefs(store)
const { colors } = useEChartsTheme()

/** 每个可见测试项一张图（顺序跟文件里的组序，不跟勾选顺序）。 */
const visibleGroups = computed(() =>
  doc.value ? doc.value.groups.filter((g) => visible.value.includes(g.index)) : [])

async function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) await loadFile(file)
  input.value = ''            // 允许再次选择同一个文件
}
</script>

<template>
  <div class="weight-page">
    <header class="weight-topbar">
      <label class="pick-btn" for="weight-file-input">选择权重文件</label>
      <input
        id="weight-file-input"
        type="file"
        accept=".csv,.txt,.h,.c"
        class="sr-only"
        @change="onFileChange"
      >
      <span v-if="filename" class="file-name" :title="filename">{{ filename }}</span>
      <span v-if="busy" class="busy-hint">处理中…</span>
      <div class="topbar-spacer" />
      <el-button :disabled="!doc" @click="toggleMean">
        {{ showMean ? '隐藏均值' : '均值' }}
      </el-button>
      <el-button type="primary" :disabled="!doc || busy" @click="exportXlsx">
        导出 Excel
      </el-button>
    </header>

    <el-alert
      v-if="errorText"
      data-testid="weight-error"
      type="error"
      :closable="false"
      show-icon
      :title="errorText"
      class="weight-error"
    />

    <div v-if="!doc" class="weight-empty" data-testid="weight-empty-hint">
      选择一个 `double 名称[n] = { … };` 形式的权重 CSV。数据只在本页使用，不写入数据库；刷新即丢。
    </div>

    <div v-else class="weight-body">
      <section class="chart-pane">
        <div
          v-if="!visibleGroups.length"
          class="chart-empty"
          data-testid="weight-chart-empty"
        >
          未选择测试项：在右侧 chip 里勾选要画的项。
        </div>
        <WeightChartPanel
          v-for="g in visibleGroups"
          :key="g.index"
          :group="g"
          :show-mean="showMean"
        />
      </section>
      <section class="table-pane">
        <WeightGroupChips
          :groups="doc.groups"
          :visible="visible"
          :colors="colors.seriesColors"
          @update:visible="(v) => (store.visible = v)"
        />
        <WeightSeriesTable :doc="doc" :show-mean="showMean" />
      </section>
    </div>
  </div>
</template>

<style scoped>
.weight-page {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  min-height: 0;
}

.weight-topbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.pick-btn {
  display: inline-flex;
  align-items: center;
  height: 32px;
  padding: 0 14px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--card);
  color: var(--text);
  cursor: pointer;
  font-size: var(--p-fs-small);
}

.pick-btn:hover {
  border-color: var(--brand);
  color: var(--brand);
}

.file-name {
  max-width: 42ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--p-fs-small);
  color: var(--text-2);
}

.busy-hint {
  font-size: var(--p-fs-dense);
  color: var(--text-2);
}

.topbar-spacer {
  flex: 1 1 auto;
}

.weight-error {
  flex: 0 0 auto;
}

.weight-empty {
  margin: 24px auto;
  padding: 20px 24px;
  max-width: 640px;
  border: 1px dashed var(--border);
  border-radius: 6px;
  color: var(--text-2);
  font-size: var(--p-fs-small);
  line-height: 1.7;
}

.weight-body {
  display: flex;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
}

.chart-pane {
  flex: 1 1 55%;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
  padding-right: 4px;
}

.chart-empty {
  margin: 24px auto;
  padding: 16px 20px;
  border: 1px dashed var(--border);
  border-radius: 6px;
  color: var(--text-2);
  font-size: var(--p-fs-small);
}

.table-pane {
  flex: 1 1 45%;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  min-height: 0;
}
</style>
