<template>
  <el-dialog
    v-model="visible"
    title="数据修复中心"
    width="760px"
    :close-on-click-modal="false"
    @close="emit('update:visible', false)"
  >
    <div v-if="!result" v-loading="checking">
      <el-alert
        title="数据修复中心"
        description="检查数据库记录与磁盘文件的一致性，可导入孤立文件、修复缺失的产品名，或删除确认无用的数据。"
        type="info"
        :closable="false"
        style="margin-bottom: 16px"
      />
      <el-button type="primary" @click="runCheck" :loading="checking">
        开始检查
      </el-button>
    </div>
    <div v-else>
      <el-descriptions :column="4" border style="margin-bottom: 16px">
        <el-descriptions-item label="孤立数据库记录">
          <el-tag :type="result.orphaned_db_count > 0 ? 'danger' : 'success'">
            {{ result.orphaned_db_count }} 条
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="孤立磁盘文件">
          <el-tag :type="result.orphaned_disk_count > 0 ? 'warning' : 'success'">
            {{ result.orphaned_disk_count }} 个
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="产品名缺失">
          <el-tag :type="result.missing_product_code_count > 0 ? 'warning' : 'success'">
            {{ result.missing_product_code_count }} 条
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="重复文件">
          <el-tag :type="result.duplicate_group_count > 0 ? 'danger' : 'success'">
            {{ result.duplicate_group_count }} 组
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>

      <!-- 孤立数据库记录 -->
      <OrphanedDbCard
        :items="result.orphaned_db"
        :count="result.orphaned_db_count"
        :fixing="fixingAction === 'delete_orphaned_db'"
        @fix="handleFix"
      />

      <!-- 孤立磁盘文件 -->
      <OrphanedDiskCard
        :items="result.orphaned_disk"
        :count="result.orphaned_disk_count"
        :fixing-import="fixingAction === 'import_orphaned_disk'"
        :fixing-delete="fixingAction === 'delete_orphaned_disk'"
        @fix="handleFix"
      />

      <!-- 产品名缺失 -->
      <MissingProductCodeCard
        :items="result.missing_product_code"
        :count="result.missing_product_code_count"
        :fixing="fixingAction === 'fix_product_codes'"
        @fix="handleFix"
      />

      <!-- 重复文件（文件名+大小相同；仅管理员可删除） -->
      <DuplicateFilesCard
        :groups="result.duplicate_groups"
        :total-count="result.duplicate_group_count"
        :fixing="fixingAction === 'delete_duplicates'"
        :can-delete="isAdmin"
        @fix="handleFixDeleteDuplicates"
      />

      <!-- 无问题 -->
      <div
        v-if="result.orphaned_db_count === 0 && result.orphaned_disk_count === 0 && result.missing_product_code_count === 0 && result.duplicate_group_count === 0"
        style="text-align: center; padding: 30px"
      >
        <el-icon :size="64" style="color: var(--color-success)"><CircleCheck /></el-icon>
        <p style="color: var(--text-primary); margin-top: 12px; font-size: 16px">
          数据修复中心检查通过，无问题发现。
        </p>
      </div>
    </div>
    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button v-if="result" type="primary" @click="result = null">
        重新检查
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { CircleCheck } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { datafilesApi, type ConsistencyCheckResult, type ConsistencyFixAction, type FixConsistencyResponse } from '../../../api/datafiles'
import { useAuthStore } from '../../../stores/auth'
import OrphanedDbCard from './OrphanedDbCard.vue'
import OrphanedDiskCard from './OrphanedDiskCard.vue'
import MissingProductCodeCard from './MissingProductCodeCard.vue'
import DuplicateFilesCard from './DuplicateFilesCard.vue'

const props = defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  done: []
}>()

const isAdmin = useAuthStore().isAdmin

const visible = computed({
  get: () => props.visible,
  set: (val) => emit('update:visible', val),
})

const checking = ref(false)
const fixingAction = ref<ConsistencyFixAction | null>(null)
const result = ref<ConsistencyCheckResult | null>(null)

async function runCheck() {
  checking.value = true
  try {
    const { data } = await datafilesApi.checkConsistency()
    result.value = data
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  } finally {
    checking.value = false
  }
}

function summarize(action: ConsistencyFixAction, data: FixConsistencyResponse): string {
  switch (action) {
    case 'delete_orphaned_db':
      return `已删除 ${data.deleted_count} 条孤立数据库记录`
    case 'delete_orphaned_disk':
      return `已删除 ${data.deleted_count} 个孤立磁盘文件`
    case 'delete_duplicates':
      return `已删除 ${data.deleted_count} 个重复文件`
    case 'import_orphaned_disk': {
      const skipped = data.skipped_count ? `，${data.skipped_count} 个跳过` : ''
      return `已导入 ${data.imported_count} 个孤立文件${skipped}`
    }
    case 'fix_product_codes': {
      const still = data.still_missing_count ? `，${data.still_missing_count} 条无法修复` : ''
      return `已修复 ${data.fixed_count} 条产品名${still}`
    }
  }
}

async function handleFix(action: ConsistencyFixAction) {
  fixingAction.value = action
  try {
    const { data } = await datafilesApi.fixConsistency(action)
    ElMessage.success(summarize(action, data))
    await runCheck()
    emit('done')
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  } finally {
    fixingAction.value = null
  }
}

async function handleFixDeleteDuplicates() {
  await handleFix('delete_duplicates')
}
</script>
