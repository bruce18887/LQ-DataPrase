<template>
  <el-dialog
    :model-value="visible"
    title="组合为批次"
    width="440px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:visible', $event)"
    @closed="reset"
  >
    <el-alert
      :title="`将选中的 ${selectedCount} 个文件归属到批次（文件将移动到批次目录）`"
      type="info"
      :closable="false"
      style="margin-bottom: 14px"
    />
    <el-radio-group v-model="mode" class="combine-mode">
      <el-radio value="new">新建批次</el-radio>
      <el-radio value="existing" :disabled="batchOptions.length === 0">追加到已有批次</el-radio>
    </el-radio-group>

    <el-input
      v-if="mode === 'new'"
      v-model="newName"
      placeholder="请输入新批次名称"
      size="large"
      :data-testid="'combine-new-name'"
      style="margin-top: 12px"
    />
    <el-select
      v-else
      v-model="existingName"
      filterable
      placeholder="选择目标批次"
      size="large"
      :data-testid="'combine-existing-select'"
      style="margin-top: 12px; width: 100%"
    >
      <el-option v-for="b in batchOptions" :key="b" :label="b" :value="b" />
    </el-select>
    <div v-if="mode === 'new' && selectedCount < 2" class="combine-hint">
      ⚠️ 新建批次需勾选至少 2 个文件；追加到已有批次可移入 1 个文件
    </div>

    <template #footer>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button
        type="primary"
        :disabled="!valid"
        :data-testid="'combine-submit'"
        @click="submit"
      >
        {{ mode === 'new' ? '组合为新批次' : '追加到批次' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  visible: boolean
  selectedCount: number
  /** 已注册批次名（追加模式候选） */
  batchOptions: string[]
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  submit: [batchName: string]
}>()

const mode = ref<'new' | 'existing'>('new')
const newName = ref('')
const existingName = ref('')

const valid = computed(() => {
  // 新建批次至少 2 个文件（首轮需求）；追加到已有批次 1 个即可
  if (mode.value === 'new') {
    return newName.value.trim().length > 0 && props.selectedCount >= 2
  }
  return !!existingName.value
})

function reset() {
  mode.value = 'new'
  newName.value = ''
  existingName.value = ''
}

function submit() {
  if (!valid.value) return
  emit('submit', mode.value === 'new' ? newName.value.trim() : existingName.value)
}
</script>

<style scoped>
.combine-mode {
  margin-bottom: 4px;
}

.combine-hint {
  margin-top: 10px;
  font-size: 12px;
  color: var(--color-warning);
}
</style>
