<template>
  <div class="file-list-tab">
    <!-- Toolbar -->
    <FileListToolbar
      :total="total"
      :selected-count="selectedIds.length"
      @search="onSearch"
      @upload-click="showUpload = !showUpload"
      @fix-click="showConsistencyCheck = true"
      @bulk-delete="onBulkDelete"
      @combine-click="onCombine"
    />

    <!-- Upload Area -->
    <FileUploadArea
      :visible="showUpload"
      @upload-success="onUploadSuccess"
    />

    <!-- File Table（表头内嵌筛选：产品/格式/文件名/程序/标签；服务端分页筛选） -->
    <FileListTable
      ref="tableRef"
      :files="files"
      :loading="loading"
      :filters="filters"
      :product-codes="productCodes"
      :format-types="formatTypes"
      :all-tags="allTags"
      @view-file="viewFile"
      @row-click="onRowClick"
      @delete-file="deleteFile"
      @sort-change="onSortChange"
      @selection-change="onSelectionChange"
      @tags-changed="loadAllTags"
    />

    <!-- Active filter chips -->
    <div v-if="hasActiveFilters" class="active-filters">
      <span class="filter-hint">
        已启用 {{ activeFilterCount }} 项表头筛选
        <el-button size="small" text type="primary" @click="clearFilters">清除全部</el-button>
      </span>
    </div>

    <!-- Pagination -->
    <div class="list-pagination">
      <el-pagination
        v-if="total > pageSize"
        layout="total, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page="currentPage"
        background
        @current-change="onPageChange"
      />
    </div>

    <!-- Consistency Check Dialog -->
    <ConsistencyCheckDialog
      v-model:visible="showConsistencyCheck"
      @done="onConsistencyDone"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { datafilesApi } from '../../../api/datafiles'
import { useFilesStore } from '../../../stores/files'
import FileListToolbar from './FileListToolbar.vue'
import FileUploadArea from './FileUploadArea.vue'
import ConsistencyCheckDialog from './ConsistencyCheckDialog.vue'
import FileListTable, { type FileFilters } from './FileListTable.vue'

const emit = defineEmits<{
  'view-file': [id: number, filename: string]
  'row-click': [id: number, filename: string]
  'total-change': [total: number]
}>()

const filesStore = useFilesStore()

// ── Core state ──────────────────────────────────────────────────────
const files = ref<any[]>([])
const loading = ref(false)
const total = ref(0)
const currentPage = ref(1)
const pageSize = 20

const productCodes = ref<string[]>([])
const formatTypes = ref<string[]>([])
const allTags = ref<string[]>([])
const selectedIds = ref<number[]>([])
const tableRef = ref<InstanceType<typeof FileListTable>>()

// Current global keyword search (toolbar)
const currentSearch = ref('')

// ── 表头筛选（服务端生效：20 条/页必须后端过滤；状态由 FileListTable 读写） ──
const filters = reactive<FileFilters>({
  filename: '',
  productCode: '',
  formatType: '',
  program: '',
  tag: '',
})

const activeFilterCount = computed(
  () => Object.values(filters).filter((v) => v !== '').length,
)
const hasActiveFilters = computed(() => activeFilterCount.value > 0)

// 表头排序：默认最新上传在前（与服务端 ordering 一致，default-sort 显示箭头）
const ordering = ref('-created_at')

// Upload / dialog toggles
const showUpload = ref(false)
const showConsistencyCheck = ref(false)

/** 表头排序变化（服务端排序：20 条/页必须后端排，不能本地 sort） */
function onSortChange({ prop, order }: { prop: string; order: 'ascending' | 'descending' | null }) {
  if (!prop || !order) {
    ordering.value = '-created_at' // 取消排序 → 回默认最新在前
  } else {
    const sign = order === 'descending' ? '-' : ''
    ordering.value = `${sign}${prop}`
  }
  currentPage.value = 1
  loadFiles()
}

function clearFilters() {
  filters.filename = ''
  filters.productCode = ''
  filters.formatType = ''
  filters.program = ''
  filters.tag = ''
  currentPage.value = 1
  loadFiles()
}

// ── Data loading ────────────────────────────────────────────────────
async function loadFiles() {
  loading.value = true
  try {
    const { data } = await datafilesApi.listFiles({
      page: currentPage.value,
      search: currentSearch.value,
      file_type: 'single',
      product_code: filters.productCode,
      format_type: filters.formatType,
      filename__icontains: filters.filename,
      program_name__icontains: filters.program,
      tag: filters.tag,
      ordering: ordering.value,
    })
    if (Array.isArray(data)) {
      files.value = data
      total.value = data.length
    } else {
      files.value = data.results ?? []
      total.value = data.count ?? files.value.length
    }
    emit('total-change', total.value)
  } catch {
    files.value = []
    total.value = 0
    emit('total-change', 0)
  } finally {
    loading.value = false
  }
}

async function loadProductCodes() {
  try {
    const { data } = await datafilesApi.getProductCodes()
    productCodes.value = data.product_codes ?? []
  } catch {
    productCodes.value = []
  }
}

async function loadFormatTypes() {
  try {
    const { data } = await datafilesApi.getFormatTypes()
    formatTypes.value = data.format_types ?? []
  } catch {
    formatTypes.value = []
  }
}

async function loadAllTags() {
  try {
    const { data } = await datafilesApi.listTags()
    allTags.value = Array.isArray(data?.tags) ? data.tags : []
  } catch {
    allTags.value = []
  }
}

// ── Toolbar event handlers ──────────────────────────────────────────
function onSearch(text: string) {
  currentSearch.value = text
  currentPage.value = 1
  loadFiles()
}

function onUploadSuccess() {
  loadFiles()
  filesStore.notifyFilesChanged()
}

function onConsistencyDone() {
  loadFiles()
  filesStore.notifyFilesChanged()
}

// ── 组合为批次 ──────────────────────────────────────────────────────
async function onCombine() {
  if (selectedIds.value.length < 2) {
    ElMessage.warning('请至少选择 2 个文件进行组合')
    return
  }
  try {
    const { value } = await ElMessageBox.prompt(
      `将选中的 ${selectedIds.value.length} 个文件组合为批次（文件将移动到批次目录）：`,
      '组合为批次',
      {
        confirmButtonText: '组合',
        cancelButtonText: '取消',
        inputPattern: /\S+/,
        inputErrorMessage: '批次名称不能为空',
        inputPlaceholder: '请输入批次名称',
      },
    )
    const name = (value || '').trim()
    if (!name) return
    const { data } = await datafilesApi.combineFiles([...selectedIds.value], name)
    ElMessage.success(`已组合 ${data.combined} 个文件为批次 "${data.batch_name}"`)
    tableRef.value?.clearSelection()
    selectedIds.value = []
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch {
    // ElMessageBox 取消 reject "cancel"；真实错误 toast 由拦截器弹出
  }
}

// ── Pagination ──────────────────────────────────────────────────────
function onPageChange(page: number) {
  currentPage.value = page
  loadFiles()
}

function onSelectionChange(ids: number[]) {
  selectedIds.value = ids
}

// ── Delete operations ───────────────────────────────────────────────
async function deleteFile(row: any) {
  try {
    await ElMessageBox.confirm(
      `确定删除文件 "${row.filename}" 吗？此操作不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    await datafilesApi.remove(row.id)
    ElMessage.success('文件已删除')
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch {
    // ElMessageBox 取消 reject "cancel"；真实错误 toast 由拦截器弹出
  }
}

async function onBulkDelete() {
  if (selectedIds.value.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${selectedIds.value.length} 个文件吗？磁盘上的源文件也会被一并移除，此操作不可恢复。`,
      '批量删除确认',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    const ids = [...selectedIds.value]
    const { data } = await datafilesApi.bulkDelete(ids)
    ElMessage.success(`已删除 ${data?.deleted ?? ids.length} 个文件`)
    tableRef.value?.clearSelection()
    selectedIds.value = []
    if (files.value.length === ids.length && currentPage.value > 1) {
      currentPage.value -= 1
    }
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch {
    // ElMessageBox 取消 reject "cancel"；真实错误 toast 由拦截器弹出
  }
}

// ── Row interactions ────────────────────────────────────────────────
function viewFile(id: number, filename: string) {
  emit('view-file', id, filename)
}

function onRowClick(id: number, filename: string) {
  emit('row-click', id, filename)
}

// ── External refresh watcher ────────────────────────────────────────
watch(() => filesStore.filesVersion, () => {
  loadFiles()
  loadProductCodes()
  loadFormatTypes()
  loadAllTags()
})

// 表头筛选值变化 → 刷新（FileListTable 内 ColumnHeaderFilter 写入 filters）
watch(filters, () => {
  currentPage.value = 1
  loadFiles()
}, { deep: true })

onMounted(() => {
  loadFiles()
  loadProductCodes()
  loadFormatTypes()
  loadAllTags()
})

defineExpose({ reload: loadFiles })
</script>

<style scoped>
.list-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.active-filters {
  display: flex;
  align-items: center;
  margin-top: 8px;
}

.filter-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

/* ============================
   Night Theme Overrides
   ============================ */
:root[data-theme="night"] .filter-hint {
  color: rgba(255, 255, 255, 0.5);
}
</style>
