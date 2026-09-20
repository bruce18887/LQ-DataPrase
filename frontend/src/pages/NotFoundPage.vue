<template>
  <div class="not-found-page">
    <div class="not-found-content">
      <h1 class="not-found-code">404</h1>
      <p class="not-found-text">页面未找到</p>
      <p class="not-found-desc">你访问的页面不存在或已被移除。</p>
      <el-button type="primary" size="large" @click="$router.push('/dashboard')">
        <el-icon><HomeFilled /></el-icon>
        返回仪表板
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { HomeFilled } from '@element-plus/icons-vue'
</script>

<style scoped>
.not-found-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
}
.not-found-content {
  text-align: center;
}
.not-found-code {
  font-size: 96px; /* @type-scale-one-off 404 装饰大字，故意远大于文案档 */
  font-weight: 700;
  color: var(--brand);
  line-height: 1;
  margin: 0 0 16px;
}
.not-found-text {
  font-size: var(--p-fs-headline);
  font-weight: 600;
  color: var(--text);
  margin: 0 0 8px;
}
.not-found-desc {
  font-size: var(--p-fs-base);
  color: var(--text-2);
  margin: 0 0 32px;
}
</style>
