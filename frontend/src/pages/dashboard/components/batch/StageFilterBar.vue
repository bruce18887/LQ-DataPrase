<template>
  <div class="stage-filter-bar">
    <button
      type="button"
      class="stage-chip"
      :class="{ 'is-active': modelValue === '' }"
      @click="$emit('update:modelValue', '')"
    >
      <span class="chip-name">全部</span>
    </button>
    <button
      v-for="s in stages"
      :key="s.stage"
      type="button"
      class="stage-chip"
      :class="{ 'is-active': modelValue === s.stage }"
      :title="`${s.stage}: ${s.pass_count}/${s.total}`"
      @click="$emit('update:modelValue', modelValue === s.stage ? '' : s.stage)"
    >
      <span class="chip-name">{{ s.stage }}</span>
      <span class="chip-yield" :class="yieldClass(s.yield_pct)">{{ s.yield_pct }}%</span>
      <span class="chip-total">{{ s.total.toLocaleString() }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import type { StageYield } from '../../../../types'

defineProps<{
  stages: StageYield[]
  modelValue: string
}>()

defineEmits<{
  'update:modelValue': [value: string]
}>()

// 与各表格良率 el-tag 阈值一致：≥95 绿 / ≥90 黄 / 其余红
function yieldClass(pct: number): string {
  if (pct >= 95) return 'yield-good'
  if (pct >= 90) return 'yield-warn'
  return 'yield-bad'
}
</script>

<style scoped>
.stage-filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}

.stage-chip {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  padding: 5px 14px;
  border: 1px solid var(--border-default);
  border-radius: 999px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  cursor: pointer;
  font: inherit;
  transition:
    border-color 0.15s,
    color 0.15s,
    background-color 0.15s;
}

.stage-chip:hover {
  border-color: var(--brand-primary);
}

.stage-chip.is-active {
  border-color: var(--brand-primary);
  background: color-mix(in srgb, var(--brand-primary) 12%, transparent);
  color: var(--brand-primary);
}

.stage-chip:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: 2px;
}

.chip-name {
  font-weight: 600;
}

.chip-yield {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.chip-total {
  font-size: 12px;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}

.chip-yield.yield-good {
  color: var(--color-success);
}

.chip-yield.yield-warn {
  color: var(--color-warning);
}

.chip-yield.yield-bad {
  color: var(--color-error);
}
</style>
