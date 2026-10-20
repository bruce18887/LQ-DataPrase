<script setup lang="ts">
import { computed, onDeactivated, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useWeightPlot } from './composables/useWeightPlot'
import { useEChartsTheme } from '../../utils/echarts-theme'
import WeightChartPanel from './components/WeightChartPanel.vue'
import WeightEmptyState from './components/WeightEmptyState.vue'
import WeightSeriesDrawer from './components/WeightSeriesDrawer.vue'
import WeightWorkspaceCard from './components/WeightWorkspaceCard.vue'

const { store, loadFile, exportXlsx, toggleMean } = useWeightPlot()
const { doc, visible, showMean, errorText, busy, filename } = storeToRefs(store)
const { colors } = useEChartsTheme()

const fileInput = ref<HTMLInputElement | null>(null)
const drawerOpen = ref(false)

/** 每个可见测试项一张图（顺序跟文件里的组序，不跟勾选顺序）。 */
const visibleGroups = computed(() =>
  doc.value ? doc.value.groups.filter((g) => visible.value.includes(g.index)) : [])

const rowCount = computed(() =>
  doc.value ? doc.value.series_count + (showMean.value ? doc.value.group_count : 0) : 0)

function pickFile() {
  fileInput.value?.click()
}

async function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) {
    drawerOpen.value = false
    await loadFile(file)
  }
  input.value = ''            // 允许再次选择同一个文件
}

// keep-alive：抽屉会 teleport 到 body，切页前不关会盖在别的页面上。
onDeactivated(() => { drawerOpen.value = false })
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
        :row-count="rowCount"
        :show-mean="showMean"
        :busy="busy"
        :groups="doc.groups"
        :visible="visible"
        :colors="colors.seriesColors"
        @pick="pickFile"
        @toggle-mean="toggleMean"
        @open-table="drawerOpen = true"
        @export="exportXlsx"
        @update:visible="(value) => (store.visible = value)"
      />

      <main class="weight-gallery" aria-label="每个测试项一张图">
        <WeightChartPanel
          v-for="g in visibleGroups"
          :key="g.index"
          :group="g"
          :show-mean="showMean"
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

      <WeightSeriesDrawer
        v-model="drawerOpen"
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
