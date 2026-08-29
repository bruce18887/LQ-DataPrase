<template>
  <el-card v-if="count > 0" class="repair-card" data-testid="missing-product-code-card">
    <template #header>
      <div class="card-header">
        <span class="card-title">产品名缺失</span>
        <el-tag type="info" size="small">product_code 为空</el-tag>
      </div>
    </template>
    <el-alert
      title="这些文件未能识别产品名。系统会先从文件名或已保存的程序名提取，必要时重新解析文件头。"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    />
    <el-alert
      v-if="count > items.length"
      :title="`共 ${count} 个文件缺失产品名，仅显示前 ${items.length} 个，操作将作用于全部。`"
      type="info"
      :closable="false"
      style="margin-bottom: 12px"
    />
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
    <div class="card-footer">
      <el-checkbox v-model="confirmed">
        <span style="color: var(--brand); font-weight: 600">
          我已确认要修复这 {{ count }} 个文件的产品名
        </span>
      </el-checkbox>
      <el-button
        type="primary"
        :disabled="!confirmed"
        :loading="fixing"
        @click="emit('fix', 'fix_product_codes')"
      >
        <el-icon><MagicStick /></el-icon> 修复缺失产品名
      </el-button>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { MagicStick } from '@element-plus/icons-vue'
import type { MissingProductCodeFile } from '../../../api/datafiles'

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

.empty-text {
  color: var(--text-3);
}
</style>
