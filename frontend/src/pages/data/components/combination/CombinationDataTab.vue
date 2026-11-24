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

    <FileUploadArea visible :active="props.active" @upload-success="handleUploadSuccess" />

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
      @file-selected="emit('file-selected', $event)"
    />

    <CombinationEditDialog
      v-model:visible="dialogVisible"
      :mode="dialogMode"
      :initial-name="activeCombination?.name"
      @submit="saveCombination"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onActivated, onMounted, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { combinationsApi } from '../../../../api/combinations'
import { datafilesApi } from '../../../../api/datafiles'
import { useFilesStore } from '../../../../stores/files'
import type { DataCombination, DataFile } from '../../../../types'
import FileUploadArea from '../FileUploadArea.vue'
import CombinationToolbar from './CombinationToolbar.vue'
import CombinationEditDialog from './CombinationEditDialog.vue'
import CombinationFileGroups from './CombinationFileGroups.vue'
import BatchDirectorySection from './BatchDirectorySection.vue'

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

const activeCombination = computed(() =>
  combinations.value.find((combination) => combination.id === activeId.value) ?? null,
)
const visibleFiles = computed(() => files.value.filter(
  (file) => (file.combination_id ?? null) === activeId.value,
))
const total = computed(() => visibleFiles.value.length)

watch(total, (value) => emit('total-change', value), { immediate: true })

async function loadAll() {
  try {
    const [comboResp, fileResp] = await Promise.all([
      combinationsApi.list(),
      datafilesApi.listFiles({ page_size: 10000, include_hidden: 1 }),
    ])
    combinations.value = Array.isArray(comboResp.data) ? comboResp.data : []
    files.value = fileResp.data.results ?? fileResp.data
    if (activeId.value != null && !combinations.value.some((item) => item.id === activeId.value)) {
      activeId.value = null
    }
  } catch {
    // 请求失败由 axios 统一管线提示；保留上一次成功数据，避免页面闪空。
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
}
</style>
