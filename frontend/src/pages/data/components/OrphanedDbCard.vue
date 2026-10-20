<template>
  <MaintenanceCard
    test-id="orphaned-db-card"
    :visible="count > 0"
    title="孤立数据库记录"
    tag-text="磁盘文件已删除"
    tag-type="danger"
    :alert="{ title: '这些记录对应的磁盘文件已不存在，删除后无法恢复。', type: 'warning' }"
  >
    <el-table :data="items" max-height="200" size="small">
      <el-table-column prop="filename" label="文件名" min-width="180" />
      <el-table-column prop="file_type" label="类型" width="90">
        <template #default="{ row }">
          <span>{{ row.file_type === 'single' ? '单文件' : '批次' }}</span>
        </template>
      </el-table-column>
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
    <template #footer-left>
      <el-checkbox v-model="confirmed">
        <span style="color: var(--error); font-weight: 600">
          我已确认要删除这 {{ count }} 条孤立记录
        </span>
      </el-checkbox>
    </template>
    <template #footer-right>
      <el-button
        type="danger"
        :disabled="!confirmed"
        :loading="fixing"
        @click="emit('fix', 'delete_orphaned_db')"
      >
        <el-icon><Delete /></el-icon> 删除孤立记录
      </el-button>
    </template>
  </MaintenanceCard>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import type { OrphanedDbRecord } from '../../../api/datafiles'
import MaintenanceCard from './MaintenanceCard.vue'

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
