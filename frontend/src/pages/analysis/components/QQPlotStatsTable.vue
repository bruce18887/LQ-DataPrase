<template>
  <el-card v-if="result" shadow="hover" :body-style="{ padding: '8px' }">
    <div class="table-header">📈 QQ图统计</div>
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

interface QQPlotResult {
  r_squared: number | null
  is_normal: boolean
  n: number
  slope: number | null
  intercept: number | null
}

const props = defineProps<{ result: QQPlotResult | null }>()

// slope/intercept 由后端 probplot 最小二乘拟合下发（QQ 图参考线同源）；
// 全常数列时二者为 null（与 r_squared 同样退化），统一显示 N/A
const fmt6 = (v: unknown): string =>
  typeof v === 'number' && Number.isFinite(v) ? v.toFixed(6) : 'N/A'

const tableData = computed(() => {
  if (!props.result) return []
  // r_squared may be null when all observed values are identical (e.g. soft-bin
  // columns like SW_Bin with constant value 1.0) — scipy.stats.probplot returns
  // NaN for the correlation coefficient, which JSON-serializes to null.
  const r2 = props.result.r_squared
  const r2Text = typeof r2 === 'number' && Number.isFinite(r2) ? r2.toFixed(4) : 'N/A'
  return [
    { label: '样本量', value: props.result.n },
    { label: 'R²', value: r2Text },
    { label: 'slope', value: fmt6(props.result.slope) },
    { label: 'intercept', value: fmt6(props.result.intercept) },
    { label: '正态性', value: props.result.is_normal ? '正态' : '非正态' },
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
