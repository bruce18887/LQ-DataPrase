<template>
  <span :class="['dp-badge', `dp-badge--${type}`, { 'dp-badge--lg': size === 'lg' }]">
    {{ value }}
  </span>
</template>

<script setup lang="ts">
/**
 * Badge 徽章组件（指南 §10.1 主变体 V1 柔和底）
 *
 * 彩底 color-mix(语义色 13%) + 同色文字，无边框、无发光、无 hover 放大；
 * 11.5px/700，圆角 6，tabular-nums；大号 12.5px（顶部条/关键位）
 *
 * @example
 * <Badge value="成功" type="success" />
 * <Badge value="98.2%" type="warning" size="lg" />
 * <Badge value="中性" type="neutral" />
 */

interface Props {
  value: string | number
  type?: 'success' | 'warning' | 'error' | 'info' | 'neutral'
  size?: 'sm' | 'lg'
}

withDefaults(defineProps<Props>(), {
  type: 'info',
  size: 'sm'
})
</script>

<style scoped>
.dp-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 11.5px;
  font-weight: 700;
  line-height: 1.5;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.dp-badge--lg {
  font-size: 12.5px;
  padding: 3px 10px;
}

.dp-badge--success {
  background: color-mix(in srgb, var(--success) 13%, transparent);
  color: var(--success);
}

.dp-badge--warning {
  background: color-mix(in srgb, var(--warn) 13%, transparent);
  color: var(--warn);
}

.dp-badge--error {
  background: color-mix(in srgb, var(--error) 13%, transparent);
  color: var(--error);
}

.dp-badge--info {
  background: color-mix(in srgb, var(--info) 13%, transparent);
  color: var(--info);
}

.dp-badge--neutral {
  background: color-mix(in srgb, var(--text-2) 12%, transparent);
  color: var(--text-2);
}
</style>
