<template>
  <div :class="['dp-card', `dp-card--${variant}`]">
    <div v-if="$slots.header" class="dp-card__header">
      <slot name="header"></slot>
    </div>
    <div class="dp-card__body">
      <slot></slot>
    </div>
    <div v-if="$slots.footer" class="dp-card__footer">
      <slot name="footer"></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * Card 卡片组件
 *
 * @example
 * <Card variant="neon">
 *   <template #header>标题</template>
 *   内容区域
 *   <template #footer>底部</template>
 * </Card>
 */

interface Props {
  variant?: 'default' | 'elevated' | 'bordered' | 'neon'
}

withDefaults(defineProps<Props>(), {
  variant: 'default'
})
</script>

<style scoped>
.dp-card {
  background: var(--bg-secondary);
  border-radius: 8px;
  overflow: hidden;
  transition: box-shadow 0.3s ease, border-color 0.3s ease;
}

.dp-card--default {
  border: 1px solid var(--border-default);
}

.dp-card--elevated {
  border: 1px solid var(--border-default);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.06);
}

.dp-card--elevated:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12), 0 2px 6px rgba(0, 0, 0, 0.08);
  transform: translateY(-2px);
}

.dp-card--bordered {
  border: 2px solid var(--border-emphasis);
}

.dp-card--neon {
  border: 1px solid var(--brand-primary);
  box-shadow:
    0 0 10px rgba(37, 99, 235, 0.2),
    0 0 20px rgba(37, 99, 235, 0.1),
    inset 0 0 10px rgba(37, 99, 235, 0.05);
}

.dp-card--neon:hover {
  box-shadow:
    0 0 15px rgba(37, 99, 235, 0.3),
    0 0 30px rgba(37, 99, 235, 0.15),
    inset 0 0 15px rgba(37, 99, 235, 0.08);
}

.dp-card__header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-default);
  font-weight: 600;
  color: var(--text-primary);
}

.dp-card__body {
  padding: 20px;
  color: var(--text-secondary);
}

.dp-card__footer {
  padding: 12px 20px;
  border-top: 1px solid var(--border-default);
  background: var(--bg-tertiary);
  color: var(--text-secondary);
}
</style>
