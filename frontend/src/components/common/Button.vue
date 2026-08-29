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
  background: var(--brand);
  border: none;
  color: var(--text-inverse);
}

.dp-button--primary:hover {
  background: var(--brand-2);
  box-shadow: 0 4px 12px color-mix(in srgb, var(--brand) 25%, transparent);
  transform: translateY(-1px);
}

.dp-button--primary:active {
  transform: translateY(0);
}

.dp-button--secondary {
  background: var(--bg-3);
  border: 1px solid var(--text-3);
  color: var(--text);
}

.dp-button--secondary:hover {
  background: var(--border-2);
  border-color: var(--brand);
}

.dp-button--neon {
  background: transparent;
  border: 1px solid var(--brand);
  color: var(--brand);
  box-shadow:
    0 0 5px color-mix(in srgb, var(--brand) 20%, transparent),
    inset 0 0 5px color-mix(in srgb, var(--brand) 5%, transparent);
}

.dp-button--neon:hover {
  background: color-mix(in srgb, var(--brand) 8%, transparent);
  box-shadow:
    0 0 15px color-mix(in srgb, var(--brand) 40%, transparent),
    0 0 30px color-mix(in srgb, var(--brand) 20%, transparent),
    inset 0 0 10px color-mix(in srgb, var(--brand) 10%, transparent);
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
