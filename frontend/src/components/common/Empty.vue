<template>
  <div class="dp-empty">
    <div class="dp-empty__icon">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <circle cx="12" cy="12" r="10"></circle>
        <line x1="12" y1="8" x2="12" y2="12"></line>
        <line x1="12" y1="16" x2="12.01" y2="16"></line>
      </svg>
    </div>
    <div class="dp-empty__text">
      {{ description }}
    </div>
    <div v-if="$slots.default" class="dp-empty__extra">
      <slot></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * Empty 空状态组件
 *
 * @example
 * <Empty description="暂无数据" />
 * <Empty description="没有找到相关内容">
 *   <Button variant="primary">刷新</Button>
 * </Empty>
 */

interface Props {
  description?: string
}

withDefaults(defineProps<Props>(), {
  description: '暂无数据'
})
</script>

<style scoped>
.dp-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: var(--text-secondary);
}

.dp-empty__icon {
  width: 80px;
  height: 80px;
  margin-bottom: 20px;
  color: var(--text-tertiary);
  opacity: 0.6;
  animation: dp-float 3s ease-in-out infinite;
}

.dp-empty__icon svg {
  width: 100%;
  height: 100%;
  filter: drop-shadow(0 0 8px rgba(37, 99, 235, 0.15));
}

.dp-empty__text {
  font-size: 16px;
  color: var(--text-secondary);
  margin-bottom: 16px;
  text-align: center;
}

.dp-empty__extra {
  margin-top: 8px;
}

@keyframes dp-float {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-10px);
  }
}

/* 悬停效果 */
.dp-empty:hover .dp-empty__icon {
  color: var(--brand-primary);
  opacity: 0.8;
}

.dp-empty:hover .dp-empty__icon svg {
  filter: drop-shadow(0 0 12px rgba(37, 99, 235, 0.3));
}
</style>
