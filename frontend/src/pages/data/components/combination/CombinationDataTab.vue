<template>
  <div class="combination-data-tab" data-testid="combination-upload">
    <header class="combination-page-header">
      <div class="combination-page-title">
        <span class="combination-eyebrow">COMBINATION DATA</span>
        <h2>组合数据</h2>
        <p>按组合整理文件，再用可选批次号区分来源批次。</p>
      </div>
      <div class="combination-scope-summary">
        <span class="combination-scope-label">当前范围</span>
        <strong
          v-if="activeCombination"
          class="combination-current-name"
          data-testid="combination-current-name"
        >{{ activeCombination.name }}</strong>
        <span v-else class="combination-current-name">未分组文件</span>
        <span class="combination-scope-count">{{ total }} 个文件</span>
      </div>
    </header>

    <CombinationToolbar
      :combinations="combinations"
      :active-id="activeId"
      @select="activeId = $event"
      @create="openCreate"
      @rename="openRename"
      @delete="removeActiveCombination"
    />

    <div class="combination-existing-action">
      <div class="combination-existing-copy">
        <strong>存量文件归组</strong>
        <span>从 {{ ungroupedFiles.length }} 个未分组文件中精确选择；批次号留空时保留原值。</span>
      </div>
      <el-button
        :disabled="ungroupedFiles.length === 0"
        data-testid="combination-existing"
        @click="openExistingAssignment"
      >存量归组（{{ ungroupedFiles.length }}）</el-button>
    </div>

    <FileUploadArea
      visible
      :active="props.active"
      :combinations="combinations"
      :combination-id="activeId"
      lock-combination
      @upload-success="handleUploadSuccess"
    />

    <div v-if="activeCombination && visibleFiles.length" class="combination-report-actions">
      <el-button
        data-testid="combination-open-gage"
        @click="openReport('gage')"
      >
        用当前组合打开 Gage 配置
      </el-button>
      <el-button
        data-testid="combination-open-buyoff"
        @click="openReport('buyoff')"
      >
        用当前组合打开 Buyoff 配置
      </el-button>
    </div>

    <section class="combination-files-panel" aria-label="组合文件">
      <CombinationFileGroups
        :files="visibleFiles"
        :combination-name="activeCombination?.name ?? null"
        :combination-id="activeId"
        :active-file-id="activeFileId"
        @file-selected="emit('file-selected', $event)"
        @remove-combination="unassignFile"
      />
    </section>

    <BatchDirectorySection
      :active-file-id="activeFileId"
      :combinations="combinations"
      @file-selected="emit('file-selected', $event)"
      @import-success="loadAll"
      @combination-created="addCreatedCombination"
    />

    <CombinationEditDialog
      v-model:visible="dialogVisible"
      :mode="dialogMode"
      :initial-name="activeCombination?.name"
      @submit="saveCombination"
    />

    <ExistingAssignmentDialog
      v-model:visible="importDialogVisible"
      :files="ungroupedFiles"
      :combinations="combinations"
      @submit="assignExistingFiles"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onActivated, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { combinationsApi } from '../../../../api/combinations'
import { datafilesApi } from '../../../../api/datafiles'
import { useFilesStore } from '../../../../stores/files'
import type { DataCombination, DataFile } from '../../../../types'
import FileUploadArea from '../FileUploadArea.vue'
import CombinationToolbar from './CombinationToolbar.vue'
import CombinationEditDialog from './CombinationEditDialog.vue'
import CombinationFileGroups from './CombinationFileGroups.vue'
import BatchDirectorySection from './BatchDirectorySection.vue'
import ExistingAssignmentDialog from './ExistingAssignmentDialog.vue'

const props = withDefaults(defineProps<{
  activeFileId?: number
  active?: boolean
}>(), {
  active: true,
})

const emit = defineEmits<{
  'file-selected': [id: number]
  'total-change': [total: number]
  'open-report': [payload: {
    kind: 'gage' | 'buyoff'
    combinationId: number | null
    combinationName: string | null
    fileIds: number[]
  }]
}>()

const filesStore = useFilesStore()
const combinations = ref<DataCombination[]>([])
const files = ref<DataFile[]>([])
const activeId = ref<number | null>(null)
const dialogMode = ref<'create' | 'rename'>('create')
const dialogVisible = ref(false)
const saving = ref(false)
const importDialogVisible = ref(false)
const assigningExisting = ref(false)

const activeCombination = computed(() =>
  combinations.value.find((combination) => combination.id === activeId.value) ?? null,
)
const ungroupedFiles = computed(() => files.value.filter(
  (file) => file.combination_id == null,
))
const visibleFiles = computed(() => files.value.filter(
  (file) => (file.combination_id ?? null) === activeId.value,
))
const total = computed(() => visibleFiles.value.length)

watch(total, (value) => emit('total-change', value), { immediate: true })
watch(() => props.active, (active) => {
  if (active) loadAll()
})

async function loadAll() {
  try {
    const [comboResp, fileResp] = await Promise.all([
      combinationsApi.list(),
      datafilesApi.listFiles({ page: 1, page_size: 100, include_hidden: 1, ordering: 'id' }),
    ])
    combinations.value = Array.isArray(comboResp.data) ? comboResp.data : []
    const firstBody = fileResp.data as DataFile[] | { results?: DataFile[]; next?: string | null }
    const loaded = Array.isArray(firstBody) ? [...firstBody] : [...(firstBody.results ?? [])]
    let next = Array.isArray(firstBody) ? null : (firstBody.next ?? null)
    while (next) {
      const response = await datafilesApi.listFiles({
        page: Number(new URL(next, window.location.origin).searchParams.get('page')) || undefined,
        page_size: 100, include_hidden: 1, ordering: 'id',
      })
      const body = response.data as { results?: DataFile[]; next?: string | null }
      loaded.push(...(body.results ?? []))
      next = body.next ?? null
    }
    files.value = loaded
    if (activeId.value != null && !combinations.value.some((item) => item.id === activeId.value)) {
      activeId.value = null
    }
  } catch {
    // 请求失败由 axios 统一管线提示；保留上一次成功数据，避免页面闪空。
  }
}

function openReport(kind: 'gage' | 'buyoff') {
  emit('open-report', {
    kind,
    combinationId: activeId.value,
    combinationName: activeCombination.value?.name ?? null,
    fileIds: visibleFiles.value.map(file => file.id),
  })
}

function addCreatedCombination(combination: DataCombination) {
  if (!combinations.value.some(item => item.id === combination.id)) {
    combinations.value = [...combinations.value, combination]
  }
}

function openCreate() {
  dialogMode.value = 'create'
  dialogVisible.value = true
}

function openRename() {
  if (!activeCombination.value) return
  dialogMode.value = 'rename'
  dialogVisible.value = true
}

async function saveCombination(name: string) {
  if (saving.value || !name) return
  saving.value = true
  try {
    if (dialogMode.value === 'create') {
      const { data } = await combinationsApi.create({ name })
      activeId.value = data.id
    } else if (activeCombination.value) {
      await combinationsApi.update(activeCombination.value.id, { name })
    }
    dialogVisible.value = false
    await loadAll()
  } catch {
    // 创建/重命名错误由 API 统一管线处理，对话框保留供用户修正。
  } finally {
    saving.value = false
  }
}

async function removeActiveCombination() {
  const current = activeCombination.value
  if (!current) return
  try {
    await ElMessageBox.confirm(
      `确定删除组合“${current.name}”吗？文件会保留并转为未分组文件。`,
      '删除组合',
      {
        confirmButtonText: '确认删除组合',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
    await combinationsApi.remove(current.id)
    activeId.value = null
    await loadAll()
    filesStore.notifyFilesChanged()
  } catch {
    // 取消删除与 API 错误分别由 MessageBox / axios 统一处理。
  }
}

async function handleUploadSuccess() {
  await loadAll()
  filesStore.notifyFilesChanged()
}

async function openExistingAssignment() {
  if (ungroupedFiles.value.length === 0) return
  await loadAll()
  if (ungroupedFiles.value.length > 0) importDialogVisible.value = true
}

async function assignExistingFiles(payload: {
  fileIds: number[]
  combinationId: number
  batchNo?: string
}) {
  if (assigningExisting.value || payload.fileIds.length === 0) return
  assigningExisting.value = true
  try {
    await datafilesApi.assignCombination({
      fileIds: payload.fileIds,
      combinationId: payload.combinationId,
      ...(payload.batchNo !== undefined ? { batchNo: payload.batchNo } : {}),
    })
    importDialogVisible.value = false
    ElMessage.success(`已将 ${payload.fileIds.length} 个未分组文件加入组合`)
    await loadAll()
    filesStore.notifyFilesChanged()
  } catch {
    // 请求失败由 axios 统一管线提示；保留弹窗与选择，便于用户重试。
  } finally {
    assigningExisting.value = false
  }
}

async function unassignFile(row: DataFile) {
  if (activeId.value == null) return
  try {
    await datafilesApi.assignCombination({
      fileIds: [row.id],
      combinationId: null,
    })
    await loadAll()
    filesStore.notifyFilesChanged()
  } catch {
    // 请求失败由 axios 统一管线提示；保留当前组合与文件列表。
  }
}

onMounted(loadAll)
onActivated(loadAll)
</script>

<style scoped>
.combination-data-tab {
  min-width: 0;
}

.combination-page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--p-space-5);
  margin-bottom: var(--p-space-4);
}

.combination-page-title {
  min-width: 0;
}

.combination-eyebrow {
  color: var(--brand);
  font-size: var(--p-fs-micro);
  font-weight: var(--p-fw-bold);
  letter-spacing: 0.12em;
}

.combination-page-title h2 {
  margin: var(--p-space-1) 0;
  color: var(--text);
  font-size: var(--p-fs-headline);
  font-weight: var(--p-fw-semibold);
}

.combination-page-title p,
.combination-scope-label,
.combination-scope-count {
  margin: 0;
  color: var(--text-2);
  font-size: var(--p-fs-dense);
}

.combination-scope-summary {
  display: grid;
  justify-items: end;
  gap: var(--p-space-1);
  min-width: 180px;
  padding: var(--p-space-3);
  border: 1px solid var(--border-2);
  border-radius: var(--p-radius-md);
  background: var(--bg-2);
}

.combination-current-name {
  max-width: 320px;
  color: var(--text);
  font-size: var(--p-fs-base);
  font-weight: var(--p-fw-semibold);
  overflow-wrap: anywhere;
}

.combination-existing-action {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--p-space-4);
  margin-top: var(--p-space-3);
  padding: var(--p-space-3) var(--p-space-4);
  border: 1px solid var(--border-2);
  border-radius: var(--p-radius-lg);
  background: var(--bg-2);
}

.combination-existing-copy {
  display: grid;
  gap: var(--p-space-1);
  min-width: 0;
}

.combination-existing-copy strong {
  color: var(--text);
  font-size: var(--p-fs-small);
  font-weight: var(--p-fw-semibold);
}

.combination-existing-copy span {
  color: var(--text-2);
  font-size: var(--p-fs-dense);
}

.combination-report-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--p-space-3);
  margin-top: var(--p-space-4);
}

.combination-files-panel {
  margin-top: var(--p-space-4);
  padding: var(--p-space-4);
  border: 1px solid var(--border-2);
  border-radius: var(--p-radius-lg);
  background: var(--bg-2);
}

@media (max-width: 760px) {
  .combination-page-header {
    flex-direction: column;
  }

  .combination-scope-summary {
    justify-items: start;
    width: 100%;
  }

  .combination-existing-action {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
