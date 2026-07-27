<template>
  <div class="list-toolbar">
    <div class="toolbar-left">
      <span class="section-title">📋 文件列表</span>
      <span class="section-count">{{ total }} 个文件</span>
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
      <el-select
        v-model="productCode"
        placeholder="全部产品"
        clearable
        class="product-filter"
        @change="emit('filter-change', $event)"
      >
        <el-option
          v-for="code in productCodes"
          :key="code"
          :label="code"
          :value="code"
        />
      </el-select>
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
import { ref } from 'vue'
import { Search, Delete, Upload, Tools } from '@element-plus/icons-vue'

defineProps<{
  total: number
  productCodes: string[]
  selectedCount: number
}>()

const emit = defineEmits<{
  search: [text: string]
  'filter-change': [code: string]
  'upload-click': []
  'fix-click': []
  'bulk-delete': []
}>()

const searchText = ref('')
const productCode = ref('')

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
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.section-count {
  font-size: 12px;
  color: var(--text-tertiary);
  padding: 2px 8px;
  background: var(--bg-secondary);
  border-radius: 10px;
}

.search-input {
  width: 220px;
}

.product-filter {
  width: 160px;
}

:root[data-theme="night"] .section-count {
  background: rgba(255, 255, 255, 0.08);
}
</style>
