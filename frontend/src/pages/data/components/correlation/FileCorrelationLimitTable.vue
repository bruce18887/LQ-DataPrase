<template>
  <div class="fc-table fc-table-wrap">
    <!-- 模板风格信息栏：标题 + 文件对 + 口径 -->
    <div class="fc-table-info">
      <span class="info-title">Data A VS Data B（Limit 对比）</span>
      <span class="info-files">{{ result.file1_name }} <b>VS</b> {{ result.file2_name }}</span>
      <span class="info-meta">
        Limit 对比 · {{ result.totals.params }} 个测试项 ·
        {{ diffRule === 'zero' ? '规则A：Diff 必须为 0' : '规则B：B 的 Limit 不更紧' }}
      </span>
    </div>

    <el-table
      :data="result.rows"
      size="small"
      :max-height="520"
      border
      class="inner-el-table"
      :header-cell-style="headerCellStyle"
    >
      <!-- 9 列全部可见（无序列块，不受横向滑动影响） -->
      <el-table-column label="Parameters" prop="param" width="180" fixed="left" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="param-name">{{ row.param }}</span>
        </template>
      </el-table-column>
      <el-table-column label="LSL A" width="76" align="center">
        <template #default="{ row }">{{ fmtNum(row.lsl_a) }}</template>
      </el-table-column>
      <el-table-column label="USL A" width="76" align="center">
        <template #default="{ row }">{{ fmtNum(row.usl_a) }}</template>
      </el-table-column>
      <el-table-column label="LSL B" width="76" align="center">
        <template #default="{ row }">{{ fmtNum(row.lsl_b) }}</template>
      </el-table-column>
      <el-table-column label="USL B" width="76" align="center">
        <template #default="{ row }">{{ fmtNum(row.usl_b) }}</template>
      </el-table-column>
      <el-table-column label="LSL Diff" width="86" align="center">
        <template #default="{ row }">
          <span
            :class="['fc-cell', { 'fc-fail-cell': row.lsl_fail }]"
            :title="row.lsl_fail ? 'Limit Diff 未通过' : ''"
          >{{ fmtDiff(row.lsl_diff) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="USL Diff" width="86" align="center">
        <template #default="{ row }">
          <span
            :class="['fc-cell', { 'fc-fail-cell': row.usl_fail }]"
            :title="row.usl_fail ? 'Limit Diff 未通过' : ''"
          >{{ fmtDiff(row.usl_diff) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="Unit" width="70" align="center">
        <template #default="{ row }">{{ row.unit || '—' }}</template>
      </el-table-column>
      <el-table-column label="判定" width="92" align="center">
        <template #default="{ row }">
          <span :class="['verdict-badge', rowVerdict(row) === 'PASS' ? 'verdict-pass' : 'verdict-fail']"
            :title="verdictTitle(row)"
          >{{ rowVerdict(row) }}</span>
        </template>
      </el-table-column>

      <template #empty>
        <el-empty description="没有可对比的测试项" :image-size="64" />
      </template>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import type { DiffRule, FileCorrelationResult, FileCorrelationRow } from '../../../../types'

defineProps<{
  result: FileCorrelationResult
  threshold: number
  diffRule: DiffRule
}>()

function headerCellStyle() {
  return {
    background: 'var(--bg-2)',
    color: 'var(--text)',
    fontWeight: '600',
    fontSize: '12px',
  }
}

/** 数值格式化（null/undefined → '—'） */
function fmtNum(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined) return '—'
  return Number(v).toFixed(digits)
}

/** Diff 显示（保留 2 位） */
function fmtDiff(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return Number(v).toFixed(2)
}

/** Limit 判定：仅按 LSL/USL Diff 规则（超差在测试值对比视图判定列） */
function rowVerdict(row: FileCorrelationRow): 'PASS' | 'FAIL' {
  return (row.lsl_fail || row.usl_fail) ? 'FAIL' : 'PASS'
}

function verdictTitle(row: FileCorrelationRow): string {
  const parts: string[] = []
  if (row.lsl_fail) parts.push('LSL Diff 未通过')
  if (row.usl_fail) parts.push('USL Diff 未通过')
  return parts.length ? parts.join('；') : '全部通过'
}
</script>

<style scoped>
.fc-table-wrap {
  min-width: 0;
}

.fc-table-info {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 10px 12px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  flex-wrap: wrap;
}

.info-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
}

.info-files {
  font-size: 12px;
  color: var(--text-2);
}

.info-files b {
  color: var(--brand);
}

.info-meta {
  font-size: 12px;
  color: var(--text-3);
  margin-left: auto;
}

:deep(.fc-table .inner-el-table) {
  --el-table-border-color: var(--border);
  --el-table-header-bg-color: var(--bg-2);
  --el-table-bg-color: var(--bg);
  --el-table-tr-bg-color: var(--bg);
  --el-table-row-hover-bg-color: var(--bg-2);
  border-radius: 0 0 8px 8px;
  overflow: hidden;
}

:deep(.el-table th.el-table__cell) {
  font-size: 12px;
}

.fc-cell {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 12px;
}

.fc-fail-cell {
  background: color-mix(in srgb, var(--error) 22%, transparent);
  color: var(--error);
  font-weight: 600;
}

.param-name {
  font-size: 12px;
  color: var(--text);
}

.verdict-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.03em;
}

.verdict-pass {
  background: var(--success);
  color: #fff;
}

.verdict-fail {
  background: var(--error);
  color: #fff;
}
</style>
