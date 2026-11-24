<template>
  <div class="file-tags-cell">
    <el-tag
      v-for="tag in manualTags"
      :key="`manual-${tag}`"
      size="small"
      type="info"
      effect="light"
      class="file-tag"
      data-testid="manual-tag"
      :closable="showClose"
      @close="emit('remove-manual', row, tag)"
    >{{ tag }}</el-tag>
    <el-tag
      v-for="tag in managedTags"
      :key="`managed-${tag}`"
      size="small"
      type="warning"
      effect="plain"
      class="file-tag managed-tag"
      data-testid="managed-tag"
      title="由组合名/批次号自动维护"
    >
      <el-icon class="managed-tag-lock"><Lock /></el-icon>{{ tag }}
    </el-tag>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Lock } from '@element-plus/icons-vue'
import type { DataFile } from '../../../types'

const props = withDefaults(defineProps<{
  row: DataFile
  showManual?: boolean
  showClose?: boolean
}>(), {
  showManual: true,
  showClose: true,
})

const emit = defineEmits<{
  'remove-manual': [row: DataFile, tag: string]
}>()

function uniqueTags(tags: string[] | undefined) {
  const seen = new Set<string>()
  return (tags ?? []).filter((tag) => {
    const value = tag.trim()
    const key = value.toLowerCase()
    if (!value || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

const managedTags = computed(() => uniqueTags(props.row.managed_tags))
const manualTags = computed(() => (
  props.showManual ? uniqueTags(props.row.tags) : []
))
</script>

<style scoped>
.file-tags-cell {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.file-tag {
  margin: 0;
  max-width: 100%;
}

.managed-tag-lock {
  margin-right: 4px;
  vertical-align: -2px;
}
</style>
