<template>
  <MaintenanceCard
    test-id="duplicate-files-card"
    :visible="groups.length > 0"
    title="重复文件"
    tag-text="文件名与大小完全相同"
    tag-type="danger"
    :alert="{
      title: '以下文件按「文件名 + 大小」判定重复。删除重复项时保留最早导入的一条（其余文件将从数据库与磁盘移除）。',
      type: 'warning',
    }"
    :truncated-note="truncatedNote"
  >
    <div v-for="group in groups" :key="group.filename + '-' + group.file_size" class="dup-group">
      <div class="dup-group-header">
        <span class="dup-group-key mono">{{ group.filename }}</span>
        <span class="dup-group-size mono">{{ formatSize(group.file_size) }}</span>
        <span class="dup-group-count">{{ group.files.length }} 个</span>
      </div>
      <el-tag
        v-for="(f, i) in group.files"
        :key="f.id"
        :type="i === 0 ? 'success' : 'danger'"
        :effect="i === 0 ? 'dark' : 'plain'"
        size="small"
        class="dup-file-tag"
        :title="dupFileTitle(f)"
      >
        {{ i === 0 ? '✓ 保留' : '删除' }} {{ f.file_type === 'batch' ? `[${f.batch_name}]` : '[单文件]' }} · #{{ f.id }}
      </el-tag>
    </div>
    <template #footer-left>
      <el-checkbox v-model="deleteConfirmed" :disabled="!canDelete">
        <span :style="{ color: canDelete ? 'var(--error)' : 'var(--text-3)', fontWeight: 600 }">
          {{ canDelete ? '我已确认要删除全部重复项' : '仅管理员可删除重复文件' }}
        </span>
      </el-checkbox>
    </template>
    <template #footer-right>
      <el-button
        type="danger"
        plain
        :disabled="!deleteConfirmed || !canDelete"
        :loading="fixing"
        @click="emit('fix')"
      >
        <el-icon><Delete /></el-icon> 删除重复文件
      </el-button>
    </template>
  </MaintenanceCard>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import type { DuplicateGroup, DuplicateGroupFile } from '../../../api/datafiles'
import { formatSize } from '../../../utils/format'
import MaintenanceCard from './MaintenanceCard.vue'

const props = defineProps<{
  groups: DuplicateGroup[]
  /** 总组数（groups 可能只显示前 N 组） */
  totalCount: number
  fixing: boolean
  /** 当前用户是否有删除权限（管理员） */
  canDelete: boolean
}>()

const emit = defineEmits<{
  fix: []
}>()

const deleteConfirmed = ref(false)
// 检查结果刷新后重置确认状态
watch(() => [props.groups, props.totalCount], () => {
  deleteConfirmed.value = false
})

const truncatedNote = computed(() =>
  props.totalCount > props.groups.length
    ? `共 ${props.totalCount} 组重复，仅显示前 ${props.groups.length} 组，删除操作将作用于全部。`
    : '',
)

function dupFileTitle(f: DuplicateGroupFile) {
  const loc = f.file_type === 'batch' ? `批次：${f.batch_name || '—'} / 子批次：${f.sub_batch || '—'}` : '单文件'
  return `ID ${f.id}｜${loc}｜大小 ${f.file_size} B`
}
</script>

<style scoped>
.dup-group {
  padding: 10px 12px;
  margin-bottom: 8px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.dup-group-header {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.dup-group-key {
  font-size: var(--p-fs-dense);
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 55%;
}

.dup-group-size {
  font-size: var(--p-fs-micro);
  color: var(--info);
}

.dup-group-count {
  font-size: var(--p-fs-micro);
  color: var(--text-3);
  padding: 1px 6px;
  background: var(--bg);
  border-radius: 8px;
}

.dup-file-tag {
  margin: 0;
}

.mono {
  font-family: var(--font-mono);
}
</style>
