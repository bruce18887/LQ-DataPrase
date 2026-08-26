<!-- frontend/src/pages/analysis/components/distribution/BoxPlotStatsTable.vue -->
<template>
  <el-card v-if="stats" shadow="hover" class="boxplot-stats-table" :body-style="{ padding: '8px' }">
    <div class="table-header">📊 箱线图统计</div>
    <el-table
      :data="tableData"
      size="small"
      :border="true"
      :header-cell-style="{ background: 'var(--bg-tertiary)', fontSize: '10px', padding: '3px 6px', whiteSpace: 'nowrap' }"
      :cell-style="{ fontSize: '10px', padding: '3px 6px', whiteSpace: 'nowrap' }"
      table-layout="auto"
    >
      <el-table-column prop="label" label="统计量" align="center" />
      <el-table-column prop="value" label="值" align="center" />
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface BoxPlotStats {
  count: number
  min: number
  q1: number
  median: number
  q3: number
  max: number
  outliers: number[]
}

const props = defineProps<{ stats: BoxPlotStats | null }>()

const tableData = computed(() => {
  if (!props.stats) return []
  const s = props.stats
  return [
    { label: 'Count', value: s.count },
    { label: 'Min', value: s.min.toFixed(4) },
    { label: 'Q1', value: s.q1.toFixed(4) },
    { label: 'Median', value: s.median.toFixed(4) },
    { label: 'Q3', value: s.q3.toFixed(4) },
    { label: 'Max', value: s.max.toFixed(4) },
    { label: 'Outliers', value: s.outliers.length },
  ]
})
</script>

<style scoped>
.table-header {
  font-weight: 600;
  font-size: 12px;
  color: var(--text-primary);
  margin-bottom: 6px;
}
</style>
