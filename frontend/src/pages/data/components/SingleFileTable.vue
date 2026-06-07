<template>
  <div class="single-file-table-wrapper">
    <el-table
      :data="pagedFiles"
      :row-key="(row: DataFile) => row.id"
      stripe
      border
      size="small"
      class="single-file-table"
      empty-text="暂无单文件"
      :default-sort="{ prop: 'created_at', order: 'descending' }"
      @expand-change="onExpandChange"
      :expand-row-keys="expandedRowIds"
    >
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="row-detail">
            <div class="detail-row">
              <span class="detail-label">完整文件名</span>
              <span class="detail-value mono">{{ row.filename }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">测试程序</span>
              <span class="detail-value">{{ row.program_name || '—' }}</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">所有标签</span>
              <div class="detail-value tag-wrap">
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
                <span v-if="!row.tags || row.tags.length === 0" class="empty-text">无标签</span>
              </div>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="filename" label="文件名" min-width="200">
        <template #default="{ row }">
          <span :class="{ 'active-file-name': row.id === activeFileId }" :title="row.filename">{{ truncateMiddle(row.filename, 32) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="format_type" label="格式" width="90" />
      <el-table-column label="行列" width="120" align="center">
        <template #default="{ row }">
          <span class="mono">{{ row.row_count }} × {{ row.col_count }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="program_name" label="测试程序" min-width="160">
        <template #default="{ row }">
          <span class="program-name-cell" :title="row.program_name">{{ row.program_name || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="标签" min-width="240" class-name="tag-cell">
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
            <input
              v-if="editingId === row.id"
              ref="tagInputRef"
              v-model="newTagValue"
              type="text"
              class="tag-native-input"
              placeholder="新标签+回车"
              maxlength="50"
              :data-row-id="row.id"
              @keyup.enter="commitNewTag(row)"
              @blur="scheduleBlurCommit(row)"
            />
            <el-button
              v-else
              size="small"
              type="primary"
              plain
              class="add-tag-btn"
              @click="startAddTag(row)"
            >
              <el-icon><Plus /></el-icon>
              <span>添加</span>
            </el-button>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="90" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'" effect="plain">
            {{ row.status || 'unknown' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" align="center" fixed="right">
        <template #default="{ row }">
          <el-button
            size="small"
            type="primary"
            @click="emit('file-selected', row.id)"
          >
            {{ row.id === activeFileId ? '✓ 当前' : '浏览数据' }}
          </el-button>
          <el-button
            size="small"
            type="danger"
            plain
            @click="emit('delete-file', row)"
            aria-label="删除文件"
          >
            <el-icon><Delete /></el-icon>
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pagination-bar">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[25, 50, 100]"
        :total="files.length"
        layout="total, sizes, prev, pager, next, jumper"
        background
        size="small"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, nextTick } from 'vue'
import { Plus, Delete } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { datafilesApi } from '../../../api/datafiles'
import type { DataFile } from '../../../types'

const props = defineProps<{
  files: DataFile[]
  activeFileId?: number
}>()

const emit = defineEmits<{
  'file-selected': [id: number]
  'delete-file': [file: DataFile]
  'tags-updated': [file: DataFile]
}>()

const currentPage = ref(1)
const pageSize = ref(25)
const editingId = ref<number | null>(null)
const newTagValue = ref('')
const tagInputRef = ref<any>(null)

// Expand row state
const expandedRowIds = ref<number[]>([])
function onExpandChange(_row: DataFile, expanded: DataFile[]) {
  expandedRowIds.value = expanded.map((r) => r.id)
}

// 中段省略号
function truncateMiddle(s: string, max: number) {
  if (!s || s.length <= max) return s
  const head = Math.ceil(max / 2) - 1
  const tail = Math.floor(max / 2) - 1
  return s.slice(0, head) + '…' + s.slice(-tail)
}

const pagedFiles = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return props.files.slice(start, start + pageSize.value)
})

function startAddTag(row: DataFile) {
  editingId.value = row.id
  newTagValue.value = ''
  nextTick(() => {
    const el = (tagInputRef.value as any)?.$el ?? tagInputRef.value
    if (el && typeof el.focus === 'function') el.focus()
  })
}

// Blur commit is delayed so that a real Enter press (keyup.enter fires before blur)
// can take precedence. Without this, el-table's internal layout reflow right after
// `startAddTag` triggers an immediate blur that wipes the empty newTagValue and
// sets editingId=null, removing the input before the user can type.
let blurTimer: ReturnType<typeof setTimeout> | null = null
function scheduleBlurCommit(row: DataFile) {
  if (blurTimer) clearTimeout(blurTimer)
  blurTimer = setTimeout(() => {
    blurTimer = null
    // Only act if this row is still the active editor and the user actually typed something.
    if (editingId.value !== row.id) return
    const t = newTagValue.value.trim()
    if (t) {
      commitNewTag(row)
    } else {
      editingId.value = null
      newTagValue.value = ''
    }
  }, 150)
}

async function commitNewTag(row: DataFile) {
  const t = newTagValue.value.trim()
  if (!t) {
    editingId.value = null
    newTagValue.value = ''
    return
  }
  const current = Array.isArray(row.tags) ? row.tags : []
  if (current.some((x) => x.toLowerCase() === t.toLowerCase())) {
    ElMessage.warning(`标签「${t}」已存在`)
    editingId.value = null
    newTagValue.value = ''
    return
  }
  const next = [...current, t]
  try {
    const { data } = await datafilesApi.setTags(row.id, next)
    // NOTE: 直接 row.tags = data.tags 只是改 props 内部对象的引用，Vue 不会追踪；
    // 真正的响应式更新由父组件 onSingleTagsUpdated 替换 files.value 触发（spread 后 el-table 重新渲染）。
    // 这里仍然赋值以保持子组件本地 row 引用同步。
    row.tags = data.tags
    emit('tags-updated', row)
    ElMessage.success(`已添加标签「${t}」`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.tags?.[0] || '标签更新失败')
  } finally {
    editingId.value = null
    newTagValue.value = ''
  }
}

async function removeTag(row: DataFile, tag: string) {
  const current = Array.isArray(row.tags) ? row.tags : []
  const next = current.filter((x) => x.toLowerCase() !== tag.toLowerCase())
  if (next.length === current.length) return
  try {
    const { data } = await datafilesApi.setTags(row.id, next)
    row.tags = data.tags
    emit('tags-updated', row)
    ElMessage.success(`已移除标签「${tag}」`)
  } catch {
    ElMessage.error('标签移除失败')
  }
}
</script>

<style scoped>
.single-file-table-wrapper {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.single-file-table {
  width: 100%;
  background: var(--bg-secondary);
  border-radius: 8px;
}

.active-file-name {
  color: var(--brand-primary);
  font-weight: 600;
}

.mono {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-secondary);
}

.program-name-cell {
  color: var(--text-secondary);
  font-size: 12px;
}

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

.tag-input {
  width: 140px;
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

.row-detail {
  padding: 12px 24px 16px 56px;
  background: var(--bg-secondary);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 6px 8px;
}
.detail-row {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  min-height: 20px;
}
.detail-label {
  flex-shrink: 0;
  width: 96px;
  font-size: 12px;
  color: var(--text-tertiary);
  padding-top: 1px;
}
.detail-value {
  flex: 1;
  font-size: 13px;
  color: var(--text-primary);
  word-break: break-all;
  line-height: 1.5;
}
.detail-value.tag-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  padding: 4px 0 12px;
}

:deep(.el-table) {
  --el-table-bg-color: var(--bg-secondary);
  --el-table-tr-bg-color: var(--bg-secondary);
  --el-table-header-bg-color: var(--bg-tertiary);
  --el-table-row-hover-bg-color: var(--bg-hover);
  --el-table-border-color: var(--border-muted);
  --el-table-header-text-color: var(--text-primary);
  --el-table-text-color: var(--text-primary);
}

:deep(.el-table th.el-table__cell) {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  font-weight: 600;
  border-bottom: 1px solid var(--border-default);
}

:deep(.el-table td.el-table__cell) {
  border-bottom: 1px solid var(--border-muted);
}

:deep(.el-pagination) {
  --el-pagination-bg-color: var(--bg-secondary);
  --el-pagination-button-bg-color: var(--bg-secondary);
  --el-pagination-hover-color: var(--brand-primary);
  color: var(--text-secondary);
}
</style>
