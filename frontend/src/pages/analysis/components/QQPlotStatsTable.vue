<template>
  <el-card v-if="result" shadow="hover" :body-style="{ padding: '8px' }">
    <div class="table-header">📈 QQ图统计</div>
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

interface QQPlotResult {
  r_squared: number | null
  is_normal: boolean
  n: number
}

const props = defineProps<{ result: QQPlotResult | null }>()

const tableData = computed(() => {
  if (!props.result) return []
  // r_squared may be null when all observed values are identical (e.g. soft-bin
  // columns like SW_Bin with constant value 1.0) — scipy.stats.probplot returns
  // NaN for the correlation coefficient, which JSON-serializes to null.
  const r2 = props.result.r_squared
  const r2Text = typeof r2 === 'number' && Number.isFinite(r2) ? r2.toFixed(4) : 'N/A'
  return [
    { label: 'R²', value: r2Text },
    { label: '正态性', value: props.result.is_normal ? '正态' : '非正态' },
    { label: '样本量', value: props.result.n },
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
