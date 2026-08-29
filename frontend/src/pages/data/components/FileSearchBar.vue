<template>
  <div class="file-search-bar">
    <el-input
      v-model="keyword"
      placeholder="按文件名 / 测试程序 / 标签 过滤"
      clearable
      size="default"
      class="search-input"
      @input="emitChange"
    >
      <template #prefix>
        <el-icon><Search /></el-icon>
      </template>
    </el-input>
    <el-select
      v-model="selectedTag"
      placeholder="按标签筛选"
      clearable
      filterable
      allow-create
      default-first-option
      size="default"
      class="tag-select"
      @change="emitChange"
    >
      <el-option
        v-for="t in availableTags"
        :key="t"
        :label="t"
        :value="t"
      />
    </el-select>
    <el-button v-if="keyword || selectedTag" size="default" plain @click="reset">
      <el-icon><RefreshLeft /></el-icon>
      <span>重置</span>
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { Search, RefreshLeft } from '@element-plus/icons-vue'

const props = defineProps<{
  availableTags: string[]
}>()

const emit = defineEmits<{
  change: [payload: { keyword: string; tag: string }]
}>()

const keyword = ref('')
const selectedTag = ref('')

function emitChange() {
  emit('change', { keyword: keyword.value.trim(), tag: selectedTag.value })
}

function reset() {
  keyword.value = ''
  selectedTag.value = ''
  emitChange()
}

watch(() => props.availableTags, (next) => {
  if (selectedTag.value && !next.includes(selectedTag.value)) {
    selectedTag.value = ''
    emitChange()
  }
})
</script>

<style scoped>
.file-search-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.search-input {
  flex: 1 1 320px;
  min-width: 240px;
  max-width: 480px;
}

.tag-select {
  flex: 0 1 220px;
  min-width: 180px;
}

:deep(.el-input__wrapper),
:deep(.el-select__wrapper) {
  background-color: var(--bg-2);
  box-shadow: 0 0 0 1px var(--border-2) inset;
}

:deep(.el-input__wrapper:hover),
:deep(.el-select__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--brand) inset;
}

:deep(.el-input__inner),
:deep(.el-select__placeholder) {
  color: var(--text-2);
}
</style>
