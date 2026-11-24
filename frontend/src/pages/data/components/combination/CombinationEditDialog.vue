<template>
  <el-dialog
    :model-value="visible"
    :title="mode === 'create' ? '新建组合' : '重命名组合'"
    width="420px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:visible', $event)"
    @opened="focusInput"
  >
    <el-input
      ref="inputRef"
      v-model="name"
      class="combination-name-input"
      data-testid="combination-name-input"
      maxlength="40"
      placeholder="例如 gage、buyoff、实验室调试"
      @keyup.enter="submit"
    />
    <template #footer>
      <div class="combination-dialog-footer">
        <span class="combination-dialog-hint">一个文件最多属于一个组合</span>
        <div class="combination-dialog-actions">
          <el-button @click="emit('update:visible', false)">取消</el-button>
          <el-button
            type="primary"
            :disabled="!name.trim()"
            data-testid="combination-save"
            @click="submit"
          >保存</el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { ElInput } from 'element-plus'

const props = defineProps<{
  visible: boolean
  mode: 'create' | 'rename'
  initialName?: string
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  submit: [name: string]
}>()

const inputRef = ref<InstanceType<typeof ElInput>>()
const name = ref('')

watch(() => [props.visible, props.initialName], () => {
  if (!props.visible) return
  name.value = props.initialName ?? ''
  void focusInput()
})

async function focusInput() {
  await nextTick()
  inputRef.value?.focus()
}

function submit() {
  const value = name.value.trim()
  if (value) emit('submit', value)
}
</script>

<style scoped>
.combination-name-input {
  width: 100%;
}

.combination-dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--p-space-4);
}

.combination-dialog-hint {
  color: var(--text-2);
  font-size: var(--p-fs-dense);
}

.combination-dialog-actions {
  display: flex;
  align-items: center;
  gap: var(--p-space-2);
}

@media (max-width: 560px) {
  .combination-dialog-footer {
    align-items: flex-end;
    flex-direction: column;
  }
}
</style>
