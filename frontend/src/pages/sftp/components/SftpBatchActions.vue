<template>
  <div class="batch-bar">
    <el-checkbox :model-value="allSelected" :indeterminate="isIndeterminate" @change="emit('select-all', $event)">
      全选
    </el-checkbox>
    <el-button size="small" @click="emit('invert')">反选</el-button>
    <template v-if="selectedCount > 0">
      <el-divider direction="vertical" />
      <el-tag type="info" size="small">已选 {{ selectedCount }} 个文件</el-tag>
      <!-- 与单行下载同一判据（`transferActive` 已把「搜索进行中」并进去），
           这里只补「为什么禁着」：搜索与下载互斥这件事不说清楚，用户只会反复点。 -->
      <el-tooltip :content="transferReason" :disabled="!transferActive" placement="top">
        <span class="tip-anchor">
          <el-button size="small" type="primary" @click="emit('batch-download')" :loading="batchDownloading" :disabled="transferActive">
            <el-icon><Download /></el-icon> 批量下载
          </el-button>
        </span>
      </el-tooltip>
      <el-tooltip :content="transferReason" :disabled="!transferActive" placement="top">
        <span class="tip-anchor">
          <el-button size="small" type="success" @click="emit('batch-download-and-parse')" :loading="batchParsing" :disabled="transferActive">
            <el-icon><DataAnalysis /></el-icon> 批量下载解析
          </el-button>
        </span>
      </el-tooltip>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Download, DataAnalysis } from '@element-plus/icons-vue'

const props = defineProps<{
  selectedCount: number
  allSelected: boolean
  isIndeterminate: boolean
  batchDownloading: boolean
  batchParsing: boolean
  /** 传输互斥：任意传输进行中时禁用所有下载入口（后端共享 paramiko 连接非线程安全） */
  transferActive?: boolean
  /** 只为把禁用原因说准（搜索进行中 ≠ 又一次下载）；判据本身仍是 `transferActive` */
  searchActive?: boolean
}>()

const emit = defineEmits<{
  'select-all': [value: boolean]
  invert: []
  'batch-download': []
  'batch-download-and-parse': []
}>()

const transferReason = computed(() => (props.searchActive
  ? '搜索进行中：下载与搜索互斥，同时只允许一路传输（去右上角或搜索页取消搜索）'
  : '已有传输在进行：同一时刻只允许一路下载'))
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
.tip-anchor { display: inline-flex; }
</style>
