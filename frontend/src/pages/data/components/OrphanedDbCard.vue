<template>
  <el-card v-if="count > 0" class="repair-card" data-testid="orphaned-db-card">
    <template #header>
      <div class="card-header">
        <span class="card-title">孤立数据库记录</span>
        <el-tag type="danger" size="small">磁盘文件已删除</el-tag>
      </div>
    </template>
    <el-alert
      title="这些记录对应的磁盘文件已不存在，删除后无法恢复。"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />
    <el-table :data="items" max-height="200" size="small">
      <el-table-column prop="filename" label="文件名" min-width="180" />
      <el-table-column prop="batch_name" label="批次" width="120">
        <template #default="{ row }">
          <span>{{ row.batch_name || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="sub_batch" label="子批次" width="120">
        <template #default="{ row }">
          <span>{{ row.sub_batch || '—' }}</span>
        </template>
      </el-table-column>
    </el-table>
    <div class="card-footer">
      <el-checkbox v-model="confirmed">
        <span style="color: var(--error); font-weight: 600">
          我已确认要删除这 {{ count }} 条孤立记录
        </span>
      </el-checkbox>
      <el-button
        type="danger"
        :disabled="!confirmed"
        :loading="fixing"
        @click="emit('fix', 'delete_orphaned_db')"
      >
        <el-icon><Delete /></el-icon> 删除孤立记录
      </el-button>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import type { OrphanedDbRecord } from '../../../api/datafiles'

const props = defineProps<{
  items: OrphanedDbRecord[]
  count: number
  fixing: boolean
}>()

const emit = defineEmits<{
  fix: [action: 'delete_orphaned_db']
}>()

const confirmed = ref(false)
// 检查结果刷新后重置确认状态
watch(() => [props.items, props.count], () => {
  confirmed.value = false
})
</script>

<style scoped>
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.card-title {
  font-weight: 600;
  color: var(--text);
}

.card-footer {
  margin-top: 12px;
  padding: 12px;
  background: var(--bg-2);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
