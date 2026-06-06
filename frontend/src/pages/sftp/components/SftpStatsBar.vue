<template>
  <div class="stats-bar">
    <el-tag type="info" effect="plain" size="small">
      <el-icon><Folder /></el-icon> {{ dirCount }} 个文件夹
    </el-tag>
    <el-tag type="info" effect="plain" size="small">
      <el-icon><Document /></el-icon> {{ fileCount }} 个文件
    </el-tag>
    <el-tag type="info" effect="plain" size="small">
      <el-icon><PieChart /></el-icon> 总计 {{ formatSize(totalSize) }}
    </el-tag>
    <el-tag effect="plain" size="small">
      共 {{ totalCount }} 项
    </el-tag>
  </div>
</template>

<script setup lang="ts">
import { Folder, Document, PieChart } from '@element-plus/icons-vue'

defineProps<{
  dirCount: number
  fileCount: number
  totalSize: number
  totalCount: number
}>()

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  return (bytes / (1024 * 1024 * 1024)).toFixed(1) + ' GB'
}
</script>

<style scoped>
.stats-bar { display: flex; gap: 12px; justify-content: flex-end; padding: 0 4px; }
</style>
