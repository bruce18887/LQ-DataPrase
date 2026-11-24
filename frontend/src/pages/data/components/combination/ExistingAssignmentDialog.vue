<template>
  <el-dialog
    :model-value="visible"
    title="选择存量文件归组"
    width="900px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:visible', $event)"
    @closed="reset"
  >
    <div class="existing-filters">
      <el-input
        v-model="search"
        data-testid="existing-search"
        clearable
        placeholder="按文件名搜索"
      />
      <el-select-v2
        v-model="sourceBatch"
        data-testid="existing-source-batch"
        clearable
        filterable
        placeholder="按来源批次筛选"
        :options="sourceOptions"
      />
      <el-button :disabled="!sourceBatch" data-testid="existing-select-batch" @click="selectSourceBatch">
        选择当前来源批次全部
      </el-button>
      <span class="selected-count" data-testid="existing-selected-count">已精确选择 {{ selectedIds.size }} 个文件</span>
    </div>

    <el-table
      ref="tableRef"
      :data="filteredFiles"
      row-key="id"
      max-height="360"
      @selection-change="onSelectionChange"
    >
      <el-table-column type="selection" width="44" reserve-selection />
      <el-table-column label="文件名" min-width="210">
        <template #default="{ row }">
          <span class="file-name" :title="row.filename">{{ row.filename }}</span>
        </template>
      </el-table-column>
      <el-table-column label="来源批次" min-width="130">
        <template #default="{ row }">{{ row.batch_name || '—' }}</template>
      </el-table-column>
      <el-table-column label="当前手动标签" min-width="130">
        <template #default="{ row }">
          <FileTagsCell v-if="row.tags?.length" :row="row" :show-close="false" />
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="当前批次号" min-width="120">
        <template #default="{ row }">{{ row.batch_no || '—' }}</template>
      </el-table-column>
      <el-table-column label="归组后系统标签预览" min-width="190">
        <template #default="{ row }">
          <div v-if="targetCombination" class="managed-preview" data-testid="existing-preview">
            <el-tag
              v-for="tag in previewTags(row)"
              :key="tag"
              size="small"
              type="warning"
              effect="plain"
            >{{ tag }}</el-tag>
          </div>
          <span v-else>选择目标组合后预览</span>
        </template>
      </el-table-column>
    </el-table>

    <div class="existing-target">
      <label>
        <span>目标组合</span>
        <el-select-v2
          v-model="combinationId"
          data-testid="import-combination"
          filterable
          placeholder="选择组合"
          :options="combinationOptions"
        />
      </label>
      <label>
        <span>批次号覆盖（可选）</span>
        <el-input
          v-model="batchNo"
          data-testid="import-batch-no"
          maxlength="40"
          placeholder="留空保留原值"
        />
      </label>
    </div>
    <template #footer>
      <span class="footer-note">只提交勾选的 {{ selectedIds.size }} 个文件，未勾选文件保持不变。</span>
      <el-button @click="emit('update:visible', false)">取消</el-button>
      <el-button
        type="primary"
        :disabled="combinationId === null || selectedIds.size === 0"
        data-testid="import-submit"
        @click="submit"
      >确认归组（{{ selectedIds.size }}）</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { DataCombination, DataFile } from '../../../../types'
import FileTagsCell from '../FileTagsCell.vue'

interface TableSelectionHandle {
  toggleRowSelection: (row: DataFile, selected: boolean) => void
  clearSelection: () => void
}

const props = defineProps<{
  visible: boolean
  files: DataFile[]
  combinations: DataCombination[]
}>()

const emit = defineEmits<{
  'update:visible': [value: boolean]
  submit: [payload: { fileIds: number[]; combinationId: number; batchNo?: string }]
}>()

const tableRef = ref<TableSelectionHandle | null>(null)
const search = ref('')
const sourceBatch = ref('')
const combinationId = ref<number | null>(null)
const batchNo = ref('')
const selectedIds = ref<Set<number>>(new Set())

const sourceOptions = computed(() => [...new Set(
  props.files.map(file => file.batch_name).filter(Boolean),
)].sort().map(value => ({ value, label: value })))
const combinationOptions = computed(() => props.combinations.map(combo => ({
  value: combo.id,
  label: combo.name,
})))
const targetCombination = computed(() => props.combinations.find(
  combo => combo.id === combinationId.value,
) ?? null)
const filteredFiles = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return props.files.filter(file => (
    (!sourceBatch.value || file.batch_name === sourceBatch.value)
    && (!keyword || file.filename.toLowerCase().includes(keyword))
  ))
})

function previewTags(row: DataFile) {
  if (!targetCombination.value) return []
  const value = batchNo.value.trim() || row.batch_no || ''
  return value
    ? [targetCombination.value.name, `${targetCombination.value.name} / ${value}`]
    : [targetCombination.value.name]
}

function onSelectionChange(rows: DataFile[]) {
  selectedIds.value = new Set(rows.map(row => row.id))
}

async function selectSourceBatch() {
  if (!sourceBatch.value) return
  search.value = ''
  await nextTick()
  const next = new Set(selectedIds.value)
  for (const file of filteredFiles.value) {
    tableRef.value?.toggleRowSelection(file, true)
    next.add(file.id)
  }
  selectedIds.value = next
}

function reset() {
  search.value = ''
  sourceBatch.value = ''
  combinationId.value = null
  batchNo.value = ''
  selectedIds.value = new Set()
  tableRef.value?.clearSelection()
}

function submit() {
  if (combinationId.value === null || selectedIds.value.size === 0) return
  const value = batchNo.value.trim()
  emit('submit', {
    fileIds: [...selectedIds.value].sort((a, b) => a - b),
    combinationId: combinationId.value,
    ...(value ? { batchNo: value } : {}),
  })
}

watch(() => props.visible, visible => {
  if (visible) reset()
})
watch(() => props.files, files => {
  const ids = new Set(files.map(file => file.id))
  selectedIds.value = new Set([...selectedIds.value].filter(id => ids.has(id)))
})
</script>

<style scoped>
.existing-filters,
.existing-target {
  display: flex;
  align-items: end;
  flex-wrap: wrap;
  gap: var(--p-space-3);
  margin-bottom: var(--p-space-3);
}

.existing-filters .el-input {
  width: 220px;
}

.existing-filters .el-select-v2 {
  width: 200px;
}

.selected-count,
.footer-note {
  color: var(--text-2);
  font-size: var(--p-fs-dense);
}

.existing-target {
  margin-top: var(--p-space-4);
}

.existing-target label {
  display: grid;
  gap: var(--p-space-1);
  color: var(--text-2);
  font-size: var(--p-fs-dense);
}

.existing-target .el-select-v2,
.existing-target .el-input {
  width: 260px;
}

.file-name {
  color: var(--text);
  overflow-wrap: anywhere;
}

.managed-preview {
  display: flex;
  flex-wrap: wrap;
  gap: var(--p-space-1);
}

.footer-note {
  margin-right: auto;
}

@media (max-width: 760px) {
  .existing-target label,
  .existing-target .el-select-v2,
  .existing-target .el-input {
    width: 100%;
  }
}
</style>
