<template>
  <div class="list-toolbar">
    <div class="toolbar-left">
      <span class="section-title">📋 文件列表</span>
      <span class="section-count">{{ total }} 个文件</span>
      <!-- 磁盘占用：复用 .section-count 的外观（同一族 chip，不新增字号声明，
           过 e2e/global/fonts.spec.ts 那条禁硬编码 px 的闸），浮层用 el-descriptions
           而不是自定义样式 —— popper 被 teleport 到 body，scoped CSS 够不着它。 -->
      <el-popover
        v-if="usage"
        placement="bottom-start"
        :width="300"
        trigger="hover"
        popper-class="disk-usage-popover"
      >
        <template #reference>
          <span class="section-count" data-testid="disk-usage-chip">
            {{ usageChipText(usage) }}
          </span>
        </template>
        <el-descriptions :column="1" size="small" border>
          <el-descriptions-item v-for="row in usageRows" :key="row.label" :label="row.label">
            {{ row.sizeText }} · {{ row.countText }}
          </el-descriptions-item>
          <el-descriptions-item v-if="!usageRows.length" label="数据目录">
            没有文件
          </el-descriptions-item>
          <el-descriptions-item v-if="usageOutside" label="目录外记录">
            {{ usageOutside }}
          </el-descriptions-item>
          <el-descriptions-item v-if="usageScanned" label="统计时间">
            {{ usageScanned }}
          </el-descriptions-item>
        </el-descriptions>
      </el-popover>
    </div>
    <div class="toolbar-right">
      <el-input
        v-model="searchText"
        placeholder="按文件名/程序名/标签搜索"
        clearable
        class="search-input"
        @input="onSearchInput"
        @clear="onSearchInput"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <el-button
        type="primary"
        plain
        :disabled="selectedCount < 1"
        :title="selectedCount < 1 ? '请先勾选文件' : '组合/追加为批次'"
        @click="emit('combine-click')"
      >
        <el-icon><Collection /></el-icon>
        组合为批次
      </el-button>
      <el-button
        type="primary"
        @click="emit('upload-click')"
      >
        <el-icon><Upload /></el-icon>
        上传文件
      </el-button>
      <el-button
        type="danger"
        plain
        :disabled="selectedCount === 0"
        @click="emit('bulk-delete')"
      >
        <el-icon><Delete /></el-icon>
        批量删除{{ selectedCount ? ` (${selectedCount})` : '' }}
      </el-button>
      <el-button
        type="warning"
        plain
        @click="emit('fix-click')"
      >
        <el-icon><Tools /></el-icon>
        数据修复
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Search, Delete, Upload, Tools, Collection } from '@element-plus/icons-vue'
import type { FileUsage } from '../../../api/datafiles'
import {
  usageBreakdownRows,
  usageChipText,
  usageOutsideLine,
  usageScannedText,
} from '../../../utils/diskUsage'

const props = defineProps<{
  total: number
  selectedCount: number
  usage: FileUsage | null
}>()

const emit = defineEmits<{
  search: [text: string]
  'upload-click': []
  'fix-click': []
  'bulk-delete': []
  'combine-click': []
}>()

const usageRows = computed(() => usageBreakdownRows(props.usage))
const usageOutside = computed(() => usageOutsideLine(props.usage))
const usageScanned = computed(() => usageScannedText(props.usage))

const searchText = ref('')

let searchTimer: ReturnType<typeof setTimeout> | undefined

function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    emit('search', searchText.value)
  }, 300)
}
</script>

<style scoped>
.list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.section-title {
  font-size: var(--p-fs-base);
  font-weight: 600;
  color: var(--text);
}

.section-count {
  font-size: var(--p-fs-dense);
  color: var(--text-3);
  padding: 2px 8px;
  background: var(--bg-2);
  border-radius: 10px;
}

.search-input {
  width: 220px;
}

:root[data-theme="night"] .section-count {
  background: rgba(255, 255, 255, 0.08);
}
</style>
