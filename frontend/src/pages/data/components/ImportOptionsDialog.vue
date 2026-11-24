<template>
  <el-dialog
    :model-value="visible"
    title="批量加入组合"
    width="460px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:visible', $event)"
    @closed="reset"
  >
    <el-alert
      :title="`将选中的 ${selectedCount} 个文件归入组合；批次号留空时保留原值。`"
      type="info"
      :closable="false"
      style="margin-bottom: 16px"
    />
    <div class="import-options-form">
      <label class="import-field">
        <span>组合</span>
        <el-select-v2
          v-model="combinationId"
          :options="options"
          filterable
          clearable
          placeholder="选择组合"
          aria-label="选择组合"
          data-testid="import-combination"
        />
      </label>
      <label class="import-field">
        <span>批次号（可选）</span>
        <el-input
          v-model="batchNo"
          maxlength="40"
          placeholder="留空保留原批次号"
          aria-label="批次号（可选）"
          data-testid="import-batch-no"
        />
      </label>
      <el-checkbox
        v-model="clearBatchNo"
        data-testid="import-clear-batch-no"
      >清空批次号</el-checkbox>
    </div>
    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button
        type="primary"
        :disabled="combinationId === null || selectedCount === 0"
        data-testid="import-submit"
        @click="submit"
      >确认归组</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { DataCombination } from '../../../types'
import type { CombinationImportPayload } from '../composables/useCombinationSelection'

const props = defineProps<{
  visible: boolean
  combinations: DataCombination[]
  selectedCount: number
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  submit: [payload: CombinationImportPayload]
}>()

const combinationId = ref<number | null>(null)
const batchNo = ref('')
const clearBatchNo = ref(false)
const options = computed(() => props.combinations.map((combo) => ({
  value: combo.id,
  label: combo.name,
})))

watch(() => props.visible, (visible) => {
  if (visible) reset()
})

function reset() {
  combinationId.value = null
  batchNo.value = ''
  clearBatchNo.value = false
}

function submit() {
  if (combinationId.value === null || props.selectedCount === 0) return
  const value = batchNo.value.trim()
  emit('submit', {
    combinationId: combinationId.value,
    ...(clearBatchNo.value ? { batchNo: '' } : value ? { batchNo: value } : {}),
  })
}
</script>

<style scoped>
.import-options-form {
  display: grid;
  gap: 16px;
}

.import-field {
  display: grid;
  gap: 8px;
  color: var(--text);
  font-size: var(--p-fs-dense);
}

.import-field > span {
  color: var(--text-2);
}
</style>
