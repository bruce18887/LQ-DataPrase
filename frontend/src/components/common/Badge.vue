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
  background: rgba(5, 150, 105, 0.1);
  color: var(--color-success);
  border: 1px solid var(--color-success);
  box-shadow:
    0 0 8px rgba(5, 150, 105, 0.2),
    inset 0 0 8px rgba(5, 150, 105, 0.05);
}

.dp-badge--warning {
  background: rgba(217, 119, 6, 0.1);
  color: var(--color-warning);
  border: 1px solid var(--color-warning);
  box-shadow:
    0 0 8px rgba(217, 119, 6, 0.2),
    inset 0 0 8px rgba(217, 119, 6, 0.05);
}

.dp-badge--error {
  background: rgba(220, 38, 38, 0.1);
  color: var(--color-error);
  border: 1px solid var(--color-error);
  box-shadow:
    0 0 8px rgba(220, 38, 38, 0.2),
    inset 0 0 8px rgba(220, 38, 38, 0.05);
}

.dp-badge--info {
  background: rgba(37, 99, 235, 0.1);
  color: var(--color-info);
  border: 1px solid var(--color-info);
  box-shadow:
    0 0 8px rgba(37, 99, 235, 0.2),
    inset 0 0 8px rgba(37, 99, 235, 0.05);
}

.dp-badge:hover {
  transform: scale(1.05);
}
</style>
