<template>
  <Transition name="zoom-fade">
    <div v-if="showIndicator" class="zoom-indicator" role="status" aria-live="polite">
      缩放 {{ Math.round(zoom * 100) }}%
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { useZoom } from '../../composables/useZoom'

// 与 App.vue 共享模块级单例状态：缩放时显示、停止后自动隐藏
const { zoom, showIndicator } = useZoom()
</script>

<style scoped>
.zoom-indicator {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 3000;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-md);
  backdrop-filter: blur(4px);
  pointer-events: none;
}

.zoom-fade-enter-active,
.zoom-fade-leave-active {
  transition:
    opacity 0.25s ease,
    transform 0.25s ease;
}

.zoom-fade-enter-from,
.zoom-fade-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
</style>
