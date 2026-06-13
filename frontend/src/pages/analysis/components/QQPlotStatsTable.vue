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
  r_squared: number
  is_normal: boolean
  n: number
}

const props = defineProps<{ result: QQPlotResult | null }>()

const tableData = computed(() => {
  if (!props.result) return []
  return [
    { label: 'R²', value: props.result.r_squared.toFixed(4) },
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
