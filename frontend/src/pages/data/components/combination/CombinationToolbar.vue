<template>
  <div class="combination-toolbar">
    <div class="combination-picker">
      <span class="combination-field-label">当前组合</span>
      <el-select-v2
        class="combination-select"
        :model-value="activeId"
        :options="options"
        clearable
        filterable
        placeholder="选择组合或查看未分组文件"
        popper-class="dp-combination-select-popper"
        data-testid="combination-select"
        @update:model-value="emit('select', $event)"
      />
    </div>
    <div class="combination-actions">
      <span class="combination-count">{{ combinations.length }} 个组合</span>
      <el-button type="primary" data-testid="combination-create" @click="emit('create')">
        新建组合
      </el-button>
      <el-button :disabled="activeId == null" data-testid="combination-rename" @click="emit('rename')">
        重命名
      </el-button>
      <el-button
        :disabled="activeId == null"
        type="danger"
        plain
        data-testid="combination-delete"
        @click="emit('delete')"
      >删除组合</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DataCombination } from '../../../../types'

const props = defineProps<{
  combinations: DataCombination[]
  activeId: number | null
}>()

const emit = defineEmits<{
  select: [value: number | null]
  create: []
  rename: []
  delete: []
}>()

const options = computed(() => props.combinations.map((combination) => ({
  label: combination.name,
  value: combination.id,
})))
</script>

<style scoped>
.combination-toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--p-space-4);
  padding: var(--p-space-3) var(--p-space-4);
  background: var(--bg-2);
  border: 1px solid var(--border-2);
  border-radius: var(--p-radius-lg);
}

.combination-picker,
.combination-actions {
  display: flex;
  align-items: center;
  gap: var(--p-space-2);
}

.combination-picker {
  align-items: flex-start;
  flex-direction: column;
  min-width: 0;
}

.combination-field-label,
.combination-count {
  color: var(--text-2);
  font-size: var(--p-fs-dense);
}

.combination-field-label {
  font-weight: var(--p-fw-semibold);
}

.combination-picker :deep(.combination-select) {
  width: 280px;
  max-width: 100%;
}

.combination-count {
  margin-right: var(--p-space-1);
  white-space: nowrap;
}

@media (max-width: 980px) {
  .combination-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .combination-actions {
    flex-wrap: wrap;
  }
}

@media (max-width: 560px) {
  .combination-picker :deep(.combination-select) {
    width: 100%;
  }

  .combination-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .combination-count {
    margin-right: 0;
  }
}
</style>
