<template>
  <div class="dp-empty">
    <div class="dp-empty__icon" aria-hidden="true">
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
 * Empty 空状态组件（指南 §10.8：图标 34 半透明 + 说明 13/600 + 主动作插槽）
 *
 * @example
 * <Empty description="暂无数据" />
 * <Empty description="没有找到相关内容">
 *   <Button variant="primary" size="small">刷新</Button>
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
  padding: 48px 20px;
  color: var(--text-2);
}

.dp-empty__icon {
  width: 34px;
  height: 34px;
  margin-bottom: 12px;
  color: var(--text-3);
  opacity: 0.5;
}

.dp-empty__icon svg {
  width: 100%;
  height: 100%;
}

.dp-empty__text {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-2);
  margin-bottom: 12px;
  text-align: center;
}

.dp-empty__extra {
  margin-top: 4px;
}
</style>
