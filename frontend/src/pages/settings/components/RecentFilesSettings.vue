<template>
  <div>
    <div class="recent-files__header">
      <span>最多保留</span>
      <el-input-number
        :model-value="maxRecentFiles"
        :min="1"
        :max="50"
        :step="1"
        size="small"
        style="margin-left: 8px; width: 120px"
        @update:model-value="onMaxRecentFilesChange"
      />
      <span>个最近文件</span>
    </div>

    <el-table v-if="recentFiles.length > 0" :data="recentFiles" stripe size="small">
      <el-table-column label="序号" type="index" width="60" />
      <el-table-column prop="id" label="文件 ID" width="100" />
      <el-table-column prop="name" label="文件名" min-width="200" />
      <el-table-column label="访问时间" width="170">
        <template #default="{ row }">
          {{ formatDate(row.accessed_at) }}
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-else description="暂无最近文件" />
  </div>
</template>

<script setup lang="ts">
interface RecentFile {
  id: number
  name: string
  accessed_at: string
}

const props = defineProps<{
  recentFiles: RecentFile[]
  maxRecentFiles: number
}>()
const emit = defineEmits<{
  (e: 'update:maxRecentFiles', value: number): void
}>()

// el-input-number 清空输入时发射 undefined，钳位到最小值 1
function onMaxRecentFilesChange(value: number | undefined) {
  emit('update:maxRecentFiles', value ?? props.maxRecentFiles)
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
</script>

<style scoped>
.recent-files__header {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  font-size: 14px;
  color: var(--text-2);
}
</style>
