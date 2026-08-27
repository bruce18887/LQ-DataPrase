<template>
  <el-card v-if="groups.length > 0" class="repair-card" data-testid="duplicate-files-card">
    <template #header>
      <div class="card-header">
        <span class="card-title">重复文件</span>
        <el-tag type="danger" size="small">文件名与大小完全相同</el-tag>
      </div>
    </template>
    <el-alert
      title="以下文件按「文件名 + 大小」判定重复。删除重复项时保留最早导入的一条（其余文件将从数据库与磁盘移除）。"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />
    <el-alert
      v-if="totalCount > groups.length"
      :title="`共 ${totalCount} 组重复，仅显示前 ${groups.length} 组，删除操作将作用于全部。`"
      type="info"
      :closable="false"
      style="margin-bottom: 12px"
    />
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
    <div class="card-footer">
      <el-checkbox v-model="deleteConfirmed" :disabled="!canDelete">
        <span :style="{ color: canDelete ? 'var(--color-danger)' : 'var(--text-tertiary)', fontWeight: 600 }">
          {{ canDelete ? '我已确认要删除全部重复项' : '仅管理员可删除重复文件' }}
        </span>
      </el-checkbox>
      <el-button
        type="danger"
        plain
        :disabled="!deleteConfirmed || !canDelete"
        :loading="fixing"
        @click="emit('fix')"
      >
        <el-icon><Delete /></el-icon> 删除重复文件
      </el-button>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import type { DuplicateGroup, DuplicateGroupFile } from '../../../api/datafiles'
import { formatSize } from '../../../utils/format'

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

function dupFileTitle(f: DuplicateGroupFile) {
  const loc = f.file_type === 'batch' ? `批次：${f.batch_name || '—'} / 子批次：${f.sub_batch || '—'}` : '单文件'
  return `ID ${f.id}｜${loc}｜大小 ${f.file_size} B`
}
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  font-weight: 600;
  color: var(--text-primary);
}

.dup-group {
  padding: 10px 12px;
  margin-bottom: 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
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
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 55%;
}

.dup-group-size {
  font-size: 11px;
  color: var(--color-info);
}

.dup-group-count {
  font-size: 11px;
  color: var(--text-tertiary);
  padding: 1px 6px;
  background: var(--bg-primary);
  border-radius: 8px;
}

.dup-file-tag {
  margin: 0;
}

.card-footer {
  margin-top: 12px;
  padding: 12px;
  background: var(--bg-secondary);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.mono {
  font-family: var(--font-mono);
}
</style>
