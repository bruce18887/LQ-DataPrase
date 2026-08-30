<template>
  <div class="phase-summary">
    <!-- 总览条：紧凑展示原 KPI 卡片的关键信息（占位更小、信息更密），随阶段过滤联动 -->
    <div class="summary-strip" data-testid="phase-summary-strip">
      <div class="strip-item">
        <span class="strip-label">{{ labelFor('input_total') }}</span>
        <span class="strip-value">{{ formatNumber(kpi.input_total) }}</span>
      </div>
      <div class="strip-item">
        <span class="strip-label">{{ labelFor('pass') }}</span>
        <span class="strip-value strip-value--pass">{{ formatNumber(kpi.pass) }}</span>
      </div>
      <div class="strip-item">
        <span class="strip-label">{{ labelFor('fail') }}</span>
        <span class="strip-value" :class="kpi.fail > 0 ? 'strip-value--fail' : 'strip-value--ok'">
          {{ formatNumber(kpi.fail) }}
        </span>
      </div>
      <div class="strip-item">
        <span class="strip-label">{{ labelFor('yield') }}</span>
        <span class="strip-value" :class="yieldClass(kpi.overall_yield)">
          {{ formatYield(kpi.overall_yield) }}<span class="strip-unit">%</span>
        </span>
      </div>
    </div>

    <el-table
      :data="treeData"
      row-key="key"
      :tree-props="{ children: 'children' }"
      size="small"
      class="tree-table"
    >
      <el-table-column prop="phase" label="阶段" min-width="220" show-overflow-tooltip>
        <template #default="{ row }">
          <span :class="{ 'stage-parent': isParent(row) }">
            {{ isParent(row) ? row.stage : row.phase }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="file_count" label="文件数" min-width="80" align="right" />
      <el-table-column prop="total" label="测试总数" min-width="100" align="right" />
      <el-table-column prop="pass_count" label="Pass" min-width="90" align="right" />
      <el-table-column prop="fail_count" label="Fail" min-width="80" align="right">
        <template #default="{ row }">
          <span :style="{ color: row.fail_count > 0 ? 'var(--error)' : 'var(--success)', fontWeight: 'bold' }">
            {{ row.fail_count }}
          </span>
        </template>
      </el-table-column>
      <el-table-column prop="yield_pct" label="良率" min-width="100" align="center">
        <template #default="{ row }">
          <YieldBadge :value="row.yield_pct" />
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { PhaseSummary, StageYield } from '../../../../types'
import YieldBadge from '../../../../components/common/YieldBadge.vue'

const props = defineProps<{
  stages: StageYield[]
  phases: PhaseSummary[]
  /** 总览条数据：批次整体（未过滤）或当前选中阶段（阶段过滤联动） */
  kpi: {
    input_total: number
    pass: number
    fail: number
    overall_yield: number | null
  }
  /** 当前是否处于阶段过滤态（决定总览条文案） */
  stageFiltered?: boolean
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

function formatNumber(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '-'
  return n.toLocaleString()
}

function formatYield(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '-'
  return n.toFixed(2)
}

function yieldClass(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return ''
  if (n >= 95) return 'strip-value--good'
  if (n >= 90) return 'strip-value--warn'
  return 'strip-value--bad'
}

const yieldLabels: Record<string, string> = {
  input_total: '投入数量',
  pass: '总 Pass',
  fail: '总 Fail',
  yield: '整体良率',
}

const stageYieldLabels: Record<string, string> = {
  input_total: '测试总数',
  pass: 'Pass',
  fail: 'Fail',
  yield: '良率',
}

function labelFor(key: string): string {
  const map = props.stageFiltered ? stageYieldLabels : yieldLabels
  return map[key] ?? key
}
</script>

<style scoped>
.stage-parent {
  font-weight: 600;
}

/* T2 纯分隔：数字列 tabular-nums */
.tree-table {
  font-variant-numeric: tabular-nums;
}

/* —— 总览条（对齐单文件规格 / 审阅页：卡内 --bg 底、圆角 10） —— */
.summary-strip {
  display: flex;
  align-items: stretch;
  gap: 10px;
  flex-wrap: wrap;
  row-gap: 8px;
  margin-bottom: 12px;
  padding: 9px 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg);
}

.strip-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  padding: 2px 18px;
  border-right: 1px solid var(--border-2);
}

.strip-item:last-child {
  border-right: none;
}

.strip-label {
  font-size: 11px;
  color: var(--text-2);
}

.strip-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.strip-unit {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-2);
  margin-left: 1px;
}

.strip-value--pass {
  color: var(--success);
}

.strip-value--fail {
  color: var(--error);
}

.strip-value--ok {
  color: var(--success);
}

.strip-value--good {
  color: var(--success);
}

.strip-value--warn {
  color: var(--warn);
}

.strip-value--bad {
  color: var(--error);
}

@media (max-width: 720px) {
  .strip-item {
    padding: 2px 10px;
  }
}
</style>
