<template>
  <div class="batch-group unregistered">
    <div class="batch-header">
      <span class="batch-name">📁 {{ dir.name }}</span>
      <span class="batch-count">{{ dir.file_count }} 个文件</span>
      <span class="batch-size">{{ formatSize(dir.total_size) }}</span>
      <div style="flex:1" />
      <el-button size="small" type="success" @click="emit('import', dir)" :loading="importing">
        <el-icon><Upload /></el-icon> 导入
      </el-button>
      <el-button size="small" type="danger" plain @click="emit('delete', dir)">
        <el-icon><Delete /></el-icon> 删除
      </el-button>
    </div>
    <div v-if="dir.preview_files && dir.preview_files.length > 0" class="preview-list">
      <div v-for="p in dir.preview_files" :key="p.name" class="preview-item">
        <span class="preview-name" :title="p.name">{{ p.name }}</span>
        <span class="mono preview-size">{{ formatSize(p.size) }}</span>
      </div>
      <div v-if="dir.preview_files.length < dir.file_count" class="preview-more">
        共 {{ dir.file_count }} 个文件，仅显示前 {{ dir.preview_files.length }} 个
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Upload, Delete } from '@element-plus/icons-vue'
import type { BatchDirInfo } from '../../../api/datafiles'
import { formatSize } from '../../../utils/format'

defineProps<{
  dir: BatchDirInfo
  importing: boolean
}>()

const emit = defineEmits<{
  import: [dir: BatchDirInfo]
  delete: [dir: BatchDirInfo]
}>()
</script>

<style scoped>
.batch-group {
  margin-bottom: 12px;
  padding: 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-radius: 10px;
}

.batch-group.unregistered {
  border-left: 3px solid var(--color-warning);
}

.batch-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.batch-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.batch-count {
  font-size: 12px;
  color: var(--text-tertiary);
  padding: 2px 8px;
  background: var(--bg-primary);
  border-radius: 10px;
}

.batch-size {
  font-size: 12px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

/* 未导入目录预览 */
.preview-list {
  margin-top: 8px;
  max-height: 220px;
  overflow-y: auto;
  border: 1px dashed var(--border-muted);
  border-radius: 8px;
  padding: 4px 8px;
  background: var(--bg-primary);
}

.preview-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 2px 0;
  font-size: 12px;
}

.preview-name {
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-size {
  color: var(--text-tertiary);
  font-size: 11px;
  flex-shrink: 0;
}

.preview-more {
  padding: 4px 0;
  font-size: 11px;
  color: var(--text-tertiary);
}

.mono {
  font-family: var(--font-mono);
}

/* Night theme overrides */
:root[data-theme="night"] .batch-group {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.08);
}

:root[data-theme="night"] .batch-group.unregistered {
  border-left-color: var(--color-warning);
}
</style>
