<template>
  <div class="fc-table-wrap">
    <!-- 模板风格信息栏：标题 + 文件对 + 口径 -->
    <div class="fc-table-info">
      <span class="info-title">Data A VS Data B</span>
      <span class="info-files">{{ result.file1_name }} <b>VS</b> {{ result.file2_name }}</span>
      <span class="info-meta">
        序列 {{ result.serials.length }} 个 · 阈值 {{ threshold }}% ·
        {{ diffRule === 'zero' ? '规则A：Diff 必须为 0' : '规则B：B 的 Limit 不更紧' }}
      </span>
    </div>

    <el-table
      :data="result.rows"
      size="small"
      :max-height="520"
      border
      class="fc-table"
      :header-cell-style="headerCellStyle"
    >
      <!-- 左侧固定组：Test Name（模板 B2:I2 组标题） -->
      <el-table-column label="Test Name" fixed="left" align="center" header-align="center">
        <el-table-column label="Parameters" prop="param" width="180" fixed="left" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="param-name">{{ row.param }}</span>
          </template>
        </el-table-column>
        <el-table-column label="LSL A" width="76" align="center" fixed="left">
          <template #default="{ row }">{{ fmtNum(row.lsl_a) }}</template>
        </el-table-column>
        <el-table-column label="USL A" width="76" align="center" fixed="left">
          <template #default="{ row }">{{ fmtNum(row.usl_a) }}</template>
        </el-table-column>
        <el-table-column label="LSL B" width="76" align="center" fixed="left">
          <template #default="{ row }">{{ fmtNum(row.lsl_b) }}</template>
        </el-table-column>
        <el-table-column label="USL B" width="76" align="center" fixed="left">
          <template #default="{ row }">{{ fmtNum(row.usl_b) }}</template>
        </el-table-column>
        <el-table-column label="LSL Diff" width="86" align="center" fixed="left">
          <template #default="{ row }">
            <span
              :class="['fc-cell', { 'fc-fail-cell': row.lsl_fail }]"
              :title="row.lsl_fail ? 'Limit Diff 未通过' : ''"
            >{{ fmtDiff(row.lsl_diff) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="USL Diff" width="86" align="center" fixed="left">
          <template #default="{ row }">
            <span
              :class="['fc-cell', { 'fc-fail-cell': row.usl_fail }]"
              :title="row.usl_fail ? 'Limit Diff 未通过' : ''"
            >{{ fmtDiff(row.usl_diff) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Unit" width="70" align="center" fixed="left">
          <template #default="{ row }">{{ row.unit || '—' }}</template>
        </el-table-column>
        <el-table-column label="判定" width="92" align="center" fixed="left">
          <template #default="{ row }">
            <span :class="['verdict-badge', rowVerdict(row) === 'PASS' ? 'verdict-pass' : 'verdict-fail']"
              :title="verdictTitle(row)"
            >{{ rowVerdict(row) }}</span>
          </template>
        </el-table-column>
      </el-table-column>

      <!-- 每序列 4 列块：ATE / Bench / Delta / % Diff（模板 J2:M2 组标题） -->
      <el-table-column
        v-for="(serial, si) in result.serials"
        :key="serial"
        :label="String(serial)"
        align="center"
        header-align="center"
      >
        <el-table-column label="ATE" width="88" align="center">
          <template #default="{ row }">{{ fmtNum(row.cells?.[si]?.ate) }}</template>
        </el-table-column>
        <el-table-column label="Bench" width="88" align="center">
          <template #default="{ row }">{{ fmtNum(row.cells?.[si]?.bench) }}</template>
        </el-table-column>
        <el-table-column label="Delta" width="88" align="center">
          <template #default="{ row }">
            <span
              :class="['fc-cell', { 'fc-fail-cell': row.cells?.[si]?.fail }]"
              :title="row.cells?.[si]?.fail ? `|%Diff| 超出阈值 ${threshold}%` : ''"
            >{{ fmtNum(row.cells?.[si]?.delta) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="% Diff" width="92" align="center">
          <template #default="{ row }">
            <span
              :class="['fc-cell', { 'fc-fail-cell': row.cells?.[si]?.fail }]"
              :title="row.cells?.[si]?.fail ? `|%Diff| 超出阈值 ${threshold}%` : ''"
            >{{ fmtPct(row.cells?.[si]?.diff_pct) }}</span>
          </template>
        </el-table-column>
      </el-table-column>

      <template #empty>
        <el-empty description="没有可对比的测试项" :image-size="64" />
      </template>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import type { DiffRule, FileCorrelationResult, FileCorrelationRow } from '../../../../types'

const props = defineProps<{
  result: FileCorrelationResult
  threshold: number
  diffRule: DiffRule
}>()

function headerCellStyle() {
  return {
    background: 'var(--bg-secondary)',
    color: 'var(--text-primary)',
    fontWeight: '600',
    fontSize: '12px',
  }
}

/** 数值格式化（null/undefined → '—'） */
function fmtNum(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined) return '—'
  return Number(v).toFixed(digits)
}

/** %Diff 显示（保留 2 位 + %） */
function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return `${Number(v).toFixed(2)}%`
}

/** Diff 显示（保留 2 位） */
function fmtDiff(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return Number(v).toFixed(2)
}

function rowVerdict(row: FileCorrelationRow): 'PASS' | 'FAIL' {
  return (row.fail_count > 0 || row.lsl_fail || row.usl_fail) ? 'FAIL' : 'PASS'
}

function verdictTitle(row: FileCorrelationRow): string {
  const parts: string[] = []
  if (row.fail_count > 0) parts.push(`${row.fail_count} 单元超差`)
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
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  flex-wrap: wrap;
}

.info-title {
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary);
}

.info-files {
  font-size: 12px;
  color: var(--text-secondary);
}

.info-files b {
  color: var(--brand-primary);
}

.info-meta {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-left: auto;
}

:deep(.fc-table) {
  --el-table-border-color: var(--border-muted);
  --el-table-header-bg-color: var(--bg-secondary);
  --el-table-bg-color: var(--bg-primary);
  --el-table-tr-bg-color: var(--bg-primary);
  --el-table-row-hover-bg-color: var(--bg-secondary);
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
  background: var(--color-fail-bg);
  color: var(--color-fail-text);
  font-weight: 600;
}

.param-name {
  font-size: 12px;
  color: var(--text-primary);
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
  background: var(--color-success);
  color: #fff;
}

.verdict-fail {
  background: var(--color-error);
  color: #fff;
}
</style>
