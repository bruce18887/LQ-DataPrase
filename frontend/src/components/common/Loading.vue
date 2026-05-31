<template>
  <div class="dp-loading" :style="{ width: size, height: size }">
    <div class="dp-loading__spinner" :style="spinnerStyle"></div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

/**
 * Loading 加载动画组件
 *
 * @example
 * <Loading />
 * <Loading size="60px" color="#58a6ff" />
 * <Loading size="40px" color="#3fb950" />
 */

interface Props {
  size?: string
  color?: string
}

const props = withDefaults(defineProps<Props>(), {
  size: '50px',
  color: '#2563eb'
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
  border: 3px solid rgba(37, 99, 235, 0.15);
  border-top-color: var(--brand-primary);
  border-right-color: var(--brand-primary);
  border-radius: 50%;
  animation: dp-spin 0.8s linear infinite;
  box-shadow:
    0 0 15px rgba(37, 99, 235, 0.25),
    inset 0 0 15px rgba(37, 99, 235, 0.1);
}

@keyframes dp-spin {
  0% {
    transform: rotate(0deg);
  }
  100% {
    transform: rotate(360deg);
  }
}

/* 霓虹脉冲效果 */
.dp-loading__spinner::before {
  content: '';
  position: absolute;
  inset: -3px;
  border-radius: 50%;
  opacity: 0;
  animation: dp-pulse 1.5s ease-out infinite;
}

@keyframes dp-pulse {
  0% {
    opacity: 0.8;
    transform: scale(1);
  }
  100% {
    opacity: 0;
    transform: scale(1.3);
  }
}
</style>
