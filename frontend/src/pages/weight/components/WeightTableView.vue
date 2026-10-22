<script setup lang="ts">
import { computed } from 'vue'
import type { WeightDocDto } from '../weightChartOption'
import WeightSeriesTable from './WeightSeriesTable.vue'

const props = defineProps<{
  doc: WeightDocDto
  showMean: boolean
  colors: string[]
}>()

const rowCount = computed(() =>
  props.doc.series_count + (props.showMean ? props.doc.group_count : 0),
)
</script>

<template>
  <section class="weight-table-view" data-testid="weight-table-view">
    <div class="table-desc">
      <span class="desc-text">
        {{ rowCount }} 行 · {{ doc.group_count }} 测试项 · 均值{{ showMean ? '已显示' : '已隐藏' }}
      </span>
      <span class="desc-hint">横向滚动看全部 Code，前两列固定</span>
    </div>

    <WeightSeriesTable :doc="doc" :show-mean="showMean" :colors="colors" />

    <footer class="table-note">
      表格始终列出全部测试项的全部曲线：「测试项」与「组内曲线」的勾选只影响图表画廊，不删这里的行。
      均值行随「显示均值」开关增减。
    </footer>
  </section>
</template>

<style scoped>
.weight-table-view {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.table-desc {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 12px;
  font-size: var(--p-fs-micro);
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}

.desc-hint {
  color: var(--text-3);
}

.table-note {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
}
</style>
