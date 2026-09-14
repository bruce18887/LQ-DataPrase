<template>
  <el-card shadow="hover" :body-style="{ padding: '8px' }">
    <div class="table-header">
      📊 范围对比
      <!-- 单位每个参数只有一个（后端 unit 字段，各行同值），放表头比占一整列窄 49px：
           左栏只有 ~385px，125% 缩放时那 49px 正是 Gap/Unit 被裁掉的原因 -->
      <span v-if="unitLabel" class="table-header__unit">（{{ unitLabel }}）</span>
    </div>
    <el-table
      v-if="rangeTableData.length"
      :data="rangeTableData"
      border
      size="small"
      scrollbar-always-on
      :row-class-name="rangeRowClass"
      :header-cell-style="{ background: 'var(--bg-3)', fontSize: '10px', padding: '3px 4px', whiteSpace: 'nowrap' }"
      :cell-style="{ fontSize: '10px', padding: '3px 4px', whiteSpace: 'nowrap' }"
      table-layout="auto"
    >
      <el-table-column prop="label" label="" align="left" min-width="95" />
      <el-table-column prop="low" label="Low" align="center" min-width="60" />
      <el-table-column prop="high" label="High" align="center" min-width="60" />
      <el-table-column prop="gap" label="Gap" align="center" min-width="60" />
    </el-table>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'

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

/** 单位：后端按参数下发一个值，各行相同，故提到表头（无值时整个后缀不渲染） */
const unitLabel = computed(() => props.rangeTableData[0]?.unit || '')

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

.table-header__unit {
  font-weight: 400;
  color: var(--text-2);
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
