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
    <!-- 目录被后端分页（默认 500 条/页）时的真实进度 + 原位「加载更多」 -->
    <template v-if="hasMore && remoteTotal">
      <el-tag type="warning" effect="plain" size="small" data-sftp-list-paging>
        已加载 {{ loadedCount }} / {{ remoteTotal }} 项
      </el-tag>
      <el-button
        link
        type="primary"
        size="small"
        :icon="ArrowDown"
        :loading="loadingMore"
        data-sftp-load-more
        @click="emit('load-more')"
      >加载更多</el-button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { Folder, Document, PieChart, ArrowDown } from '@element-plus/icons-vue'

defineProps<{
  dirCount: number
  fileCount: number
  totalSize: number
  totalCount: number
  /** 本页之外还有没给的条目（后端 `truncated`） */
  hasMore?: boolean
  /** 目录真实条目数（后端 `total`） */
  remoteTotal?: number
  /** 已加载条数（跨页累加，含文件夹） */
  loadedCount?: number
  loadingMore?: boolean
}>()

const emit = defineEmits<{ 'load-more': [] }>()

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
