<template>
  <el-card shadow="hover" :body-style="{ padding: '8px' }">
    <div class="table-header">📊 范围对比</div>
    <el-table
      v-if="rangeTableData.length"
      :data="rangeTableData"
      border
      size="small"
      :row-class-name="rangeRowClass"
      :header-cell-style="{ background: '#4a90d9', color: 'white', fontSize: '10px', padding: '3px 2px' }"
      :cell-style="{ fontSize: '10px', padding: '3px 4px' }"
    >
      <el-table-column prop="label" label="" min-width="85" show-overflow-tooltip />
      <el-table-column prop="low" label="Low" align="center" min-width="75" show-overflow-tooltip />
      <el-table-column prop="high" label="High" align="center" min-width="75" show-overflow-tooltip />
      <el-table-column prop="gap" label="Gap" align="center" min-width="65" show-overflow-tooltip />
      <el-table-column prop="unit" label="Unit" width="42" align="center" />
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
interface RangeRow {
  label: string
  low: string
  high: string
  gap: string
  unit: string
}

interface Props {
  rangeTableData: RangeRow[]
  rangeType: string
}

const props = defineProps<Props>()

function rangeRowClass({ row }: { row: RangeRow }) {
  const active =
    props.rangeType === 'RDL'
      ? 'RowDataLimit'
      : props.rangeType === 'DR'
        ? 'Data Range'
        : props.rangeType === 'CL'
          ? 'CustomLimit'
          : props.rangeType === 'S3'
            ? '3 Sigma'
            : props.rangeType === 'S4'
              ? '4 Sigma'
              : '6 Sigma'
  return row.label === active ? 'range-active-row' : ''
}
</script>

<style scoped>
.table-header {
  font-weight: 600;
  font-size: 12px;
  color: var(--text-primary);
  margin-bottom: 6px;
}
</style>

<style>
.range-active-row {
  background-color: #d0e8ff !important;
  font-weight: bold;
  color: #e53935;
}
</style>
