<template>
  <el-card v-if="count > 0" class="repair-card" data-testid="orphaned-disk-card">
    <template #header>
      <div class="card-header">
        <span class="card-title">孤立磁盘文件</span>
        <el-tag type="warning" size="small">数据库中无记录</el-tag>
      </div>
    </template>
    <el-alert
      title="这些文件在数据库中没有记录。推荐先导入到数据库，确认无用后再删除。"
      type="warning"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />
    <el-alert
      v-if="count > items.length"
      :title="`共 ${count} 个孤立文件，仅显示前 ${items.length} 个，操作将作用于全部。`"
      type="info"
      :closable="false"
      style="margin-bottom: 12px"
    />
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
    <div class="card-footer">
      <el-checkbox v-model="importConfirmed">
        <span style="color: var(--success); font-weight: 600">
          我已确认要导入这 {{ count }} 个文件
        </span>
      </el-checkbox>
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
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { Delete, Download } from '@element-plus/icons-vue'
import type { OrphanedDiskFile } from '../../../api/datafiles'

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

.action-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
