<script setup lang="ts">
import { computed } from 'vue'
import {
  formatWeightCell, groupColor,
  type WeightDocDto,
} from '../weightChartOption'

const props = defineProps<{ doc: WeightDocDto; showMean: boolean; colors: string[] }>()

interface Row {
  key: string
  groupIndex: number
  color: string
  sourceIndex: number | null
  name: string
  isMean: boolean
  decimals: number
  cells: (number | null)[]
}

/** `row-key` 必须用 `组序号:系列下标`：系列名不唯一（解析器不去重），拿名字当键会串行。 */
const rows = computed<Row[]>(() => {
  const out: Row[] = []
  for (const g of props.doc.groups) {
    const color = groupColor(props.colors, g.index)
    g.series.forEach((s, i) => out.push({
      key: `${g.index}:${i}`,
      groupIndex: g.index,
      color,
      sourceIndex: s.source_index,
      name: s.name,
      isMean: false,
      decimals: s.decimals,
      cells: s.values,
    }))
    if (props.showMean) out.push({
      key: `${g.index}:mean`,
      groupIndex: g.index,
      color,
      sourceIndex: null,
      name: g.mean.name,
      isMean: true,
      decimals: g.mean.decimals,
      cells: g.mean.values,
    })
  }
  return out
})

const codeColumns = computed(() => Array.from({ length: props.doc.code_max + 1 }, (_, i) => i))

function cellText(row: Row, code: number): string {
  return formatWeightCell(row.cells[code], row.decimals)
}

function rowClassName({ row }: { row: Row }): string {
  return row.isMean ? 'is-mean-row' : ''
}

/** 组底色交替只染系列名单格（与 xlsx 导出同口径，不整行铺底）。 */
function cellClassName({ row, column }: { row: Row; column: { property?: string } }): string {
  if (column.property !== 'name') return ''
  return [
    'weight-name-cell',
    row.isMean ? 'weight-mean-cell' : '',
    row.groupIndex % 2 === 1 ? 'weight-name-tint' : '',
  ].filter(Boolean).join(' ')
}
</script>

<template>
  <div class="weight-table" data-testid="weight-rows">
    <el-table
      :data="rows"
      row-key="key"
      size="small"
      :max-height="560"
      class="dp-table-dense"
      :row-class-name="rowClassName"
      :cell-class-name="cellClassName"
    >
      <el-table-column label="原序号" width="74" align="right" fixed="left">
        <template #default="{ row }">
          <span class="index-text">{{ row.sourceIndex ?? '' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="系列名" min-width="218" fixed="left">
        <template #default="{ row }">
          <span class="series-cell">
            <span class="series-dot" :style="{ backgroundColor: row.color }" aria-hidden="true" />
            <span class="series-name" :title="row.name">{{ row.name }}</span>
            <span v-if="row.isMean" class="mean-tag">均值</span>
          </span>
        </template>
      </el-table-column>
      <el-table-column
        v-for="code in codeColumns"
        :key="code"
        :label="String(code)"
        min-width="82"
        align="right"
      >
        <template #default="{ row }">{{ cellText(row, code) }}</template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.weight-table {
  width: 100%;
  /* 滚动高度由 el-table 自己的 max-height 承载（仓内表格一律 max-height，不靠父级给高） */
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--p-radius-md);
}

.index-text {
  font-size: var(--p-fs-dense);
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}

.series-cell {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.series-dot {
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  border-radius: 50%;
}

.series-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--p-fs-dense);
  color: var(--text);
}

.mean-tag {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  height: 17px;
  padding: 0 5px;
  border-radius: var(--p-radius-xs);
  background: color-mix(in srgb, var(--brand) 12%, transparent);
  color: var(--brand);
  font-size: var(--p-fs-micro);
  font-weight: 700;
}

:deep(.is-mean-row) {
  font-weight: 600;
}

:deep(.el-table__body td .cell) {
  font-variant-numeric: tabular-nums;
}

:deep(.el-table__cell.weight-name-cell) {
  /* 固定列必须不透明，否则横向滚动时下层单元格会透出来。night 的 --card 是半透明的，
     所以用 EP 表体底色（light #fff / night #16213e）而不是 --card。 */
  background: var(--el-table-tr-bg-color);
}

:deep(.el-table__cell.weight-name-tint) {
  background: color-mix(in srgb, var(--text) 3.5%, var(--el-table-tr-bg-color));
}

:deep(.el-table__body tr:hover .weight-name-cell) {
  background: color-mix(in srgb, var(--brand) 6%, var(--el-table-tr-bg-color));
}

:deep(.el-table__body tr:hover .weight-name-tint) {
  background: color-mix(in srgb, var(--brand) 8%, var(--el-table-tr-bg-color));
}

:deep(.el-table__cell.weight-mean-cell) {
  box-shadow: inset 2px 0 0 var(--brand);
}
</style>
