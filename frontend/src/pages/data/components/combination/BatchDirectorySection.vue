<template>
  <el-collapse class="batch-directory-section" data-testid="batch-directory-section">
    <el-collapse-item name="source-directories" title="来源批次目录（ZIP / SFTP）">
      <BatchDataTab
        :active-file-id="activeFileId"
        :combinations="combinations"
        @file-selected="emit('file-selected', $event)"
        @import-success="emit('import-success')"
        @combination-created="emit('combination-created', $event)"
      />
    </el-collapse-item>
  </el-collapse>
</template>

<script setup lang="ts">
import type { DataCombination } from '../../../../types'
import BatchDataTab from '../BatchDataTab.vue'

defineProps<{
  activeFileId?: number
  combinations: DataCombination[]
}>()

const emit = defineEmits<{
  'file-selected': [id: number]
  'import-success': []
  'combination-created': [combination: DataCombination]
}>()
</script>

<style scoped>
.batch-directory-section {
  margin-top: var(--p-space-5);
  border: 1px solid var(--border-2);
  border-radius: var(--p-radius-md);
  background: var(--bg-2);
}

.batch-directory-section :deep(.el-collapse-item__header) {
  min-height: var(--p-space-10);
  padding: 0 var(--p-space-3);
  color: var(--text);
  font-size: var(--p-fs-small);
  font-weight: var(--p-fw-semibold);
  border-bottom-color: var(--border-2);
}

.batch-directory-section :deep(.el-collapse-item__content) {
  padding: var(--p-space-3);
}

.batch-directory-section :deep(.el-collapse-item__wrap) {
  border-bottom-color: var(--border-2);
}
</style>
