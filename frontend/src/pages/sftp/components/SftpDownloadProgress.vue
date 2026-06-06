<template>
  <el-card class="download-progress-card" shadow="never">
    <div class="progress-info">
      <span class="progress-title">
        <el-icon><Download /></el-icon> 正在下载目录...
      </span>
      <span class="progress-stats">{{ progress.current }}/{{ progress.total }} 文件</span>
    </div>
    <el-progress :percentage="progress.percent" :stroke-width="12" :format="(p: number) => `${p}%`" />
    <div class="progress-detail">
      <span>{{ progress.currentFile }}</span>
      <span>{{ progress.speed > 0 ? `${progress.speed} MB/s` : '' }}{{ progress.eta > 0 ? ` · 预计剩余 ${progress.eta}s` : '' }}</span>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { Download } from '@element-plus/icons-vue'

defineProps<{
  progress: {
    percent: number
    speed: number
    eta: number
    currentFile: string
    current: number
    total: number
  }
}>()
</script>

<style scoped>
.download-progress-card {
  border-radius: 8px;
  margin-bottom: 8px;
  border-left: 4px solid var(--brand-primary);
}
.download-progress-card :deep(.el-card__body) { padding: 14px 20px; }
.progress-info {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.progress-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 14px;
  color: var(--text-primary);
}
.progress-stats { font-size: 13px; color: var(--text-secondary); }
.progress-detail {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary);
}
</style>
