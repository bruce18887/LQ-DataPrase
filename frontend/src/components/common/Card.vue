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
  box-shadow: var(--shadow-md);
}

.dp-card--elevated:hover {
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px);
}

.dp-card--bordered {
  border: 2px solid var(--border-emphasis);
}

.dp-card--neon {
  border: 1px solid var(--brand-primary);
  box-shadow:
    0 0 10px color-mix(in srgb, var(--brand-primary) 20%, transparent),
    0 0 20px color-mix(in srgb, var(--brand-primary) 10%, transparent),
    inset 0 0 10px color-mix(in srgb, var(--brand-primary) 5%, transparent);
}

.dp-card--neon:hover {
  box-shadow:
    0 0 15px color-mix(in srgb, var(--brand-primary) 30%, transparent),
    0 0 30px color-mix(in srgb, var(--brand-primary) 15%, transparent),
    inset 0 0 15px color-mix(in srgb, var(--brand-primary) 8%, transparent);
}

:root.theme-night .dp-card--neon {
  box-shadow:
    0 0 10px var(--brand-primary),
    0 0 20px color-mix(in srgb, var(--brand-primary) 50%, transparent),
    inset 0 0 10px color-mix(in srgb, var(--brand-primary) 25%, transparent);
}

:root.theme-night .dp-card--neon:hover {
  box-shadow:
    0 0 15px var(--brand-primary),
    0 0 30px color-mix(in srgb, var(--brand-primary) 50%, transparent),
    inset 0 0 15px color-mix(in srgb, var(--brand-primary) 40%, transparent);
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
