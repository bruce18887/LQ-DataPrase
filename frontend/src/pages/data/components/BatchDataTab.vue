<template>
  <div class="batch-data-tab">
    <!-- 汇总条 -->
    <BatchSummaryBar
      v-if="batchDirs.length > 0"
      :batch-count="batchGroups.length"
      :file-count="totalFileCount"
      :total-size="totalByteSize"
      :pending-dirs="unregisteredDirs.length"
      @refresh="loadBatchDirs"
    />

    <!-- 批次搜索 -->
    <div v-if="batchDirs.length > 0" class="batch-search-bar">
      <el-input
        v-model="batchSearch"
        placeholder="按批次名称过滤…"
        clearable
        size="small"
        :data-testid="'batch-search'"
        style="width: 240px"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <span v-if="batchSearch" class="batch-search-hint">
        匹配 {{ filteredUnregisteredDirs.length + filteredBatchGroups.length }} 条
      </span>
    </div>

    <!-- Unregistered batch directories (from SFTP downloads) -->
    <template v-if="filteredUnregisteredDirs.length > 0">
      <div class="section-label">📂 SFTP 下载目录（未导入）</div>
      <UnregisteredDirCard
        v-for="dir in filteredUnregisteredDirs"
        :key="dir.name"
        :dir="dir"
        :importing="importingDir === dir.name"
        @import="importDir"
        @delete="deleteDir"
      />
    </template>

    <!-- Batch files grouped (registered) -->
    <template v-if="filteredBatchGroups.length > 0">
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
      <div v-for="group in filteredBatchGroups" :key="group.name" class="batch-group" :data-testid="`batch-group-${group.name}`">
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
          <span class="batch-size" :title="`总大小 ${formatSize(groupStats(group).totalSize)}`">
            {{ formatSize(groupStats(group).totalSize) }}
          </span>
          <span class="batch-size" :title="`总行数 ${groupStats(group).totalRows}`">
            {{ groupStats(group).totalRows }} 行
          </span>
          <span
            v-for="fmt in groupStats(group).formats"
            :key="fmt"
            class="batch-flag batch-flag-format"
          >{{ fmt }}</span>
          <span
            v-for="code in groupStats(group).products"
            :key="code"
            class="batch-flag batch-flag-product"
          >{{ code }}</span>
          <span
            v-for="stg in groupStats(group).stages"
            :key="stg"
            class="batch-flag batch-flag-stage"
          >{{ stg }}</span>
          <span v-if="group.subBatchNames.length > 0" class="batch-flag">{{ group.subBatchNames.length }} 个子批次</span>
          <div style="flex:1" />
          <el-dropdown
            v-if="group.subBatchNames.length > 0"
            trigger="click"
            @command="(sub: string) => deleteSubBatch(group.name, sub)"
          >
            <el-button size="small" type="danger" plain link @click.stop>
              删子批次<el-icon><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="sub in group.subBatchNames" :key="sub" :command="sub">
                  {{ sub }}（{{ groupFilesBySub(group, sub).length }} 个文件）
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button size="small" type="danger" plain @click.stop="deleteBatch(group)">
            <el-icon><Delete /></el-icon> 删除批次
          </el-button>
        </div>
        <el-collapse-transition>
          <div v-show="isBatchExpanded(group.name)" class="batch-files" :data-testid="`batch-files-${group.name}`">
            <div v-if="selectedIds[group.name]?.length" class="batch-selection-bar">
              <span>已选 {{ selectedIds[group.name].length }} 个文件</span>
              <el-button size="small" type="warning" plain @click="uncombineSelected(group)">
                <el-icon><Upload /></el-icon> 移出选中的 {{ selectedIds[group.name].length }} 个
              </el-button>
            </div>
            <BatchFilesTable
              :files="group.files"
              :active-file-id="activeFileId"
              @file-selected="emit('file-selected', $event)"
              @selection-change="(ids: number[]) => onBatchSelection(group.name, ids)"
              @remove-one="(row: any) => uncombineOne(group, row)"
            />
          </div>
        </el-collapse-transition>
      </div>
    </template>

    <el-empty
      v-if="batchDirs.length === 0"
      description="暂无批次数据 — 上传 ZIP 压缩包或在文件列表勾选单文件「组合为批次」会生成批次"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { Upload, Delete, Search, ArrowRight, ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { datafilesApi, type BatchDirInfo } from '../../../api/datafiles'
import { useFilesStore } from '../../../stores/files'
import { formatSize } from '../../../utils/format'
import { groupStats, groupFilesBySub, filterBatchGroups, type BatchGroup } from '../composables/useBatchGroupStats'
import BatchFilesTable from './BatchFilesTable.vue'
import BatchSummaryBar from './BatchSummaryBar.vue'
import UnregisteredDirCard from './UnregisteredDirCard.vue'

const props = defineProps<{
  activeFileId?: number
}>()

const emit = defineEmits<{
  'file-selected': [id: number]
  'total-change': [total: number]
}>()

const filesStore = useFilesStore()

const batchDirs = ref<BatchDirInfo[]>([])
const importingDir = ref('')
// 批次搜索（按名称过滤，注册/未注册一起过滤）
const batchSearch = ref('')
// 每个批次的勾选集合：{ batchName: [fileId...] }
const selectedIds = ref<Record<string, number[]>>({})
// 已导入批次默认折叠：单批次可能含 100+ 文件，全部展开会撑高页面。
const expandedBatches = ref<Set<string>>(new Set())

// ── 派生数据 ────────────────────────────────────────────────────────

const unregisteredDirs = computed(() => batchDirs.value.filter((d) => !d.registered))

const batchGroups = computed<BatchGroup[]>(() =>
  batchDirs.value.filter((d) => d.registered).map((d) => {
    const subs = new Set<string>()
    for (const f of d.files) {
      if (f.sub_batch) subs.add(f.sub_batch)
    }
    return { name: d.name, files: d.files, subBatchNames: [...subs].sort() }
  }),
)

const filteredBatchGroups = computed<BatchGroup[]>(() => filterBatchGroups(batchGroups, batchSearch.value))

const filteredUnregisteredDirs = computed(() => {
  const kw = batchSearch.value.trim().toLowerCase()
  if (!kw) return unregisteredDirs.value
  return unregisteredDirs.value.filter((d) => d.name.toLowerCase().includes(kw))
})

const totalFileCount = computed(() =>
  batchGroups.value.reduce((acc, g) => acc + g.files.length, 0),
)
const totalByteSize = computed(() =>
  batchDirs.value.reduce((acc, d) => acc + (d.total_size || 0), 0),
)

// ── 展开/折叠 ───────────────────────────────────────────────────────

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

// ── 数据加载 ────────────────────────────────────────────────────────

async function loadBatchDirs() {
  try {
    const { data } = await datafilesApi.listBatchDirs()
    batchDirs.value = Array.isArray(data) ? data : []
    emit('total-change', batchDirs.value.length)
    // 清理已不存在的批次（用户可能在别的 tab 删了批次）
    const valid = new Set(batchGroups.value.map((g) => g.name))
    const filtered = new Set([...expandedBatches.value].filter((n) => valid.has(n)))
    if (filtered.size !== expandedBatches.value.size) {
      expandedBatches.value = filtered
    }
    // 勾选集合同步清理
    const nextSel: Record<string, number[]> = {}
    for (const [name, ids] of Object.entries(selectedIds.value)) {
      if (valid.has(name)) nextSel[name] = ids
    }
    selectedIds.value = nextSel
  } catch {
    batchDirs.value = []
    emit('total-change', 0)
  }
}

// ── 导入/删除目录 ───────────────────────────────────────────────────

async function importDir(dir: BatchDirInfo) {
  importingDir.value = dir.name
  try {
    await datafilesApi.importBatchDir(dir.name)
    ElMessage.success(`批次 "${dir.name}" 已导入`)
    await loadBatchDirs()
    filesStore.notifyFilesChanged()
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  } finally {
    importingDir.value = ''
  }
}

async function deleteDir(dir: BatchDirInfo) {
  try {
    await ElMessageBox.confirm(
      `确定删除目录 "${dir.name}" 及其 ${dir.file_count} 个文件吗？此操作不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    await datafilesApi.deleteBatchDir(dir.name)
    ElMessage.success(`目录 "${dir.name}" 已删除`)
    await loadBatchDirs()
    filesStore.notifyFilesChanged()
  } catch {
    // ElMessageBox 取消 reject "cancel"；真实错误 toast 由拦截器弹出
  }
}

async function deleteBatch(group: { name: string; files: any[] }) {
  try {
    await ElMessageBox.confirm(
      `确定删除批次 "${group.name}" 及其 ${group.files.length} 个文件吗？此操作不可恢复。`,
      '确认删除批次',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    await datafilesApi.deleteBatchDir(group.name)
    ElMessage.success(`批次 "${group.name}" 已删除`)
    await loadBatchDirs()
    filesStore.notifyFilesChanged()
  } catch {
    // ElMessageBox 取消 reject "cancel"；真实错误 toast 由拦截器弹出
  }
}

async function deleteSubBatch(batchName: string, subBatchName: string) {
  try {
    await ElMessageBox.confirm(
      `确定删除子批次 "${subBatchName}" 及其文件吗？此操作不可恢复。`,
      '确认删除子批次',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    await datafilesApi.deleteSubBatch(batchName, subBatchName)
    ElMessage.success(`子批次 "${subBatchName}" 已删除`)
    await loadBatchDirs()
    filesStore.notifyFilesChanged()
  } catch {
    // ElMessageBox 取消 reject "cancel"；真实错误 toast 由拦截器弹出
  }
}

// ── 移出批次（还原为单文件） ────────────────────────────────────────

function onBatchSelection(batchName: string, ids: number[]) {
  selectedIds.value = { ...selectedIds.value, [batchName]: ids }
}

async function uncombine(paths: number[], batchName: string, count: number) {
  try {
    await ElMessageBox.confirm(
      `确定将 ${count} 个文件从批次 "${batchName}" 移出吗？文件将恢复为单文件。`,
      '移出批次',
      { confirmButtonText: '移出', cancelButtonText: '取消', type: 'warning' },
    )
    const { data } = await datafilesApi.uncombineFiles(paths)
    ElMessage.success(`已将 ${data.moved} 个文件移出批次 "${batchName}"`)
    selectedIds.value = { ...selectedIds.value, [batchName]: [] }
    await loadBatchDirs()
    filesStore.notifyFilesChanged()
  } catch {
    // ElMessageBox 取消 reject "cancel"；真实错误 toast 由拦截器弹出
  }
}

async function uncombineSelected(group: { name: string }) {
  await uncombine(selectedIds.value[group.name] ?? [], group.name, selectedIds.value[group.name]?.length ?? 0)
}

async function uncombineOne(group: { name: string }, row: any) {
  await uncombine([row.id], group.name, 1)
}

// ── 外部刷新 ────────────────────────────────────────────────────────

watch(() => filesStore.filesVersion, () => {
  loadBatchDirs()
})

onMounted(() => {
  loadBatchDirs()
})

defineExpose({ loadBatchDirs })
</script>

<style scoped>
.batch-data-tab {
  margin-bottom: 16px;
}

.section-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-2);
  margin-bottom: 12px;
}

.batch-group {
  margin-bottom: 12px;
  padding: 14px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 10px;
}

.batch-search-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.batch-search-hint {
  font-size: 12px;
  color: var(--text-3);
}

.batch-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
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
  background: var(--bg);
}

.batch-header-clickable:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
}

.batch-chevron {
  font-size: 14px;
  color: var(--text-3);
  transition: transform 0.2s ease, color 0.2s ease;
  flex-shrink: 0;
}

.batch-chevron-open {
  transform: rotate(90deg);
  color: var(--brand);
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
  color: var(--text);
}

.batch-count {
  font-size: 12px;
  color: var(--text-3);
  padding: 2px 8px;
  background: var(--bg);
  border-radius: 10px;
}

.batch-size {
  font-size: 12px;
  color: var(--text-3);
  font-family: var(--font-mono);
}

.batch-flag {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 9px;
  background: var(--bg);
  color: var(--text-3);
  border: 1px solid var(--border);
  white-space: nowrap;
}

.batch-flag.product {
  color: var(--info);
}

.batch-flag.format {
  color: var(--warn);
}

.batch-flag.stage {
  color: var(--brand);
  background: color-mix(in srgb, var(--brand) 10%, var(--bg));
}

.batch-files {
  /* 折叠/展开动画期间让内容不溢出 */
  overflow: hidden;
}

.batch-selection-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  margin-bottom: 8px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 12px;
  color: var(--text-2);
}

/* Night theme overrides */
:root[data-theme="night"] .batch-group {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.08);
}

:root[data-theme="night"] .batch-header-clickable:hover {
  background: rgba(255, 255, 255, 0.05);
}

:root[data-theme="night"] .batch-chevron {
  color: rgba(255, 255, 255, 0.6);
}

:root[data-theme="night"] .batch-chevron-open {
  color: var(--brand);
}

:root[data-theme="night"] .batch-flag {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.1);
}
</style>
