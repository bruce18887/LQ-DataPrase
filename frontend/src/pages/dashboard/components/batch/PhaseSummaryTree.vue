<template>
  <el-table
    :data="treeData"
    row-key="key"
    :tree-props="{ children: 'children' }"
    stripe
    size="small"
    :border="true"
  >
    <el-table-column prop="phase" label="阶段" min-width="220" show-overflow-tooltip>
      <template #default="{ row }">
        <span :class="{ 'stage-parent': isParent(row) }">
          {{ isParent(row) ? row.stage : row.phase }}
        </span>
      </template>
    </el-table-column>
    <el-table-column prop="file_count" label="文件数" width="80" align="center" />
    <el-table-column prop="total" label="测试总数" width="100" align="center" />
    <el-table-column prop="pass_count" label="Pass" width="90" align="center" />
    <el-table-column prop="fail_count" label="Fail" width="80" align="center">
      <template #default="{ row }">
        <span :style="{ color: row.fail_count > 0 ? 'var(--color-error)' : 'var(--color-success)', fontWeight: 'bold' }">
          {{ row.fail_count }}
        </span>
      </template>
    </el-table-column>
    <el-table-column prop="yield_pct" label="良率" width="100" align="center">
      <template #default="{ row }">
        <el-tag size="small" :type="tagType(row.yield_pct)">{{ row.yield_pct }}%</el-tag>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { PhaseSummary, StageYield } from '../../../../types'

const props = defineProps<{
  stages: StageYield[]
  phases: PhaseSummary[]
}>()

// 树形数据：stage 聚合行（父）→ 版本明细行（子）
type TreeNode = PhaseSummary & { key: string; children?: TreeNode[] }

const treeData = computed(() => {
  const groups = new Map<string, TreeNode[]>()
  for (const p of props.phases) {
    const list = groups.get(p.stage) || []
    list.push({ ...p, key: `phase:${p.phase}` } as TreeNode)
    groups.set(p.stage, list)
  }
  return props.stages.map((s) => ({
    ...s,
    key: `stage:${s.stage}`,
    children: groups.get(s.stage) || [],
  }))
})

function isParent(row: any): boolean {
  return Array.isArray(row.children)
}

function tagType(pct: number): 'success' | 'warning' | 'danger' {
  if (pct >= 95) return 'success'
  if (pct >= 90) return 'warning'
  return 'danger'
}
</script>

<style scoped>
.stage-parent {
  font-weight: 600;
}
</style>
