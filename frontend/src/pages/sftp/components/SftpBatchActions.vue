<template>
  <div class="batch-bar">
    <el-checkbox :model-value="allSelected" :indeterminate="isIndeterminate" @change="emit('select-all', $event)">
      全选
    </el-checkbox>
    <el-button size="small" @click="emit('invert')">反选</el-button>
    <template v-if="selectedCount > 0">
      <el-divider direction="vertical" />
      <el-tag type="info" size="small">已选 {{ selectedCount }} 个文件</el-tag>
      <el-button size="small" type="primary" @click="emit('batch-download')" :loading="batchDownloading" :disabled="transferActive">
        <el-icon><Download /></el-icon> 批量下载
      </el-button>
      <el-button size="small" type="success" @click="emit('batch-download-and-parse')" :loading="batchParsing" :disabled="transferActive">
        <el-icon><DataAnalysis /></el-icon> 批量下载解析
      </el-button>
    </template>
  </div>
</template>

<script setup lang="ts">
import { Download, DataAnalysis } from '@element-plus/icons-vue'

defineProps<{
  selectedCount: number
  allSelected: boolean
  isIndeterminate: boolean
  batchDownloading: boolean
  batchParsing: boolean
  /** 传输互斥：任意传输进行中时禁用所有下载入口（后端共享 paramiko 连接非线程安全） */
  transferActive?: boolean
}>()

const emit = defineEmits<{
  'select-all': [value: boolean]
  invert: []
  'batch-download': []
  'batch-download-and-parse': []
}>()
</script>

<style scoped>
.batch-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  margin-bottom: 8px;
  background: var(--bg-2);
  border: 1px solid var(--border-2);
  border-radius: 8px;
}
</style>
