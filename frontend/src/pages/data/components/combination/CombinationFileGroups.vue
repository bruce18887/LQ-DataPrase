<template>
  <div class="combination-files" data-testid="combination-files">
    <section v-if="groups.batched.length" class="combination-file-section">
      <div class="combination-section-heading">
        <h3>有批次文件</h3>
        <span>{{ batchedCount }} 个文件</span>
      </div>
      <article
        v-for="group in groups.batched"
        :key="group.key"
        class="combination-batch-group"
      >
        <header class="combination-group-header">
          <div class="combination-group-title">
            <span class="combination-group-name">{{ combinationName || '未分组文件' }}</span>
            <span class="combination-group-batch">批次号：{{ group.label }}</span>
          </div>
          <span class="combination-group-count">{{ group.files.length }} 个文件</span>
        </header>
        <BatchFilesTable
          :files="group.files"
          :active-file-id="activeFileId"
          @file-selected="emit('file-selected', $event)"
        />
      </article>
    </section>

    <section v-if="groups.unbatched.length" class="combination-file-section">
      <div class="combination-section-heading">
        <h3>{{ combinationName ? '无批次文件' : '未分组文件' }}</h3>
        <span>{{ groups.unbatched.length }} 个文件</span>
      </div>
      <div class="combination-unbatched-group">
        <header class="combination-group-header">
          <div class="combination-group-title">
            <span class="combination-group-name">{{ combinationName || '未分组文件' }}</span>
            <span class="combination-group-batch">批次号：—</span>
          </div>
          <span class="combination-group-count">{{ groups.unbatched.length }} 个文件</span>
        </header>
        <BatchFilesTable
          :files="groups.unbatched"
          :active-file-id="activeFileId"
          @file-selected="emit('file-selected', $event)"
        />
      </div>
    </section>

    <el-empty
      v-if="files.length === 0"
      :description="combinationName ? '当前组合暂无文件，可在上方上传或从文件列表归组' : '暂无未分组文件'"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DataFile } from '../../../../types'
import BatchFilesTable from '../BatchFilesTable.vue'

const props = defineProps<{
  files: DataFile[]
  combinationName: string | null
  activeFileId?: number
}>()

const emit = defineEmits<{
  'file-selected': [id: number]
}>()

const groups = computed(() => {
  const batched = new Map<string, DataFile[]>()
  const unbatched: DataFile[] = []
  for (const file of props.files) {
    const key = (file.batch_no || '').trim().toLowerCase()
    if (!key) {
      unbatched.push(file)
      continue
    }
    const list = batched.get(key) ?? []
    list.push(file)
    batched.set(key, list)
  }
  return {
    batched: [...batched.entries()].map(([key, rows]) => ({
      key,
      label: (rows[0].batch_no || key).trim(),
      files: rows,
    })),
    unbatched,
  }
})

const batchedCount = computed(() =>
  groups.value.batched.reduce((total, group) => total + group.files.length, 0),
)
</script>

<style scoped>
.combination-files {
  min-width: 0;
}

.combination-file-section + .combination-file-section {
  margin-top: var(--p-space-5);
}

.combination-section-heading,
.combination-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--p-space-3);
}

.combination-section-heading {
  margin-bottom: var(--p-space-2);
  color: var(--text-2);
  font-size: var(--p-fs-dense);
}

.combination-section-heading h3 {
  margin: 0;
  color: var(--text);
  font-size: var(--p-fs-small);
  font-weight: var(--p-fw-semibold);
}

.combination-batch-group,
.combination-unbatched-group {
  overflow: hidden;
  border: 1px solid var(--border-2);
  border-radius: var(--p-radius-md);
  background: var(--bg-2);
}

.combination-batch-group + .combination-batch-group {
  margin-top: var(--p-space-3);
}

.combination-group-header {
  min-height: var(--p-space-10);
  padding: var(--p-space-2) var(--p-space-3);
  border-bottom: 1px solid var(--border-2);
}

.combination-group-title {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--p-space-2);
  min-width: 0;
}

.combination-group-name {
  color: var(--text);
  font-size: var(--p-fs-small);
  font-weight: var(--p-fw-semibold);
}

.combination-group-batch,
.combination-group-count {
  color: var(--text-2);
  font-size: var(--p-fs-dense);
}

.combination-group-batch {
  font-family: var(--font-mono);
  overflow-wrap: anywhere;
}

.combination-group-count {
  white-space: nowrap;
}
</style>
