<script setup lang="ts">
import { computed } from 'vue'
import type { WeightDocDto } from '../weightChartOption'

const props = defineProps<{ doc: WeightDocDto; showMean: boolean }>()

interface Row {
  key: string
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
    g.series.forEach((s, i) => out.push({
      key: `${g.index}:${i}`,
      sourceIndex: s.source_index,
      name: s.name,
      isMean: false,
      decimals: s.decimals,
      cells: s.values,
    }))
    if (props.showMean) out.push({
      key: `${g.index}:mean`,
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
  const v = row.cells[code]
  if (v === null || v === undefined) return ''
  return v.toFixed(Math.min(Math.max(row.decimals, 0), 8))
}
</script>

<template>
  <div class="weight-table" data-testid="weight-rows">
    <el-table
      :data="rows"
      row-key="key"
      size="small"
      height="100%"
      :row-class-name="({ row }: { row: Row }) => (row.isMean ? 'is-mean-row' : '')"
    >
      <el-table-column label="原序号" width="80" align="right">
        <template #default="{ row }">{{ row.sourceIndex ?? '' }}</template>
      </el-table-column>
      <el-table-column prop="name" label="系列名" min-width="200" show-overflow-tooltip />
      <el-table-column
        v-for="code in codeColumns"
        :key="code"
        :label="String(code)"
        min-width="62"
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
  height: 100%;
  min-height: 320px;
}

:deep(.is-mean-row) {
  font-weight: 600;
}
</style>
