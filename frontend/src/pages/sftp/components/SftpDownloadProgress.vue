<template>
  <el-card class="download-progress-card" shadow="never">
    <div class="progress-info">
      <span class="progress-title">
        <el-icon><Download /></el-icon>
        {{ mode === 'file' ? `正在下载 ${progress.currentFile}` : '正在下载目录...' }}
      </span>
      <span class="progress-stats" v-if="mode === 'dir'">
        {{ progress.current }}/{{ progress.total }} 文件 ·
        {{ formatBytes(progress.bytes_done) }} / {{ formatBytes(progress.total_bytes) }}
      </span>
      <span class="progress-stats" v-else>{{ formatBytes(progress.bytes_done) }} / {{ formatBytes(progress.total_bytes) }}</span>
    </div>
    <el-progress :percentage="progress.percent" :stroke-width="12" :format="(p: number) => `${p}%`" />
    <div class="progress-detail">
      <span v-if="mode === 'dir'">{{ progress.currentFile }}</span>
      <span>{{ progress.speed > 0 ? `${progress.speed} MB/s` : '' }}{{ progress.eta > 0 ? ` · 预计剩余 ${progress.eta}s` : '' }}</span>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { Download } from '@element-plus/icons-vue'

/**
 * 下载进度卡片：
 * - mode='dir'：目录批量下载（文件名 + N/M 个文件 + 已完成字节/总字节 + 百分比/速率/ETA）
 * - mode='file'：单文件下载（文件名 + 已完成字节/总字节 + 百分比/速率/ETA）
 *
 * 两种模式的 percent 均由后端按「实际累计下载字节 / 总下载字节」计算，
 * 目录下载百分比随分块实时更新（不会卡在低百分比）。
 */
defineProps<{
  mode: 'file' | 'dir'
  progress: {
    percent: number
    speed: number
    eta: number
    currentFile: string
    current: number
    total: number
    bytes_done: number
    total_bytes: number
  }
}>()

function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
}
</script>

<style scoped>
.download-progress-card {
  border-radius: 8px;
  margin-bottom: 8px;
  border-left: 4px solid var(--brand);
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
  color: var(--text);
}
.progress-stats { font-size: 13px; color: var(--text-2); }
.progress-detail {
  display: flex;
  justify-content: space-between;
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-2);
}
</style>
