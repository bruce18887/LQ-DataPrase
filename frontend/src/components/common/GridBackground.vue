<template>
  <div class="grid-background">
    <slot />
  </div>
</template>

<script setup lang="ts">
// 网格背景组件 - 工业技术风格
</script>

<style scoped>
.grid-background {
  position: relative;
  width: 100%;
  height: 100%;
  background-color: var(--bg-primary);
  background-image:
    linear-gradient(rgba(37, 99, 235, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(37, 99, 235, 0.08) 1px, transparent 1px);
  background-size: 50px 50px;
  background-position: center center;
}

/* 添加渐变遮罩效果 */
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
    rgba(250, 251, 252, 0.6) 100%
  );
  pointer-events: none;
}
</style>
