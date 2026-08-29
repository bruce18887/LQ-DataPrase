<template>
  <div class="batch-summary">
    <div class="summary-item">
      <span class="summary-label">批次</span>
      <span class="summary-value">{{ batchCount }}</span>
    </div>
    <div class="summary-item">
      <span class="summary-label">文件</span>
      <span class="summary-value">{{ fileCount }}</span>
    </div>
    <div class="summary-item">
      <span class="summary-label">总大小</span>
      <span class="summary-value mono">{{ formatSize(totalSize) }}</span>
    </div>
    <div v-if="pendingDirs > 0" class="summary-item summary-warning">
      <span class="summary-label">待导入目录</span>
      <span class="summary-value">{{ pendingDirs }}</span>
    </div>
    <div style="flex:1" />
    <el-button size="small" text @click="emit('refresh')">
      <el-icon><Refresh /></el-icon> 刷新
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'
import { formatSize } from '../../../utils/format'

defineProps<{
  batchCount: number
  fileCount: number
  totalSize: number
  pendingDirs: number
}>()

const emit = defineEmits<{
  refresh: []
}>()
</script>

<style scoped>
.batch-summary {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 14px;
  margin-bottom: 14px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  flex-wrap: wrap;
}

.summary-item {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.summary-label {
  font-size: 12px;
  color: var(--text-3);
}

.summary-value {
  font-size: 15px;
  font-weight: 700;
  color: var(--brand);
}

.summary-warning .summary-value {
  color: var(--warn);
}

/* Night theme overrides */
:root[data-theme="night"] .batch-summary {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.08);
}
</style>
