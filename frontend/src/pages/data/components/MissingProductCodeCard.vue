<template>
  <MaintenanceCard
    test-id="missing-product-code-card"
    :visible="count > 0"
    title="产品名缺失"
    tag-text="product_code 为空"
    tag-type="info"
    :alert="{
      title: '这些文件未能识别产品名。系统会先从文件名或已保存的程序名提取，必要时重新解析文件头。',
      type: 'info',
    }"
    :truncated-note="truncatedNote"
  >
    <el-table :data="items" max-height="200" size="small">
      <el-table-column prop="filename" label="文件名" min-width="180" />
      <el-table-column prop="batch_name" label="批次" width="120">
        <template #default="{ row }">
          <span>{{ row.batch_name || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="预计产品名" width="160">
        <template #default="{ row }">
          <el-tag v-if="row.preview_code" type="success" size="small" effect="plain">
            {{ row.preview_code }}
          </el-tag>
          <span v-else class="empty-text">—</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag v-if="row.preview_code" type="success" size="small">可直接修复</el-tag>
          <el-tag v-else-if="row.reparse_needed" type="warning" size="small">需重读文件</el-tag>
          <el-tag v-else type="danger" size="small">文件缺失</el-tag>
        </template>
      </el-table-column>
    </el-table>
    <template #footer-left>
      <el-checkbox v-model="confirmed">
        <span style="color: var(--brand); font-weight: 600">
          我已确认要修复这 {{ count }} 个文件的产品名
        </span>
      </el-checkbox>
    </template>
    <template #footer-right>
      <el-button
        type="primary"
        :disabled="!confirmed"
        :loading="fixing"
        @click="emit('fix', 'fix_product_codes')"
      >
        <el-icon><MagicStick /></el-icon> 修复缺失产品名
      </el-button>
    </template>
  </MaintenanceCard>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { MagicStick } from '@element-plus/icons-vue'
import type { MissingProductCodeFile } from '../../../api/datafiles'
import MaintenanceCard from './MaintenanceCard.vue'

const props = defineProps<{
  items: MissingProductCodeFile[]
  count: number
  fixing: boolean
}>()

const emit = defineEmits<{
  fix: [action: 'fix_product_codes']
}>()

const confirmed = ref(false)
// 检查结果刷新后重置确认状态
watch(() => [props.items, props.count], () => {
  confirmed.value = false
})

const truncatedNote = computed(() =>
  props.count > props.items.length
    ? `共 ${props.count} 个文件缺失产品名，仅显示前 ${props.items.length} 个，操作将作用于全部。`
    : '',
)
</script>

<style scoped>
.empty-text {
  color: var(--text-3);
}
</style>
