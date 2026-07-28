<template>
  <el-button
    :class="['dp-button', `dp-button--${variant}`]"
    v-bind="$attrs"
  >
    <slot></slot>
  </el-button>
</template>

<script setup lang="ts">
/**
 * Button 按钮组件（扩展 Element Plus Button）
 *
 * @example
 * <Button variant="primary">主要按钮</Button>
 * <Button variant="secondary">次要按钮</Button>
 * <Button variant="neon">霓虹按钮</Button>
 */

interface Props {
  variant?: 'primary' | 'secondary' | 'neon'
}

withDefaults(defineProps<Props>(), {
  variant: 'primary'
})
</script>

<style scoped>
.dp-button {
  border-radius: 8px;
  font-weight: 500;
  transition: background-color 0.3s ease, color 0.3s ease, border-color 0.3s ease, box-shadow 0.3s ease;
}

.dp-button--primary {
  background: var(--brand-primary);
  border: none;
  color: var(--text-inverse);
}

.dp-button--primary:hover {
  background: var(--brand-primary-hover);
  box-shadow: 0 4px 12px rgba(var(--brand-primary-rgb), 0.25);
  transform: translateY(-1px);
}

.dp-button--primary:active {
  transform: translateY(0);
}

.dp-button--secondary {
  background: var(--bg-tertiary);
  border: 1px solid var(--border-emphasis);
  color: var(--text-primary);
}

.dp-button--secondary:hover {
  background: var(--border-default);
  border-color: var(--brand-primary);
}

.dp-button--neon {
  background: transparent;
  border: 1px solid var(--brand-primary);
  color: var(--brand-primary);
  box-shadow:
    0 0 5px rgba(var(--brand-primary-rgb), 0.2),
    inset 0 0 5px rgba(var(--brand-primary-rgb), 0.05);
}

.dp-button--neon:hover {
  background: rgba(var(--brand-primary-rgb), 0.08);
  box-shadow:
    0 0 15px rgba(var(--brand-primary-rgb), 0.4),
    0 0 30px rgba(var(--brand-primary-rgb), 0.2),
    inset 0 0 10px rgba(var(--brand-primary-rgb), 0.1);
  transform: translateY(-1px);
}

.dp-button--neon:active {
  transform: translateY(0);
}

@media (prefers-reduced-motion: reduce) {
  .dp-button--primary:hover,
  .dp-button--neon:hover {
    transform: none;
  }
}
</style>
