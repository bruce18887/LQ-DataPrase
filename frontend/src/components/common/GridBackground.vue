<template>
  <div class="grid-background">
    <slot />
  </div>
</template>

<script setup lang="ts">
/**
 * GridBackground 网格背景组件
 * 工业技术风格 — 使用当前主题品牌色绘制装饰性网格
 */
interface Props {
  /** 网格单元大小，默认 50px */
  gridSize?: number
}

withDefaults(defineProps<Props>(), {
  gridSize: 50,
})
</script>

<style scoped>
.grid-background {
  position: relative;
  width: 100%;
  height: 100%;
  background-color: var(--bg-primary);
  background-image:
    linear-gradient(rgba(var(--brand-primary-rgb), 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--brand-primary-rgb), 0.08) 1px, transparent 1px);
  background-size: 50px 50px;
  background-position: center center;
}

/* 渐变遮罩 — 浅色主题 */
.grid-background::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: radial-gradient(
    circle at center,
    transparent 0%,
    var(--bg-primary) 100%
  );
  pointer-events: none;
}
</style>
