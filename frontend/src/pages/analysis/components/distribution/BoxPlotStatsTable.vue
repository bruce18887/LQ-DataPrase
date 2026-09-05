<!-- frontend/src/pages/analysis/components/distribution/BoxPlotStatsTable.vue -->
<template>
  <el-card v-if="stats" shadow="hover" class="boxplot-stats-table" :body-style="{ padding: '8px' }">
    <div class="table-header">📊 箱线图统计</div>
    <el-table
      :data="tableData"
      size="small"
      :border="true"
      :header-cell-style="{ background: 'var(--bg-3)', fontSize: '10px', padding: '3px 6px', whiteSpace: 'nowrap' }"
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

// 后端 NaN→JSON null：overall 字段可能为 null（如过滤后计数为 0），
// 裸 .toFixed 会 TypeError 打断渲染（对齐 OutlierHintBar/QQPlotStatsTable）
const fmt = (v: unknown): string =>
  typeof v === 'number' && Number.isFinite(v) ? v.toFixed(4) : '-'

const tableData = computed(() => {
  if (!props.stats) return []
  const s = props.stats
  return [
    { label: 'Count', value: s.count },
    { label: 'Min', value: fmt(s.min) },
    { label: 'Q1', value: fmt(s.q1) },
    { label: 'Median', value: fmt(s.median) },
    { label: 'Q3', value: fmt(s.q3) },
    { label: 'Max', value: fmt(s.max) },
    { label: 'Outliers', value: s.outliers?.length ?? 0 },
  ]
})
</script>

<style scoped>
.table-header {
  font-weight: 600;
  font-size: 12px;
  color: var(--text);
  margin-bottom: 6px;
}
</style>
