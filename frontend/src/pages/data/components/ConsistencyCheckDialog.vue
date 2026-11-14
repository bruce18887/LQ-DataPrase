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

      <!-- 清单/磁盘差值（规格 §4.6 + 计划订正③）：只陈述事实、不给动作按钮——
           产品里没有任何路径会回写 file_size，「重新扫描」修不好这一行。
           data-testid 是给 e2e 的结构钩子：按文案筛的定位器抓不到「title 为空但这一行照样
           渲染出来」的回归（2026-11-14 变异实测），而这一行的契约本来就是「出现 / 不出现」。 -->
      <el-alert
        v-if="mismatchLine"
        data-testid="disk-mismatch-alert"
        :title="mismatchLine"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />

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
        <el-icon :size="64" style="color: var(--success)"><CircleCheck /></el-icon>
        <p style="color: var(--text); margin-top: 12px; font-size: var(--p-fs-lead)">
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
import { datafilesApi, type ConsistencyCheckResult, type ConsistencyFixAction, type FileUsage, type FixConsistencyResponse } from '../../../api/datafiles'
import { usageMismatchLine } from '../../../utils/diskUsage'
import { remainingGroupsNote } from '../../../utils/dupKeep'
import { useAuthStore } from '../../../stores/auth'
import OrphanedDbCard from './OrphanedDbCard.vue'
import OrphanedDiskCard from './OrphanedDiskCard.vue'
import MissingProductCodeCard from './MissingProductCodeCard.vue'
import DuplicateFilesCard from './DuplicateFilesCard.vue'

const props = defineProps<{
  visible: boolean
  usage: FileUsage | null
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

// 差值行读的是**已经拉过的那次占用**，不在这个对话框里再扫一遍盘（规格 §4.6：
// 它只是一个「清单与磁盘对不上」的提示，不是一个第二指标）。
const mismatchLine = computed(() => usageMismatchLine(props.usage))

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
      return `已删除 ${data.deleted_count} 个重复文件${remainingGroupsNote(data.remaining_groups)}`
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

async function handleFix(action: ConsistencyFixAction, keepIds?: number[]) {
  fixingAction.value = action
  try {
    const { data } = await datafilesApi.fixConsistency(action, keepIds)
    ElMessage.success(summarize(action, data))
    await runCheck()
    emit('done')
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出（400 invalid_keep_id 走的就是这条通路：
    // 后端 detail 是中文 ⇒ pickMessage 先读 message，前端不需要 ERROR_CODE_MAP 条目）
  } finally {
    fixingAction.value = null
  }
}

async function handleFixDeleteDuplicates(keepIds: number[]) {
  await handleFix('delete_duplicates', keepIds)
}
</script>
