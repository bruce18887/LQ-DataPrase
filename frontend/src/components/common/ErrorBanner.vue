<template>
  <!-- 请求失败横幅（指南 §10.8 四色横幅）：失败必须说清「哪块数据、为什么、
       怎么办」，并与「没有数据」的空态区分开。 -->
  <div class="error-banner" role="alert" data-testid="error-banner">
    <span class="eb-icon">⛔</span>
    <div class="eb-body">
      <div class="eb-title">{{ title }}</div>
      <div class="eb-msg">{{ message }}</div>
    </div>
    <el-button
      v-if="showRetry"
      size="small"
      type="primary"
      plain
      @click="emit('retry')"
    >
      重试
    </el-button>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  message: string
  title?: string
  showRetry?: boolean
}>(), {
  title: '数据加载失败',
  showRetry: true,
})

const emit = defineEmits<{ retry: [] }>()
</script>

<style scoped>
.error-banner {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  margin-bottom: 12px;
  border-radius: 12px;
  border: 1px solid color-mix(in srgb, var(--error) 40%, transparent);
  background: color-mix(in srgb, var(--error) 10%, transparent);
}

.eb-icon {
  font-size: 14px;
  line-height: 1;
}

.eb-body {
  flex: 1;
  min-width: 0;
}

.eb-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--error-2);
}

.eb-msg {
  font-size: 11px;
  color: var(--text-2);
  word-break: break-all;
}
</style>
