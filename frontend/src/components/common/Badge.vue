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
  background: color-mix(in srgb, var(--success) 10%, transparent);
  color: var(--success);
  border: 1px solid var(--success);
  box-shadow:
    0 0 8px color-mix(in srgb, var(--success) 20%, transparent),
    inset 0 0 8px color-mix(in srgb, var(--success) 5%, transparent);
}

.dp-badge--warning {
  background: color-mix(in srgb, var(--warn) 10%, transparent);
  color: var(--warn);
  border: 1px solid var(--warn);
  box-shadow:
    0 0 8px color-mix(in srgb, var(--warn) 20%, transparent),
    inset 0 0 8px color-mix(in srgb, var(--warn) 5%, transparent);
}

.dp-badge--error {
  background: color-mix(in srgb, var(--error) 10%, transparent);
  color: var(--error);
  border: 1px solid var(--error);
  box-shadow:
    0 0 8px color-mix(in srgb, var(--error) 20%, transparent),
    inset 0 0 8px color-mix(in srgb, var(--error) 5%, transparent);
}

.dp-badge--info {
  background: color-mix(in srgb, var(--info) 10%, transparent);
  color: var(--info);
  border: 1px solid var(--info);
  box-shadow:
    0 0 8px color-mix(in srgb, var(--info) 20%, transparent),
    inset 0 0 8px color-mix(in srgb, var(--info) 5%, transparent);
}

@media (prefers-reduced-motion: no-preference) {
  .dp-badge:hover {
    transform: scale(1.05);
  }
}
</style>
