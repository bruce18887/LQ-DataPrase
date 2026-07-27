<template>
  <el-dialog
    v-model="visible"
    title="数据一致性检查"
    width="700px"
    :close-on-click-modal="false"
    @close="emit('update:visible', false)"
  >
    <div v-if="!consistencyResult" v-loading="checking">
      <el-alert
        title="数据一致性检查"
        description="检查数据库记录与磁盘文件的一致性，修复可能的数据不一致问题。"
        type="info"
        :closable="false"
        style="margin-bottom: 16px"
      />
      <el-button type="primary" @click="runCheck" :loading="checking">
        开始检查
      </el-button>
    </div>
    <div v-else>
      <el-descriptions :column="2" border style="margin-bottom: 16px">
        <el-descriptions-item label="孤立数据库记录">
          <el-tag :type="consistencyResult.orphaned_db_count > 0 ? 'danger' : 'success'">
            {{ consistencyResult.orphaned_db_count }} 条
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="孤立磁盘文件">
          <el-tag :type="consistencyResult.orphaned_disk_count > 0 ? 'warning' : 'success'">
            {{ consistencyResult.orphaned_disk_count }} 个
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>

      <!-- 孤立数据库记录 -->
      <el-card v-if="consistencyResult.orphaned_db_count > 0" style="margin-bottom: 16px">
        <template #header>
          <div style="display: flex; align-items: center; justify-content: space-between">
            <span style="font-weight: 600">孤立数据库记录</span>
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
        <el-table :data="consistencyResult.orphaned_db" max-height="200" size="small">
          <el-table-column prop="filename" label="文件名" min-width="200" />
          <el-table-column prop="batch_name" label="批次" width="150" />
        </el-table>
        <div style="margin-top: 12px; padding: 12px; background: var(--bg-secondary); border-radius: 8px">
          <el-checkbox v-model="confirmDeleteDb" style="margin-bottom: 8px">
            <span style="color: var(--color-danger); font-weight: 600">
              我已确认要删除这 {{ consistencyResult.orphaned_db_count }} 条孤立记录
            </span>
          </el-checkbox>
          <el-button
            type="danger"
            size="small"
            :disabled="!confirmDeleteDb"
            @click="fixConsistency('delete_orphaned_db')"
            :loading="fixing"
          >
            <el-icon><Delete /></el-icon> 删除孤立记录
          </el-button>
        </div>
      </el-card>

      <!-- 孤立磁盘文件 -->
      <el-card v-if="consistencyResult.orphaned_disk_count > 0" style="margin-bottom: 16px">
        <template #header>
          <div style="display: flex; align-items: center; justify-content: space-between">
            <span style="font-weight: 600">孤立磁盘文件</span>
            <el-tag type="warning" size="small">数据库中无记录</el-tag>
          </div>
        </template>
        <el-alert
          title="这些文件在数据库中没有记录，删除后无法通过网页恢复。"
          type="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 12px"
        />
        <el-table :data="consistencyResult.orphaned_disk.map((p) => ({ path: p }))" max-height="200" size="small">
          <el-table-column prop="path" label="文件路径" />
        </el-table>
        <div style="margin-top: 12px; padding: 12px; background: var(--bg-secondary); border-radius: 8px">
          <el-checkbox v-model="confirmDeleteDisk" style="margin-bottom: 8px">
            <span style="color: var(--color-warning); font-weight: 600">
              我已确认要删除这 {{ consistencyResult.orphaned_disk_count }} 个孤立文件
            </span>
          </el-checkbox>
          <el-button
            type="warning"
            size="small"
            :disabled="!confirmDeleteDisk"
            @click="fixConsistency('delete_orphaned_disk')"
            :loading="fixing"
          >
            <el-icon><Delete /></el-icon> 删除孤立文件
          </el-button>
        </div>
      </el-card>

      <!-- 无问题 -->
      <div
        v-if="consistencyResult.orphaned_db_count === 0 && consistencyResult.orphaned_disk_count === 0"
        style="text-align: center; padding: 30px"
      >
        <el-icon :size="64" style="color: var(--color-success)"><CircleCheck /></el-icon>
        <p style="color: var(--text-primary); margin-top: 12px; font-size: 16px">
          数据一致性检查通过，无问题发现。
        </p>
      </div>
    </div>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button v-if="consistencyResult" type="primary" @click="consistencyResult = null">
        重新检查
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Delete, CircleCheck } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { datafilesApi } from '../../../api/datafiles'

const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  done: []
}>()

const visible = computed({
  get: () => props.visible,
  set: (val) => emit('update:visible', val),
})

const checking = ref(false)
const fixing = ref(false)
const confirmDeleteDb = ref(false)
const confirmDeleteDisk = ref(false)
const consistencyResult = ref<{
  orphaned_db_count: number
  orphaned_disk_count: number
  orphaned_db: Array<{ id: number; filename: string; batch_name: string; file_path: string }>
  orphaned_disk: string[]
} | null>(null)

async function runCheck() {
  checking.value = true
  confirmDeleteDb.value = false
  confirmDeleteDisk.value = false
  try {
    const { data } = await datafilesApi.checkConsistency()
    consistencyResult.value = data
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '检查失败')
  } finally {
    checking.value = false
  }
}

async function fixConsistency(action: 'delete_orphaned_db' | 'delete_orphaned_disk') {
  const actionLabel = action === 'delete_orphaned_db' ? '孤立数据库记录' : '孤立磁盘文件'
  try {
    fixing.value = true
    const { data } = await datafilesApi.fixConsistency(action)
    ElMessage.success(`已删除 ${data.deleted_count} 个${actionLabel}`)
    confirmDeleteDb.value = false
    confirmDeleteDisk.value = false
    await runCheck()
    emit('done')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '修复失败')
  } finally {
    fixing.value = false
  }
}
</script>
