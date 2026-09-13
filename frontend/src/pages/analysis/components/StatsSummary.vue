<template>
  <div class="stats-summary">
    <div
      v-for="card in displayCards"
      :key="card.label"
      class="stat-item"
      :class="{ 'has-color': card.color }"
    >
      <span class="stat-label">{{ card.label }}</span>
      <span class="stat-value" :style="card.color ? { color: card.color } : undefined">
        {{ card.value }}
      </span>
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
/* 单行紧凑条（2026-09-13：原 5 列卡片网格最多 3 行 ≈126px，占掉图表纵向空间）。
   语义 token；类名 .stats-summary/.stat-item/.stat-label/.stat-value 为 e2e 契约，勿改。 */
.stats-summary {
  display: flex;
  flex-wrap: nowrap;
  align-items: baseline;
  gap: 2px 18px;
  padding: 4px 10px;
  background: var(--bg-3);
  border-radius: 6px;
  border: 1px solid var(--border-2);
  /* 强制单行（窄屏/多项时横向滚动，而非折行增高）：目标是固定 ~26px 高度，
     折行会把高度翻倍回到旧卡片网格的观感。 */
  overflow-x: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border-2) transparent;
}

.stat-item {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
}

.stat-label {
  font-size: 11px;
  color: var(--text-2);
  white-space: nowrap;
}

.stat-value {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
}
</style>
