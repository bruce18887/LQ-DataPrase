<template>
  <MaintenanceCard
    test-id="orphaned-disk-card"
    :visible="count > 0"
    title="孤立磁盘文件"
    tag-text="数据库中无记录"
    tag-type="warning"
    :alert="{
      title: '这些文件在数据库中没有记录。推荐先导入到数据库，确认无用后再删除。',
      type: 'warning',
    }"
    :truncated-note="truncatedNote"
  >
    <el-table :data="items" max-height="200" size="small">
      <el-table-column prop="batch_name" label="批次" width="140">
        <template #default="{ row }">
          <span>{{ row.batch_name || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="sub_batch" label="子批次" width="120">
        <template #default="{ row }">
          <span>{{ row.sub_batch || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="filename" label="文件名" min-width="180" />
    </el-table>
    <template #footer-left>
      <el-checkbox v-model="importConfirmed">
        <span style="color: var(--success); font-weight: 600">
          我已确认要导入这 {{ count }} 个文件
        </span>
      </el-checkbox>
    </template>
    <template #footer-right>
      <div class="action-row">
        <el-button
          type="primary"
          :disabled="!importConfirmed"
          :loading="fixingImport"
          @click="emit('fix', 'import_orphaned_disk')"
        >
          <el-icon><Download /></el-icon> 导入到数据库
        </el-button>
        <el-checkbox v-model="deleteConfirmed">
          <span style="color: var(--warn); font-weight: 600">
            确认删除
          </span>
        </el-checkbox>
        <el-button
          type="warning"
          plain
          :disabled="!deleteConfirmed"
          :loading="fixingDelete"
          @click="emit('fix', 'delete_orphaned_disk')"
        >
          <el-icon><Delete /></el-icon> 删除孤立文件
        </el-button>
      </div>
    </template>
  </MaintenanceCard>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Delete, Download } from '@element-plus/icons-vue'
import type { OrphanedDiskFile } from '../../../api/datafiles'
import MaintenanceCard from './MaintenanceCard.vue'

const props = defineProps<{
  items: OrphanedDiskFile[]
  count: number
  fixingImport: boolean
  fixingDelete: boolean
}>()

const emit = defineEmits<{
  fix: [action: 'import_orphaned_disk' | 'delete_orphaned_disk']
}>()

const importConfirmed = ref(false)
const deleteConfirmed = ref(false)
// 检查结果刷新后重置确认状态
watch(() => [props.items, props.count], () => {
  importConfirmed.value = false
  deleteConfirmed.value = false
})

const truncatedNote = computed(() =>
  props.count > props.items.length
    ? `共 ${props.count} 个孤立文件，仅显示前 ${props.items.length} 个，操作将作用于全部。`
    : '',
)
</script>

<style scoped>
.action-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
