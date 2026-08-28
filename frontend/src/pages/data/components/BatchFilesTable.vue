<template>
  <div class="batch-files-table">
    <el-table
      ref="tableRef"
      :data="files"
      :row-key="(row: any) => row.id"
      size="small"
      max-height="420"
      style="width: 100%"
      :row-class-name="() => 'batch-file-row'"
      @selection-change="onSelectionChange"
    >
      <el-table-column type="selection" width="40" align="center" />
      <el-table-column label="文件名" min-width="200">
        <template #default="{ row }">
          <div class="bf-name-cell">
            <span v-if="row.status !== 'ready'" class="bf-error" title="解析失败或未就绪">
              <el-icon :size="13"><WarningFilled /></el-icon>
            </span>
            <span
              class="batch-filename"
              :class="{ 'is-active': row.id === activeFileId, 'batch-filename-wrap': wrapFilename }"
              :title="row.tags && row.tags.length ? `${row.filename}\n标签: ${row.tags.join(', ')}` : row.filename"
              @click="emit('file-selected', row.id)"
            >{{ row.filename }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="stage" label="阶段" min-width="72" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.stage" size="small" type="primary" effect="plain">{{ row.stage }}</el-tag>
          <span v-else class="dim-text">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="program_name" label="测试程序" min-width="150">
        <template #default="{ row }">
          <span class="dim-text bf-ellipsis" :title="row.program_name">{{ row.program_name || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="product_code" label="产品" min-width="100">
        <template #default="{ row }">
          <el-tag v-if="row.product_code" size="small" type="info" effect="plain">
            {{ row.product_code }}
          </el-tag>
          <span v-else class="dim-text">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="sub_batch" label="子批次" min-width="100">
        <template #default="{ row }">
          <span class="dim-text">{{ row.sub_batch || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="行列" min-width="84" align="center" sortable :sort-method="sortByRows">
        <template #default="{ row }">
          <span v-if="Number(row.row_count) === 0" class="bf-zero-rows" title="解析行数为 0（可能为空文件）">
            <el-icon :size="12"><WarningFilled /></el-icon>
          </span>
          <span class="mono dim-text">{{ row.row_count }}×{{ row.col_count }}</span>
        </template>
      </el-table-column>
      <el-table-column label="大小" min-width="84" align="right" sortable :sort-method="sortBySize">
        <template #default="{ row }">
          <span class="mono size-text">{{ formatSize(row.file_size) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="data_date" label="测试日期" min-width="104" sortable>
        <template #default="{ row }">
          <span class="dim-text mono" :title="row.data_date ? `从文件名解析：${row.filename}` : ''">
            {{ row.data_date || '—' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="118" align="center" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" plain @click.stop="emit('file-selected', row.id)">查看</el-button>
          <el-button size="small" type="warning" plain @click.stop="emit('remove-one', row)">移出</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { WarningFilled } from '@element-plus/icons-vue'
import type { ElTable } from 'element-plus'
import type { DataFile } from '../../../types'
import { formatSize } from '../../../utils/format'
import { getFilenameWrap } from '../../../utils/filenameWrap'

const props = defineProps<{
  files: DataFile[]
  activeFileId?: number
}>()

const emit = defineEmits<{
  'file-selected': [id: number]
  'selection-change': [ids: number[]]
  'remove-one': [row: DataFile]
}>()

const tableRef = ref<InstanceType<typeof ElTable>>()

// 文件名显示跟随系统设置 filename_wrap（默认开启；设置页「表格设置」统一控制）
const wrapFilename = ref(true)
onMounted(async () => {
  wrapFilename.value = await getFilenameWrap()
})

function onSelectionChange(rows: any[]) {
  emit('selection-change', rows.map((r) => r.id))
}

/** 页内排序：大小（file_size） */
function sortBySize(a: DataFile, b: DataFile) {
  return (Number(a.file_size) || 0) - (Number(b.file_size) || 0)
}

/** 页内排序：行列（row_count×col_count 乘积） */
function sortByRows(a: DataFile, b: DataFile) {
  return (Number(a.row_count) || 0) * (Number(a.col_count) || 0)
    - (Number(b.row_count) || 0) * (Number(b.col_count) || 0)
}

defineExpose({
  clearSelection: () => tableRef.value?.clearSelection(),
})
</script>

<style scoped>
.batch-files-table {
  overflow: hidden;
}

.bf-name-cell {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  min-width: 0;
}

.bf-error {
  color: var(--color-danger);
  display: inline-flex;
  flex-shrink: 0;
}

.bf-zero-rows {
  color: var(--color-warning);
  display: inline-flex;
  margin-right: 4px;
  vertical-align: middle;
}

.batch-filename {
  cursor: pointer;
  font-size: 12px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.batch-filename-wrap {
  white-space: normal;
  word-break: break-all;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
  text-overflow: ellipsis;
}

.batch-filename:hover {
  color: var(--brand-primary);
}

.batch-filename.is-active {
  color: var(--brand-primary);
  font-weight: 600;
}

.bf-ellipsis {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.dim-text {
  color: var(--text-secondary);
  font-size: 12px;
}

.mono {
  font-family: var(--font-mono);
}

.size-text {
  color: var(--color-info);
  font-weight: 600;
}
</style>
