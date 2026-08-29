<template>
  <div class="dp-loading" :style="{ width: size, height: size }" role="status" aria-live="polite" aria-label="加载中">
    <div class="dp-loading__spinner" :style="spinnerStyle" aria-hidden="true"></div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

/**
 * Loading 加载动画组件（指南 §10.8：简洁品牌色环，旧霓虹脉冲已移除）
 *
 * @example
 * <Loading />
 * <Loading size="60px" />
 * <Loading size="40px" color="var(--success)" />
 */

interface Props {
  size?: string
  color?: string
}

const props = withDefaults(defineProps<Props>(), {
  size: '50px',
  color: 'var(--brand)'
})

const spinnerStyle = computed(() => ({
  borderTopColor: props.color,
  borderRightColor: props.color
}))
</script>

<style scoped>
.dp-loading {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.dp-loading__spinner {
  width: 100%;
  height: 100%;
  border: 3px solid color-mix(in srgb, var(--brand) 15%, transparent);
  border-top-color: var(--brand);
  border-right-color: var(--brand);
  border-radius: 50%;
  animation: dp-spin 0.8s linear infinite;
}

@media (prefers-reduced-motion: reduce) {
  .dp-loading__spinner {
    animation: none;
  }
}

@keyframes dp-spin {
  0% {
    transform: rotate(0deg);
  }
  100% {
    transform: rotate(360deg);
  }
}
</style>
