<template>
  <el-card shadow="hover" :body-style="{ padding: '8px' }">
    <div class="table-header">📊 范围对比</div>
    <el-table
      v-if="rangeTableData.length"
      :data="rangeTableData"
      border
      size="small"
      scrollbar-always-on
      :row-class-name="rangeRowClass"
      :header-cell-style="{ background: 'var(--bg-3)', fontSize: '10px', padding: '3px 6px', whiteSpace: 'nowrap' }"
      :cell-style="{ fontSize: '10px', padding: '3px 6px', whiteSpace: 'nowrap' }"
      table-layout="auto"
    >
      <el-table-column prop="label" label="" align="left" min-width="95" />
      <el-table-column prop="low" label="Low" align="center" min-width="60" />
      <el-table-column prop="high" label="High" align="center" min-width="60" />
      <el-table-column prop="gap" label="Gap" align="center" min-width="60" />
      <el-table-column prop="unit" label="Unit" align="center" min-width="50" />
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
  // 异常值裁剪时行 label 带 " (cut)" 后缀，剥离后再比较否则高亮永远失效
  const label = row.label.replace(/\s*\(cut\)$/, '')
  return label === active ? 'range-active-row' : ''
}
</script>

<style scoped>
.table-header {
  font-weight: 600;
  font-size: 12px;
  color: var(--text);
  margin-bottom: 6px;
}

/* 当前 range 口径所在行：EP 把底色画在 td 上，只命中 tr 的规则会被单元格
   底色盖掉，故特指到 td.el-table__cell（含 hover 态），无需全局块与 !important */
:deep(.el-table tr.range-active-row > td.el-table__cell),
:deep(.el-table tr.range-active-row:hover > td.el-table__cell) {
  background-color: var(--active-bg);
  color: var(--brand);
  font-weight: bold;
}
</style>
