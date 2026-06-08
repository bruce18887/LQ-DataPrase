<template>
  <div class="file-list-tab">
    <!-- Toolbar -->
    <div class="list-toolbar">
      <div class="toolbar-left">
        <span class="section-title">📋 文件列表</span>
        <span class="section-count">{{ total }} 个文件</span>
      </div>
      <div class="toolbar-right">
        <el-input
          v-model="searchText"
          placeholder="按文件名/程序名/标签搜索"
          clearable
          class="search-input"
          @input="onSearchInput"
          @clear="onSearchInput"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-select
          v-model="productCode"
          placeholder="全部产品"
          clearable
          class="product-filter"
          @change="onFilterChange"
        >
          <el-option
            v-for="code in productCodes"
            :key="code"
            :label="code"
            :value="code"
          />
        </el-select>
        <el-button
          type="primary"
          @click="showUpload = !showUpload"
        >
          <el-icon><Upload /></el-icon>
          上传文件
        </el-button>
        <el-button
          type="danger"
          plain
          :disabled="selectedIds.length === 0"
          @click="onBulkDelete"
        >
          <el-icon><Delete /></el-icon>
          批量删除{{ selectedIds.length ? ` (${selectedIds.length})` : '' }}
        </el-button>
        <el-button
          type="warning"
          plain
          @click="showConsistencyCheck = true"
        >
          <el-icon><Tools /></el-icon>
          数据修复
        </el-button>
      </div>
    </div>

    <!-- Upload Area (Collapsible) -->
    <el-collapse-transition>
      <div v-show="showUpload" class="upload-section">
        <el-upload
          drag
          :http-request="handleUpload"
          accept=".csv,.txt,.dat,.zip,.7z,.rar"
          :show-file-list="false"
          multiple
        >
          <el-icon :size="48"><UploadFilled /></el-icon>
          <div class="upload-text">拖拽文件到此处 或 <em>点击上传</em></div>
          <div class="upload-hint">支持多文件上传，ZIP/7z/RAR 压缩包会自动解压</div>
        </el-upload>
        <el-progress
          v-if="uploadProgress > 0 && uploadProgress < 100"
          :percentage="uploadProgress"
          style="margin-top: 8px"
        />
      </div>
    </el-collapse-transition>

    <!-- Batch Management (Conditional) -->
    <template v-if="unregisteredDirs.length > 0 || batchGroups.length > 0">
      <div class="batch-section">
        <!-- Unregistered batch directories -->
        <template v-if="unregisteredDirs.length > 0">
          <div class="section-label">📂 SFTP 下载目录（未导入）</div>
          <div v-for="dir in unregisteredDirs" :key="dir.name" class="batch-group unregistered">
            <div class="batch-header">
              <span class="batch-name">📁 {{ dir.name }}</span>
              <span class="batch-count">{{ dir.file_count }} 个文件</span>
              <span class="batch-size">{{ formatSize(dir.total_size) }}</span>
              <div style="flex:1" />
              <el-button size="small" type="success" @click="importDir(dir)" :loading="importingDir === dir.name">
                <el-icon><Upload /></el-icon> 导入
              </el-button>
              <el-button size="small" type="danger" plain @click="deleteDir(dir)">
                <el-icon><Delete /></el-icon> 删除
              </el-button>
            </div>
          </div>
        </template>

        <!-- Batch files grouped (registered) -->
        <template v-if="batchGroups.length > 0">
          <div class="section-label-row">
            <span class="section-label">📦 已导入批次</span>
            <el-button
              size="small"
              text
              class="batch-toggle-all"
              :data-testid="'batch-toggle-all'"
              @click="toggleAllBatches"
            >
              <el-icon><component :is="allBatchesExpanded ? ArrowUp : ArrowDown" /></el-icon>
              {{ allBatchesExpanded ? '全部折叠' : '全部展开' }}
            </el-button>
          </div>
          <div v-for="group in batchGroups" :key="group.name" class="batch-group" :data-testid="`batch-group-${group.name}`">
            <div
              class="batch-header batch-header-clickable"
              role="button"
              tabindex="0"
              :aria-expanded="isBatchExpanded(group.name)"
              :data-testid="`batch-header-${group.name}`"
              @click="toggleBatch(group.name)"
              @keydown.enter.prevent="toggleBatch(group.name)"
              @keydown.space.prevent="toggleBatch(group.name)"
            >
              <el-icon class="batch-chevron" :class="{ 'batch-chevron-open': isBatchExpanded(group.name) }">
                <ArrowRight />
              </el-icon>
              <span class="batch-name">📦 {{ group.name }}</span>
              <span class="batch-count">{{ group.files.length }} 个文件</span>
              <div style="flex:1" />
              <el-button
                size="small"
                type="danger"
                plain
                @click.stop="deleteBatch(group)"
              >
                <el-icon><Delete /></el-icon> 删除批次
              </el-button>
            </div>
            <el-collapse-transition>
              <div v-show="isBatchExpanded(group.name)" class="batch-files" :data-testid="`batch-files-${group.name}`">
                <!-- 有子批次时按子批次分组显示 -->
                <template v-if="group.subBatches && group.subBatches.length > 0">
                  <div v-for="sub in group.subBatches" :key="sub.name" class="sub-batch-group">
                    <div class="sub-batch-header">
                      <span class="sub-batch-name">📁 {{ sub.name }}</span>
                      <span class="sub-batch-count">{{ sub.files.length }} 个文件</span>
                    </div>
                    <div class="sub-batch-files">
                      <el-tag
                        v-for="f in sub.files"
                        :key="f.id"
                        :type="f.id === activeFileId ? 'primary' : 'info'"
                        :effect="f.id === activeFileId ? 'dark' : 'plain'"
                        class="batch-file-tag"
                        @click="emit('file-selected', f.id)"
                      >
                        {{ f.filename }}
                      </el-tag>
                    </div>
                  </div>
                </template>
                <!-- 无子批次时直接显示文件列表 -->
                <template v-else>
                  <el-tag
                    v-for="f in group.files"
                    :key="f.id"
                    :type="f.id === activeFileId ? 'primary' : 'info'"
                    :effect="f.id === activeFileId ? 'dark' : 'plain'"
                    class="batch-file-tag"
                    @click="emit('file-selected', f.id)"
                  >
                    {{ f.filename }}
                  </el-tag>
                </template>
              </div>
            </el-collapse-transition>
          </div>
        </template>
      </div>
    </template>

    <el-table
      ref="tableRef"
      :data="files"
      :row-key="(row: any) => row.id"
      stripe
      style="width: 100%"
      v-loading="loading"
      :header-cell-style="{ background: 'var(--bg-secondary)', color: 'var(--text-primary)', fontWeight: '600' }"
      :row-class-name="tableRowClassName"
      @row-click="onRowClick"
      @selection-change="onSelectionChange"
      @expand-change="onExpandChange"
      :expand-row-keys="expandedRowIds"
      highlight-current-row
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
      <el-table-column type="selection" width="44" align="center" />
      <el-table-column prop="id" label="ID" width="70" align="center">
        <template #default="{ row }">
          <span class="id-badge">#{{ row.id }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="filename" label="文件名" min-width="200">
        <template #default="{ row }">
          <div class="filename-cell">
            <span class="file-icon">📄</span>
            <span class="file-name" :title="row.filename">{{ truncateMiddle(row.filename, 32) }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="product_code" label="产品" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.product_code" size="small" type="info" effect="plain">
            {{ row.product_code }}
          </el-tag>
          <span v-else class="empty-text">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="format_type" label="格式" width="80" />
      <el-table-column label="行列" width="100" align="center">
        <template #default="{ row }">
          <span class="mono">{{ row.row_count }}×{{ row.col_count }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="program_name" label="测试程序" min-width="120">
        <template #default="{ row }">
          <span class="program-name-cell" :title="row.program_name">{{ row.program_name || '—' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="标签" min-width="180" class-name="tag-cell">
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
              @keyup.enter="commitNewTag(row)"
              @blur="scheduleBlurCommit(row)"
            />
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
      <el-table-column prop="created_at" label="上传时间" width="140">
        <template #default="{ row }">
          <span class="time-text">{{ formatTime(row.created_at) }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="file_size" label="大小" width="90" align="right">
        <template #default="{ row }">
          <span class="size-badge">{{ formatSize(row.file_size) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140" align="center" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" plain @click.stop="viewFile(row)">查看</el-button>
          <el-button size="small" type="danger" plain @click.stop="deleteFile(row)">
            <el-icon><Delete /></el-icon>
          </el-button>
        </template>
      </el-table-column>
    </el-table>

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

    <!-- 数据一致性检查对话框 -->
    <el-dialog
      v-model="showConsistencyCheck"
      title="数据一致性检查"
      width="700px"
      :close-on-click-modal="false"
    >
      <div v-if="!consistencyResult" v-loading="checkingConsistency">
        <el-alert
          title="数据一致性检查"
          description="检查数据库记录与磁盘文件的一致性，修复可能的数据不一致问题。"
          type="info"
          :closable="false"
          style="margin-bottom: 16px;"
        />
        <el-button type="primary" @click="runConsistencyCheck" :loading="checkingConsistency">
          开始检查
        </el-button>
      </div>
      <div v-else>
        <el-descriptions :column="2" border style="margin-bottom: 16px;">
          <el-descriptions-item label="孤立数据库记录">
            <el-tag :type="consistencyResult.orphaned_db_count > 0 ? 'danger' : 'success'">
              {{ consistencyResult.orphaned_db_count }} 条
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="孤立磁盘文件">
            <el-tag :type="consistencyResult.orphaned_disk_count > 0 ? 'warning' : 'success'">
              {{ consistencyResult.orphaned_disk_count }} 个
            </el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <!-- 孤立数据库记录 -->
        <el-card v-if="consistencyResult.orphaned_db_count > 0" style="margin-bottom: 16px;">
          <template #header>
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <span style="font-weight: 600;">孤立数据库记录</span>
              <el-tag type="danger" size="small">磁盘文件已删除</el-tag>
            </div>
          </template>
          <el-alert
            title="这些记录对应的磁盘文件已不存在，删除后无法恢复。"
            type="warning"
            :closable="false"
            show-icon
            style="margin-bottom: 12px;"
          />
          <el-table :data="consistencyResult.orphaned_db" max-height="200" size="small">
            <el-table-column prop="filename" label="文件名" min-width="200" />
            <el-table-column prop="batch_name" label="批次" width="150" />
          </el-table>
          <div style="margin-top: 12px; padding: 12px; background: var(--bg-secondary); border-radius: 8px;">
            <el-checkbox v-model="confirmDeleteOrphanedDb" style="margin-bottom: 8px;">
              <span style="color: var(--color-danger); font-weight: 600;">
                我已确认要删除这 {{ consistencyResult.orphaned_db_count }} 条孤立记录
              </span>
            </el-checkbox>
            <el-button
              type="danger"
              size="small"
              :disabled="!confirmDeleteOrphanedDb"
              @click="fixConsistency('delete_orphaned_db')"
              :loading="fixing"
            >
              <el-icon><Delete /></el-icon> 删除孤立记录
            </el-button>
          </div>
        </el-card>

        <!-- 孤立磁盘文件 -->
        <el-card v-if="consistencyResult.orphaned_disk_count > 0" style="margin-bottom: 16px;">
          <template #header>
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <span style="font-weight: 600;">孤立磁盘文件</span>
              <el-tag type="warning" size="small">数据库中无记录</el-tag>
            </div>
          </template>
          <el-alert
            title="这些文件在数据库中没有记录，删除后无法通过网页恢复。"
            type="warning"
            :closable="false"
            show-icon
            style="margin-bottom: 12px;"
          />
          <el-table :data="consistencyResult.orphaned_disk.map(p => ({ path: p }))" max-height="200" size="small">
            <el-table-column prop="path" label="文件路径" />
          </el-table>
          <div style="margin-top: 12px; padding: 12px; background: var(--bg-secondary); border-radius: 8px;">
            <el-checkbox v-model="confirmDeleteOrphanedDisk" style="margin-bottom: 8px;">
              <span style="color: var(--color-warning); font-weight: 600;">
                我已确认要删除这 {{ consistencyResult.orphaned_disk_count }} 个孤立文件
              </span>
            </el-checkbox>
            <el-button
              type="warning"
              size="small"
              :disabled="!confirmDeleteOrphanedDisk"
              @click="fixConsistency('delete_orphaned_disk')"
              :loading="fixing"
            >
              <el-icon><Delete /></el-icon> 删除孤立文件
            </el-button>
          </div>
        </el-card>

        <!-- 无问题 -->
        <div v-if="consistencyResult.orphaned_db_count === 0 && consistencyResult.orphaned_disk_count === 0"
             style="text-align: center; padding: 30px;">
          <el-icon :size="64" style="color: var(--color-success);"><CircleCheck /></el-icon>
          <p style="color: var(--text-primary); margin-top: 12px; font-size: 16px;">
            数据一致性检查通过，无问题发现。
          </p>
        </div>
      </div>
      <template #footer>
        <el-button @click="showConsistencyCheck = false">关闭</el-button>
        <el-button v-if="consistencyResult" type="primary" @click="consistencyResult = null">
          重新检查
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { Search, Delete, Upload, UploadFilled, Plus, ArrowRight, ArrowDown, ArrowUp, Tools, CircleCheck } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox, type ElTable } from 'element-plus'
import { datafilesApi, type BatchDirInfo } from '../../../api/datafiles'
import { useFilesStore } from '../../../stores/files'

const emit = defineEmits<{
  'view-file': [id: number, filename: string]
  'row-click': [id: number, filename: string]
  'total-change': [total: number]
  'file-selected': [id: number]
}>()

const props = defineProps<{
  activeFileId?: number
}>()

const filesStore = useFilesStore()

const files = ref<any[]>([])
const loading = ref(false)
const total = ref(0)
const currentPage = ref(1)
const pageSize = 20

const searchText = ref('')
const productCode = ref('')
const productCodes = ref<string[]>([])
const selectedRows = ref<any[]>([])
const tableRef = ref<InstanceType<typeof ElTable>>()

const selectedIds = ref<number[]>([])
let searchTimer: ReturnType<typeof setTimeout> | undefined

// Upload state
const showUpload = ref(false)
const uploadProgress = ref(0)

// Data consistency check state
const showConsistencyCheck = ref(false)
const checkingConsistency = ref(false)
const fixing = ref(false)
const confirmDeleteOrphanedDb = ref(false)
const confirmDeleteOrphanedDisk = ref(false)
const consistencyResult = ref<{
  orphaned_db_count: number
  orphaned_disk_count: number
  orphaned_db: Array<{ id: number; filename: string; batch_name: string; file_path: string }>
  orphaned_disk: string[]
} | null>(null)

// Batch management state
const batchDirs = ref<BatchDirInfo[]>([])
const importingDir = ref('')
// 已导入批次默认折叠：单批次可能含 100+ 文件，全部展开会撑高页面。
// 用户点击 header 单独展开需要的批次。
const expandedBatches = ref<Set<string>>(new Set())

function isBatchExpanded(name: string) {
  return expandedBatches.value.has(name)
}

function toggleBatch(name: string) {
  const next = new Set(expandedBatches.value)
  if (next.has(name)) {
    next.delete(name)
  } else {
    next.add(name)
  }
  expandedBatches.value = next
}

const allBatchesExpanded = computed(() => {
  if (batchGroups.value.length === 0) return false
  return batchGroups.value.every((g) => expandedBatches.value.has(g.name))
})

function toggleAllBatches() {
  if (allBatchesExpanded.value) {
    expandedBatches.value = new Set()
  } else {
    expandedBatches.value = new Set(batchGroups.value.map((g) => g.name))
  }
}

// Tag editing state
const editingId = ref<number | null>(null)
const newTagValue = ref('')
const tagInputRef = ref<any>(null)

// Expand row state (driven by expand-row-keys)
const expandedRowIds = ref<number[]>([])
function onExpandChange(_row: any, expanded: any[]) {
  expandedRowIds.value = expanded.map((r) => r.id)
}

// 中段省略号：保留首尾有信息量的部分（适合文件名/路径）
function truncateMiddle(s: string, max: number) {
  if (!s || s.length <= max) return s
  const head = Math.ceil(max / 2) - 1
  const tail = Math.floor(max / 2) - 1
  return s.slice(0, head) + '…' + s.slice(-tail)
}

// Computed
const unregisteredDirs = computed(() => batchDirs.value.filter(d => !d.registered))

// 已导入批次直接来自 batch-dirs（磁盘走查，返回全部批次），不再依赖分页 files —
// 否则新下载文件占满第 1 页后，旧批次被挤出列表而”消失”。
// 支持子批次：按 sub_batch 字段分组显示
const batchGroups = computed(() => {
  const registered = batchDirs.value.filter(d => d.registered)
  return registered.map(d => {
    // 按 sub_batch 分组
    const subBatchMap = new Map<string, any[]>()
    for (const f of d.files) {
      const sub = f.sub_batch || ''
      if (!subBatchMap.has(sub)) {
        subBatchMap.set(sub, [])
      }
      subBatchMap.get(sub)!.push(f)
    }
    // 如果只有一个子批次（或无子批次），保持原有结构
    if (subBatchMap.size <= 1) {
      return { name: d.name, files: d.files, subBatches: [] }
    }
    // 多个子批次时，返回子批次分组
    const subBatches = Array.from(subBatchMap.entries()).map(([sub, files]) => ({
      name: sub,
      files,
    }))
    return { name: d.name, files: d.files, subBatches }
  })
})

// Load files
async function loadFiles() {
  loading.value = true
  try {
    const { data } = await datafilesApi.listFiles({
      page: currentPage.value,
      search: searchText.value,
      product_code: productCode.value,
      ordering: '-created_at',
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

// Batch management
async function loadBatchDirs() {
  try {
    const { data } = await datafilesApi.listBatchDirs()
    batchDirs.value = Array.isArray(data) ? data : []
    // 清理已不存在的批次（用户可能在别的 tab 删了批次）
    const valid = new Set(batchGroups.value.map((g) => g.name))
    const filtered = new Set([...expandedBatches.value].filter((n) => valid.has(n)))
    if (filtered.size !== expandedBatches.value.size) {
      expandedBatches.value = filtered
    }
  } catch {
    batchDirs.value = []
  }
}

async function importDir(dir: BatchDirInfo) {
  importingDir.value = dir.name
  try {
    await datafilesApi.importBatchDir(dir.name)
    ElMessage.success(`批次 "${dir.name}" 已导入`)
    await Promise.all([loadFiles(), loadBatchDirs()])
    filesStore.notifyFilesChanged()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '导入失败')
  } finally {
    importingDir.value = ''
  }
}

async function deleteDir(dir: BatchDirInfo) {
  try {
    await ElMessageBox.confirm(
      `确定删除目录 "${dir.name}" 及其 ${dir.file_count} 个文件吗？此操作不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await datafilesApi.deleteBatchDir(dir.name)
    ElMessage.success(`目录 "${dir.name}" 已删除`)
    await Promise.all([loadFiles(), loadBatchDirs()])
    filesStore.notifyFilesChanged()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e?.response?.data?.error || '删除失败')
    }
  }
}

async function deleteBatch(group: { name: string; files: any[] }) {
  try {
    await ElMessageBox.confirm(
      `确定删除批次 "${group.name}" 及其 ${group.files.length} 个文件吗？此操作不可恢复。`,
      '确认删除批次',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    // 调用 deleteBatchDir API，一次性删除目录和所有数据库记录
    await datafilesApi.deleteBatchDir(group.name)
    ElMessage.success(`批次 "${group.name}" 已删除`)
    await Promise.all([loadFiles(), loadBatchDirs()])
    filesStore.notifyFilesChanged()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e?.response?.data?.error || '删除失败')
    }
  }
}

// Data consistency check
async function runConsistencyCheck() {
  checkingConsistency.value = true
  confirmDeleteOrphanedDb.value = false
  confirmDeleteOrphanedDisk.value = false
  try {
    const { data } = await datafilesApi.checkConsistency()
    consistencyResult.value = data
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '检查失败')
  } finally {
    checkingConsistency.value = false
  }
}

async function fixConsistency(action: 'delete_orphaned_db' | 'delete_orphaned_disk') {
  const actionLabel = action === 'delete_orphaned_db' ? '孤立数据库记录' : '孤立磁盘文件'
  try {
    fixing.value = true
    const { data } = await datafilesApi.fixConsistency(action)
    ElMessage.success(`已删除 ${data.deleted_count} 个${actionLabel}`)
    // 重置确认状态
    confirmDeleteOrphanedDb.value = false
    confirmDeleteOrphanedDisk.value = false
    // 重新检查
    await runConsistencyCheck()
    await Promise.all([loadFiles(), loadBatchDirs()])
    filesStore.notifyFilesChanged()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '修复失败')
  } finally {
    fixing.value = false
  }
}

// Upload
async function handleUpload(options: { file: File }) {
  uploadProgress.value = 0
  try {
    await datafilesApi.upload(options.file, (pct: number) => {
      uploadProgress.value = pct
    })
    ElMessage.success(`${options.file.name} 上传成功`)
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch {
    ElMessage.error(`${options.file.name} 上传失败`)
  } finally {
    uploadProgress.value = 0
  }
}

// Search and filter
function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    currentPage.value = 1
    loadFiles()
  }, 300)
}

function onFilterChange() {
  currentPage.value = 1
  loadFiles()
}

function onPageChange(page: number) {
  currentPage.value = page
  loadFiles()
}

function onSelectionChange(rows: any[]) {
  selectedRows.value = rows
  selectedIds.value = rows.map((r) => r.id)
}

// Delete operations
async function deleteFile(row: any) {
  try {
    await ElMessageBox.confirm(
      `确定删除文件 "${row.filename}" 吗？此操作不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await datafilesApi.remove(row.id)
    ElMessage.success('文件已删除')
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败')
    }
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
    selectedRows.value = []
    selectedIds.value = []
    if (files.value.length === ids.length && currentPage.value > 1) {
      currentPage.value -= 1
    }
    await loadFiles()
    filesStore.notifyFilesChanged()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('批量删除失败')
  }
}

// Tag management
function startAddTag(row: any) {
  editingId.value = row.id
  newTagValue.value = ''
  nextTick(() => {
    const el = (tagInputRef.value as any)?.$el ?? tagInputRef.value
    if (el && typeof el.focus === 'function') el.focus()
  })
}

let blurTimer: ReturnType<typeof setTimeout> | null = null
function scheduleBlurCommit(row: any) {
  if (blurTimer) clearTimeout(blurTimer)
  blurTimer = setTimeout(() => {
    blurTimer = null
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

async function commitNewTag(row: any) {
  const t = newTagValue.value.trim()
  if (!t) {
    editingId.value = null
    newTagValue.value = ''
    return
  }
  const current = Array.isArray(row.tags) ? row.tags : []
  if (current.some((x: string) => x.toLowerCase() === t.toLowerCase())) {
    ElMessage.warning(`标签「${t}」已存在`)
    editingId.value = null
    newTagValue.value = ''
    return
  }
  const next = [...current, t]
  try {
    const { data } = await datafilesApi.setTags(row.id, next)
    row.tags = data.tags
    ElMessage.success(`已添加标签「${t}」`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.tags?.[0] || '标签更新失败')
  } finally {
    editingId.value = null
    newTagValue.value = ''
  }
}

async function removeTag(row: any, tag: string) {
  const current = Array.isArray(row.tags) ? row.tags : []
  const next = current.filter((x: string) => x.toLowerCase() !== tag.toLowerCase())
  if (next.length === current.length) return
  try {
    const { data } = await datafilesApi.setTags(row.id, next)
    row.tags = data.tags
    ElMessage.success(`已移除标签「${tag}」`)
  } catch {
    ElMessage.error('标签移除失败')
  }
}

// Utility
function formatTime(val: string) {
  if (!val) return ''
  return new Date(val).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function formatSize(val: number) {
  if (!val) return '--'
  if (val < 1024) return val + ' B'
  if (val < 1024 * 1024) return (val / 1024).toFixed(1) + ' KB'
  return (val / 1024 / 1024).toFixed(1) + ' MB'
}

function viewFile(row: any) {
  emit('view-file', row.id, row.filename)
}

function onRowClick(row: any) {
  emit('row-click', row.id, row.filename)
}

function tableRowClassName({ rowIndex }: { rowIndex: number }) {
  return rowIndex % 2 === 0 ? 'row-even' : 'row-odd'
}

// External operations (SFTP import/upload/delete) refresh list + product
// filter. loadProductCodes() MUST be here too — previously the "全部产品"
// dropdown only loaded on mount, so a freshly-uploaded file's product code
// showed in the table but the filter dropdown stayed empty ("no data").
watch(() => filesStore.filesVersion, () => {
  loadFiles()
  loadBatchDirs()
  loadProductCodes()
})

onMounted(() => {
  loadFiles()
  loadProductCodes()
  loadBatchDirs()
})

defineExpose({ reload: loadFiles })
</script>

<style scoped>
.list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.section-count {
  font-size: 12px;
  color: var(--text-tertiary);
  padding: 2px 8px;
  background: var(--bg-secondary);
  border-radius: 10px;
}

.search-input {
  width: 220px;
}

.product-filter {
  width: 160px;
}

.empty-text {
  color: var(--text-tertiary);
}

.list-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

/* ============================
   Upload Section
   ============================ */
.upload-section {
  margin-bottom: 16px;
  padding: 16px;
  background: var(--bg-secondary);
  border: 1px dashed var(--border-default);
  border-radius: 10px;
}

.upload-text {
  font-size: 14px;
  color: var(--text-secondary);
  margin-top: 8px;
}

.upload-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 4px;
}

/* ============================
   Batch Section
   ============================ */
.batch-section {
  margin-bottom: 16px;
}

.section-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 12px;
}

.batch-group {
  margin-bottom: 12px;
  padding: 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-radius: 10px;
}

.batch-group.unregistered {
  border-left: 3px solid var(--color-warning);
}

.batch-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.batch-header-clickable {
  cursor: pointer;
  user-select: none;
  padding: 4px 6px;
  margin-left: -6px;
  margin-right: -6px;
  border-radius: 6px;
  transition: background-color 0.15s ease;
}

.batch-header-clickable:hover {
  background: var(--bg-primary);
}

.batch-header-clickable:focus-visible {
  outline: 2px solid var(--brand-primary);
  outline-offset: 2px;
}

.batch-chevron {
  font-size: 14px;
  color: var(--text-tertiary);
  transition: transform 0.2s ease, color 0.2s ease;
  flex-shrink: 0;
}

.batch-chevron-open {
  transform: rotate(90deg);
  color: var(--brand-primary);
}

.section-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.section-label-row .section-label {
  margin-bottom: 0;
}

.batch-toggle-all {
  font-size: 12px;
}

.batch-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.batch-count {
  font-size: 12px;
  color: var(--text-tertiary);
  padding: 2px 8px;
  background: var(--bg-primary);
  border-radius: 10px;
}

.batch-size {
  font-size: 12px;
  color: var(--text-tertiary);
  font-family: var(--font-mono);
}

.batch-files {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.batch-file-tag {
  cursor: pointer;
  transition: all 0.2s ease;
}

.batch-file-tag:hover {
  transform: translateY(-1px);
}

/* 子批次样式 */
.sub-batch-group {
  margin-bottom: 12px;
  padding: 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border-muted);
  border-radius: 8px;
}

.sub-batch-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.sub-batch-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}

.sub-batch-count {
  font-size: 11px;
  color: var(--text-tertiary);
  padding: 2px 6px;
  background: var(--bg-secondary);
  border-radius: 8px;
}

.sub-batch-files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* ============================
   Expand Row Detail
   ============================ */
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

/* ============================
   Table Styling
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

.mono {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-secondary);
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
:root[data-theme="night"] .section-count {
  background: rgba(255, 255, 255, 0.08);
}

:root[data-theme="night"] .size-badge {
  color: var(--color-info);
}

:root[data-theme="night"] .upload-section {
  border-color: rgba(255, 255, 255, 0.1);
}

:root[data-theme="night"] .batch-group {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.08);
}

:root[data-theme="night"] .batch-group.unregistered {
  border-left-color: var(--color-warning);
}

:root[data-theme="night"] .batch-header-clickable:hover {
  background: rgba(255, 255, 255, 0.05);
}

:root[data-theme="night"] .batch-chevron {
  color: rgba(255, 255, 255, 0.6);
}

:root[data-theme="night"] .batch-chevron-open {
  color: var(--brand-primary);
}
</style>
