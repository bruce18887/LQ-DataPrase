<template>
  <div class="fc-summary">
    <div class="metric-card">
      <div class="metric-label">
        公共序列
        <el-tag v-if="result.truncated" size="small" type="warning" effect="plain" class="truncate-tag">
          超限截断
        </el-tag>
      </div>
      <div class="metric-value">{{ result.totals.serials }}</div>
      <div v-if="result.truncated" class="metric-hint">仅对比前 {{ result.totals.serials }} 个序列</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">测试项</div>
      <div class="metric-value">{{ result.totals.params }}</div>
      <div class="metric-hint">{{ result.limits_only ? '仅对比 Limit' : '按文件1列顺序' }}</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">对比单元</div>
      <div class="metric-value">{{ result.totals.paired_cells.toLocaleString() }}</div>
      <div class="metric-hint">ATE×Bench 配对</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">超差单元</div>
      <div class="metric-value" :class="{ 'value-fail': result.totals.fail_cells > 0 }">
        {{ result.totals.fail_cells.toLocaleString() }}
      </div>
      <div class="metric-hint">|%Diff| 超阈值</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">Limit Diff Fail</div>
      <div class="metric-value" :class="{ 'value-fail': limitFailCount > 0 }">{{ limitFailCount }}</div>
      <div class="metric-hint">{{ diffRuleLabel }}</div>
    </div>

    <div class="metric-card">
      <div class="metric-label">总体通过率</div>
      <div class="metric-value" :class="rateClass(result.totals.overall_pass_rate)">
        {{ result.totals.overall_pass_rate.toFixed(2) }}%
      </div>
      <el-progress
        :percentage="Math.min(result.totals.overall_pass_rate, 100)"
        :show-text="false"
        :stroke-width="6"
        :color="rateColor(result.totals.overall_pass_rate)"
        class="pass-rate-bar"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DiffRule, FileCorrelationResult } from '../../../../types'

const props = defineProps<{
  result: FileCorrelationResult
  diffRule: DiffRule
}>()

const diffRuleLabel = computed(() =>
  props.diffRule === 'zero' ? '规则A：Diff 必须为 0' : '规则B：B 的 Limit 不更紧')

/** 任一测试项的 LSL/USL Diff 未通过 → Limit 对比 Fail */
const limitFailCount = computed(() =>
  props.result.rows.filter((r) => r.lsl_fail || r.usl_fail).length)

function rateClass(rate: number) {
  if (rate >= 99) return 'rate-excellent'
  if (rate >= 95) return 'rate-good'
  if (rate >= 90) return 'rate-warn'
  return 'rate-bad'
}

function rateColor(rate: number) {
  if (rate >= 99) return 'var(--color-success)'
  if (rate >= 95) return 'var(--color-info)'
  if (rate >= 90) return 'var(--color-warning)'
  return 'var(--color-error)'
}
</script>

<style scoped>
.fc-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
}

.metric-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-radius: 10px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.metric-label {
  font-size: 12px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.truncate-tag {
  flex-shrink: 0;
}

.metric-value {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  font-family: var(--font-mono);
  line-height: 1.2;
}

.metric-hint {
  font-size: 11px;
  color: var(--text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.value-fail { color: var(--color-error); }

.rate-excellent { color: var(--color-success); }
.rate-good { color: var(--color-info); }
.rate-warn { color: var(--color-warning); }
.rate-bad { color: var(--color-error); }

.pass-rate-bar {
  margin-top: 2px;
}
</style>
