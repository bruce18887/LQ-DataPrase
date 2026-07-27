<template>
  <div v-if="unregisteredDirs.length > 0 || batchGroups.length > 0" class="batch-section">
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
                  <div style="flex:1" />
                  <el-button
                    size="small"
                    type="danger"
                    plain
                    @click.stop="deleteSubBatch(group.name, sub.name, sub.files)"
                  >
                    <el-icon><Delete /></el-icon> 删除子批次
                  </el-button>
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

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Upload, Delete, ArrowRight, ArrowDown, ArrowUp } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { datafilesApi, type BatchDirInfo } from '../../../api/datafiles'
import { useFilesStore } from '../../../stores/files'
import { formatSize } from '../../../utils/format'

const props = defineProps<{
  activeFileId?: number
}>()

const emit = defineEmits<{
  'file-selected': [id: number]
  'data-changed': []
}>()

const filesStore = useFilesStore()

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

const unregisteredDirs = computed(() => batchDirs.value.filter((d) => !d.registered))

// 已导入批次直接来自 batch-dirs（磁盘走查，返回全部批次），不再依赖分页 files —
// 否则新下载文件占满第 1 页后，旧批次被挤出列表而"消失"。
// 支持子批次：按 sub_batch 字段分组显示
const batchGroups = computed(() => {
  const registered = batchDirs.value.filter((d) => d.registered)
  return registered.map((d) => {
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
    await loadBatchDirs()
    filesStore.notifyFilesChanged()
    emit('data-changed')
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
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    await datafilesApi.deleteBatchDir(dir.name)
    ElMessage.success(`目录 "${dir.name}" 已删除`)
    await loadBatchDirs()
    filesStore.notifyFilesChanged()
    emit('data-changed')
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
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    await datafilesApi.deleteBatchDir(group.name)
    ElMessage.success(`批次 "${group.name}" 已删除`)
    await loadBatchDirs()
    filesStore.notifyFilesChanged()
    emit('data-changed')
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e?.response?.data?.error || '删除失败')
    }
  }
}

async function deleteSubBatch(batchName: string, subBatchName: string, files: any[]) {
  try {
    await ElMessageBox.confirm(
      `确定删除子批次 "${subBatchName}" 及其 ${files.length} 个文件吗？此操作不可恢复。`,
      '确认删除子批次',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    await datafilesApi.deleteSubBatch(batchName, subBatchName)
    ElMessage.success(`子批次 "${subBatchName}" 已删除`)
    await loadBatchDirs()
    filesStore.notifyFilesChanged()
    emit('data-changed')
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e?.response?.data?.error || '删除失败')
    }
  }
}

onMounted(() => {
  loadBatchDirs()
})

defineExpose({ loadBatchDirs })
</script>

<style scoped>
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
  padding: 4px 0;
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

/* Night theme overrides */
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
