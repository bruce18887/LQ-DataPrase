<template>
  <span :class="['dp-badge', `dp-badge--${type}`]">
    {{ value }}
  </span>
</template>

<script setup lang="ts">
/**
 * Badge 徽章组件
 *
 * @example
 * <Badge value="成功" type="success" />
 * <Badge value="警告" type="warning" />
 * <Badge value="错误" type="error" />
 * <Badge value="信息" type="info" />
 */

interface Props {
  value: string | number
  type?: 'success' | 'warning' | 'error' | 'info'
}

withDefaults(defineProps<Props>(), {
  type: 'info'
})
</script>

<style scoped>
.dp-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.5;
  transition: background-color 0.3s ease, color 0.3s ease, border-color 0.3s ease;
}

.dp-badge--success {
  background: color-mix(in srgb, var(--color-success) 10%, transparent);
  color: var(--color-success);
  border: 1px solid var(--color-success);
  box-shadow:
    0 0 8px color-mix(in srgb, var(--color-success) 20%, transparent),
    inset 0 0 8px color-mix(in srgb, var(--color-success) 5%, transparent);
}

.dp-badge--warning {
  background: color-mix(in srgb, var(--color-warning) 10%, transparent);
  color: var(--color-warning);
  border: 1px solid var(--color-warning);
  box-shadow:
    0 0 8px color-mix(in srgb, var(--color-warning) 20%, transparent),
    inset 0 0 8px color-mix(in srgb, var(--color-warning) 5%, transparent);
}

.dp-badge--error {
  background: color-mix(in srgb, var(--color-error) 10%, transparent);
  color: var(--color-error);
  border: 1px solid var(--color-error);
  box-shadow:
    0 0 8px color-mix(in srgb, var(--color-error) 20%, transparent),
    inset 0 0 8px color-mix(in srgb, var(--color-error) 5%, transparent);
}

.dp-badge--info {
  background: color-mix(in srgb, var(--color-info) 10%, transparent);
  color: var(--color-info);
  border: 1px solid var(--color-info);
  box-shadow:
    0 0 8px color-mix(in srgb, var(--color-info) 20%, transparent),
    inset 0 0 8px color-mix(in srgb, var(--color-info) 5%, transparent);
}

@media (prefers-reduced-motion: no-preference) {
  .dp-badge:hover {
    transform: scale(1.05);
  }
}
</style>
