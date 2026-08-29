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
      <YieldBadge :value="s.yield_pct" compact />
      <span class="chip-total">{{ s.total.toLocaleString() }}</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import type { StageYield } from '../../../../types'
import YieldBadge from '../../../../components/common/YieldBadge.vue'

defineProps<{
  stages: StageYield[]
  modelValue: string
}>()

defineEmits<{
  'update:modelValue': [value: string]
}>()
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
  border: 1px solid var(--border-2);
  border-radius: 999px;
  background: var(--bg-2);
  color: var(--text);
  cursor: pointer;
  font: inherit;
  transition:
    border-color 0.15s,
    color 0.15s,
    background-color 0.15s;
}

.stage-chip:hover {
  border-color: var(--brand);
}

.stage-chip.is-active {
  border-color: var(--brand);
  background: color-mix(in srgb, var(--brand) 12%, transparent);
  color: var(--brand);
}

.stage-chip:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
}

.chip-name {
  font-weight: 600;
}

.chip-total {
  font-size: 12px;
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}
</style>
