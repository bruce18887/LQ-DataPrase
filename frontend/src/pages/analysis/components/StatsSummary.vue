<template>
  <div class="stats-summary">
    <div
      v-for="card in displayCards"
      :key="card.label"
      class="stat-item"
      :class="{ 'has-color': card.color }"
      :style="card.color ? { borderColor: card.color + '40', backgroundColor: card.color + '0d' } : undefined"
    >
      <div class="stat-label">{{ card.label }}</div>
      <div class="stat-value" :style="card.color ? { color: card.color } : undefined">
        {{ card.value }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

export interface StatCard {
  label: string
  value: string
  color?: string
}

const props = defineProps<{
  statCards: StatCard[]
}>()

const displayCards = computed(() => {
  const order = ['N', 'Mean', 'Median', 'STD', 'Min', 'Max', 'Range', 'CPK', 'CPK(RDL)', 'CPK(Custom)', '3σ', '6σ']
  const map = new Map<string, StatCard>()
  for (const card of props.statCards) {
    map.set(card.label, card)
  }
  const result: StatCard[] = []
  for (const key of order) {
    if (map.has(key)) {
      result.push(map.get(key)!)
    }
  }
  for (const card of props.statCards) {
    if (!order.includes(card.label)) {
      result.push(card)
    }
  }
  return result
})
</script>

<style scoped>
.stats-summary {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 5px;
  padding: 6px 8px;
  background: var(--bg-tertiary);
  border-radius: 6px;
  border: 1px solid var(--border-default);
  height: 100%;
  align-content: center;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3px 2px;
  background: var(--bg-secondary);
  border-radius: 4px;
  border: 1px solid var(--border-muted);
  min-height: 42px;
}

.stat-label {
  font-size: 10px;
  color: var(--text-secondary);
  line-height: 1.2;
  margin-bottom: 1px;
  white-space: nowrap;
}

.stat-value {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.3;
  text-align: center;
  word-break: break-all;
}
</style>
