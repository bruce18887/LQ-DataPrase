<template>
  <el-table
    ref="tableRef"
    :data="files"
    :row-key="(row: any) => row.id"
    stripe
    style="width: 100%"
    v-loading="loading"
    :header-cell-style="{ background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontWeight: '600' }"
    :row-class-name="tableRowClassName"
    :default-sort="{ prop: 'created_at', order: 'descending' }"
    @sort-change="onSortChange"
    @row-click="emit('row-click', $event.id, $event.filename)"
    @selection-change="onSelectionChange"
    @expand-change="onExpandChange"
    :expand-row-keys="expandedRowIds"
    highlight-current-row
  >
    <el-table-column type="expand">
      <template #default="{ row }">
        <FileRowDetail :row="row" @remove-tag="removeTag" />
      </template>
    </el-table-column>
    <el-table-column type="selection" width="44" align="center" />
    <el-table-column prop="id" label="ID" min-width="64" align="center" sortable="custom">
      <template #default="{ row }">
        <span class="id-badge">#{{ row.id }}</span>
      </template>
    </el-table-column>
    <el-table-column prop="filename" label="文件名" min-width="230" sortable="custom">
      <template #header>
        <span class="header-with-filter">
          文件名
          <ColumnHeaderFilter v-model="filters.filename" mode="input" label="文件名" testid="filename" />
        </span>
      </template>
      <template #default="{ row }">
        <div class="filename-cell">
          <span class="file-icon">📄</span>
          <span class="file-name" :title="row.filename">{{ truncateMiddle(row.filename, 32) }}</span>
        </div>
      </template>
    </el-table-column>
    <el-table-column prop="product_code" label="产品" min-width="120">
      <template #header>
        <span class="header-with-filter">
          产品
          <ColumnHeaderFilter v-model="filters.productCode" mode="select" :options="productCodes" label="产品" testid="product" />
        </span>
      </template>
      <template #default="{ row }">
        <el-tag v-if="row.product_code" size="small" type="info" effect="plain">
          {{ row.product_code }}
        </el-tag>
        <span v-else class="empty-text">—</span>
      </template>
    </el-table-column>
    <el-table-column prop="format_type" label="格式" min-width="96">
      <template #header>
        <span class="header-with-filter">
          格式
          <ColumnHeaderFilter v-model="filters.formatType" mode="select" :options="formatTypes" label="格式" testid="format" />
        </span>
      </template>
    </el-table-column>
    <el-table-column prop="program_name" label="测试程序" min-width="150">
      <template #header>
        <span class="header-with-filter">
          测试程序
          <ColumnHeaderFilter v-model="filters.program" mode="input" label="测试程序" testid="program" />
        </span>
      </template>
      <template #default="{ row }">
        <span class="program-name-cell" :title="row.program_name">{{ row.program_name || '—' }}</span>
      </template>
    </el-table-column>
    <el-table-column label="标签" min-width="200" class-name="tag-cell">
      <template #header>
        <span class="header-with-filter">
          标签
          <ColumnHeaderFilter v-model="filters.tag" mode="select" :options="allTags" label="标签" testid="tag" />
        </span>
      </template>
      <template #default="{ row }">
        <div class="tag-cell-inner">
          <el-tag
            v-for="t in (row.tags || [])"
            :key="t"
            closable
            size="small"
            type="info"
            effect="light"
            class="file-tag"
            @close="removeTag(row, t)"
          >{{ t }}</el-tag>
          <div v-if="editingId === row.id" class="tag-input-wrapper">
            <input
              :ref="tagInputRef"
              :value="newTagValue"
              type="text"
              class="tag-native-input"
              placeholder="新标签+回车"
              maxlength="50"
              @input="onTagInput"
              @keydown="onTagKeydown($event, row)"
              @blur="scheduleBlurCommit(row)"
            />
            <div v-if="showTagSuggestions && tagSuggestions.length > 0" class="tag-suggestions">
              <div
                v-for="(s, i) in tagSuggestions"
                :key="s"
                class="tag-suggestion-item"
                :class="{ 'is-active': i === selectedSuggestionIdx }"
                @mousedown.prevent="selectSuggestion(s)"
              >
                {{ s }}
              </div>
            </div>
          </div>
          <el-button
            v-else
            size="small"
            type="primary"
            plain
            class="add-tag-btn"
            @click.stop="startAddTag(row)"
          >
            <el-icon><Plus /></el-icon>
          </el-button>
        </div>
      </template>
    </el-table-column>
    <el-table-column prop="created_at" label="上传时间" min-width="150" sortable="custom">
      <template #default="{ row }">
        <span class="time-text">{{ formatTime(row.created_at) }}</span>
      </template>
    </el-table-column>
    <el-table-column prop="file_size" label="大小" min-width="90" align="right" sortable="custom">
      <template #default="{ row }">
        <span class="size-badge">{{ formatSize(row.file_size) }}</span>
      </template>
    </el-table-column>
    <el-table-column label="操作" width="140" align="center" fixed="right">
      <template #default="{ row }">
        <el-button size="small" type="primary" plain @click.stop="emit('view-file', row.id, row.filename)">查看</el-button>
        <el-button size="small" type="danger" plain @click.stop="emit('delete-file', row)">
          <el-icon><Delete /></el-icon> 删除
        </el-button>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup lang="ts">
import { ref, toRef } from 'vue'
import { Plus, Delete } from '@element-plus/icons-vue'
import type { ElTable } from 'element-plus'
import { truncateMiddle, formatSize, formatTime } from '../../../utils/format'
import { useTagEditing } from '../composables/useTagEditing'
import FileRowDetail from './FileRowDetail.vue'
import ColumnHeaderFilter from './ColumnHeaderFilter.vue'

/**
 * 表头筛选状态由父组件持有（服务端筛选参数），此处 v-model 直接读写
 * 传入 reactive 对象的嵌套字段（不替换 prop 本身）。
 */
export interface FileFilters {
  filename: string
  productCode: string
  formatType: string
  program: string
  tag: string
}

const props = defineProps<{
  files: any[]
  loading: boolean
  filters: FileFilters
  productCodes: string[]
  formatTypes: string[]
  allTags: string[]
}>()

const emit = defineEmits<{
  'view-file': [id: number, filename: string]
  'row-click': [id: number, filename: string]
  'delete-file': [row: any]
  'sort-change': [payload: { prop: string; order: 'ascending' | 'descending' | null }]
  'selection-change': [ids: number[]]
  'tags-changed': []
}>()

const {
  editingId, newTagValue, tagInputRef,
  tagSuggestions, showTagSuggestions, selectedSuggestionIdx,
  startAddTag, scheduleBlurCommit, removeTag,
  onTagInput, selectSuggestion, onTagKeydown,
} = useTagEditing(toRef(props, 'files'), () => emit('tags-changed'))

const tableRef = ref<InstanceType<typeof ElTable>>()

// Expand row state
const expandedRowIds = ref<number[]>([])
function onExpandChange(_row: any, expanded: any[]) {
  expandedRowIds.value = expanded.map((r: any) => r.id)
}

function onSortChange({ prop, order }: { prop: string; order: 'ascending' | 'descending' | null }) {
  emit('sort-change', { prop, order })
}

function onSelectionChange(rows: any[]) {
  emit('selection-change', rows.map((r) => r.id))
}

function tableRowClassName({ rowIndex }: { rowIndex: number }) {
  return rowIndex % 2 === 0 ? 'row-even' : 'row-odd'
}

defineExpose({ clearSelection: () => tableRef.value?.clearSelection() })
</script>

<style scoped>
.empty-text {
  color: var(--text-tertiary);
}

/* ============================
   表头筛选
   ============================ */
.header-with-filter {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  white-space: nowrap;
}

/* ============================
   Tag Cell
   ============================ */
.tag-cell-inner {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 28px;
  max-height: 80px;
  overflow-y: auto;
}

.file-tag {
  margin: 0;
}

.add-tag-btn {
  font-size: 12px;
  padding: 2px 8px;
  height: 24px;
}

.tag-native-input {
  width: 140px;
  height: 24px;
  padding: 0 8px;
  font-size: 12px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--brand-primary);
  border-radius: 4px;
  outline: none;
  box-sizing: border-box;
}

.tag-native-input::placeholder {
  color: var(--text-tertiary);
}

.tag-input-wrapper {
  position: relative;
  display: inline-block;
}

.tag-suggestions {
  position: absolute;
  bottom: 100%;
  left: 0;
  min-width: 180px;
  max-height: 200px;
  overflow-y: auto;
  background: var(--bg-primary);
  border: 1px solid var(--border-default);
  border-radius: 6px;
  box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.15);
  z-index: 100;
  margin-bottom: 4px;
}

.tag-suggestion-item {
  padding: 6px 12px;
  font-size: 12px;
  color: var(--text-primary);
  cursor: pointer;
  transition: background 0.15s;
}

.tag-suggestion-item:hover,
.tag-suggestion-item.is-active {
  background: var(--bg-secondary);
  color: var(--brand-primary);
}

:root[data-theme="night"] .tag-suggestions {
  background: var(--bg-secondary);
  border-color: rgba(255, 255, 255, 0.1);
  box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.4);
}

/* ============================
   Table Styling（列压缩优化：min-width 下限 + 横向滚动条常显）
   ============================ */
:deep(.el-table) {
  --el-table-border-color: var(--border-muted);
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: var(--bg-secondary);
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--border-muted);
}

:deep(.el-table .el-scrollbar__bar.is-horizontal) {
  opacity: 1;
}

:deep(.el-table th.el-table__cell) {
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

:deep(.el-table .row-even) {
  --el-table-tr-bg-color: transparent;
}

:deep(.el-table .row-odd) {
  --el-table-tr-bg-color: var(--bg-secondary);
}

:deep(.el-table .el-table__row) {
  cursor: pointer;
  transition: background 0.15s ease;
}

:deep(.el-table .el-table__row:hover > td) {
  background: var(--bg-secondary) !important;
}

.id-badge {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.filename-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.file-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.program-name-cell {
  color: var(--text-secondary);
  font-size: 12px;
}

.time-text {
  font-size: 12px;
  color: var(--text-secondary);
  font-family: var(--font-mono);
}

.size-badge {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-info);
  font-family: var(--font-mono);
}

/* ============================
   Night Theme Overrides
   ============================ */
:root[data-theme="night"] .size-badge {
  color: var(--color-info);
}
</style>
