<template>
  <div class="gage-summary-page">
    <!-- 标题区 -->
    <header class="tab-header">
      <div class="tab-title-group">
        <span class="tab-title-icon" aria-hidden="true">📊</span>
        <h3 class="tab-title">Gage Summary 生成</h3>
      </div>
      <p class="tab-subtitle">为 8 个 Site 槽位分配文件，生成多 Site 统计对比报表</p>
    </header>

    <!-- Site 槽位分配 -->
    <section class="section-card">
      <div class="card-header">
        <div class="card-title-group">
          <span class="card-icon" aria-hidden="true">🔌</span>
          <span class="card-title">Site 槽位分配 (_S1 ~ _S8)</span>
        </div>
      </div>
      <div class="card-body">
        <el-row :gutter="12">
          <el-col :span="6" v-for="slot in siteSlots" :key="slot.key" class="slot-col">
            <div :class="['slot-card', { 'slot-filled': slot.fileId }]">
              <div class="slot-label-row">
                <span class="slot-label">{{ slot.label }}</span>
                <el-tag v-if="slot.fileId" size="small" type="success" class="slot-tag">已分配</el-tag>
              </div>
              <FileSelect
                v-model="slot.fileId"
                :files="availableFiles(slot.key)"
                placeholder="选择文件"
                clearable
                show-meta
                aria-label="选择Gage文件"
                class="slot-select"
              />
            </div>
          </el-col>
        </el-row>
      </div>
    </section>

    <!-- 已分配摘要 -->
    <section v-if="assignedSlots.length > 0" class="section-card">
      <div class="card-header">
        <div class="card-title-group">
          <span class="card-icon" aria-hidden="true">📋</span>
          <span class="card-title">已分配摘要</span>
        </div>
      </div>
      <div class="card-body">
        <el-descriptions :column="4" border>
          <el-descriptions-item
            v-for="slot in assignedSlots"
            :key="slot.key"
            :label="slot.label"
          >
            {{ slot.fileName }}
          </el-descriptions-item>
        </el-descriptions>
      </div>
    </section>

    <!-- 操作区 -->
    <div class="action-bar">
      <div class="action-options">
        <el-checkbox v-model="onlyBin1">只选择 Bin1 数据</el-checkbox>
        <el-checkbox v-model="ignoreNoLimit">忽略无 Limit 测试项</el-checkbox>
      </div>
      <div class="action-buttons">
        <el-button
          type="primary"
          :loading="loading"
          :disabled="assignedFileIds.length < 2"
          @click="generate"
        >
          📥 生成 Gage Summary
        </el-button>
      </div>
    </div>

    <!-- 进度条 -->
    <el-progress
      v-if="loading"
      :percentage="progress"
      :stroke-width="16"
      status="success"
      class="progress-bar"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { gageApi } from '../../api/gage'
import { downloadBlob, extractFilenameFromContentDisposition } from '../../utils/download'
import type { DataFile } from '../../types'
import FileSelect from '../../components/common/FileSelect.vue'

interface SiteSlot {
  key: string
  label: string
  fileId: number | null
}

interface Props {
  /** 文件列表（由 DataManagement 维护刷新后传入，组件不自行拉取） */
  files: DataFile[]
}

const props = withDefaults(defineProps<Props>(), { files: () => [] })

const onlyBin1 = ref(false)
const ignoreNoLimit = ref(false)
const loading = ref(false)
const progress = ref(0)

const siteSlots = ref<SiteSlot[]>([
  { key: 'S1', label: 'Site 1 (_S1)', fileId: null },
  { key: 'S2', label: 'Site 2 (_S2)', fileId: null },
  { key: 'S3', label: 'Site 3 (_S3)', fileId: null },
  { key: 'S4', label: 'Site 4 (_S4)', fileId: null },
  { key: 'S5', label: 'Site 5 (_S5)', fileId: null },
  { key: 'S6', label: 'Site 6 (_S6)', fileId: null },
  { key: 'S7', label: 'Site 7 (_S7)', fileId: null },
  { key: 'S8', label: 'Site 8 (_S8)', fileId: null },
])

// 数据库文件被删除后自动清理已失效的槽位分配（keep-alive 下组件常驻，
// 文件列表由父级刷新，这里负责把已不在列表中的 fileId 置空）
watch(() => props.files, (list) => {
  const ids = new Set(list.map(f => f.id))
  for (const slot of siteSlots.value) {
    if (slot.fileId !== null && !ids.has(slot.fileId)) {
      slot.fileId = null
    }
  }
})

const assignedSlots = computed(() => {
  return siteSlots.value
    .filter(slot => slot.fileId !== null)
    .map(slot => ({
      ...slot,
      fileName: props.files.find(f => f.id === slot.fileId)?.filename || '-',
    }))
})

const assignedFileIds = computed(() => {
  return siteSlots.value
    .map(slot => slot.fileId)
    .filter((id): id is number => id !== null)
})

/**
 * 当前槽位可选文件：排除其它槽位已占用；当前槽位已选文件即使被其它槽位
 * 占用也并回 options（否则 el-select 对不在 options 中的值显示裸 id 数字）。
 */
function availableFiles(currentKey: string) {
  const usedIds = new Set<number>()
  for (const slot of siteSlots.value) {
    if (slot.key !== currentKey && slot.fileId !== null) {
      usedIds.add(slot.fileId)
    }
  }
  const own = siteSlots.value.find((s) => s.key === currentKey)?.fileId
  if (own != null) usedIds.delete(own)
  return props.files.filter(f => !usedIds.has(f.id))
}

async function generate() {
  if (assignedFileIds.value.length < 2) {
    ElMessage.warning('请至少分配 2 个 Site 文件')
    return
  }
  loading.value = true
  progress.value = 0

  // Simulate progress
  const progressInterval = setInterval(() => {
    if (progress.value < 90) {
      progress.value += Math.random() * 15
    }
  }, 300)

  try {
    const resp = await gageApi.generateSummary(
      assignedFileIds.value,
      onlyBin1.value,
      ignoreNoLimit.value,
    )
    progress.value = 100
    const fname = extractFilenameFromContentDisposition(
      (resp.headers as Record<string, string>)?.['content-disposition'],
    ) ?? 'Gage_Summary.xlsx'
    downloadBlob(resp.data as Blob, fname)
    ElMessage.success('Gage Summary 已下载')
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  } finally {
    clearInterval(progressInterval)
    loading.value = false
    progress.value = 0
  }
}
</script>

<style scoped>
/* ================================================================
   容器
   ================================================================ */
.gage-summary-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ================================================================
   Tab 标题区（与 DataManagement 的 page-header 风格一致）
   ================================================================ */
.tab-header {
  position: relative;
  padding: 16px 20px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-left: 3px solid var(--brand);
  border-radius: 10px;
  box-shadow: var(--shadow-sm);
}

.tab-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.tab-title-icon {
  font-size: 18px;
  line-height: 1;
}

.tab-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: -0.01em;
  background: linear-gradient(135deg, var(--brand) 0%, var(--info) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.tab-subtitle {
  margin: 0;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.5;
}

/* ================================================================
   Section Card（与 ExportToolsTab / FileCorrelationSection 一致）
   ================================================================ */
.section-card {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: var(--bg-3);
  border-bottom: 1px solid var(--border);
}

.card-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-icon {
  font-size: 16px;
  line-height: 1;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

.card-body {
  padding: 16px 20px;
}

/* ================================================================
   Site 槽位卡片
   ================================================================ */
.slot-col {
  margin-bottom: 12px;
}

.slot-card {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.slot-card:hover {
  border-color: var(--brand);
  box-shadow: var(--shadow-indigo-focus);
}

.slot-card.slot-filled {
  border-color: var(--success);
  background: var(--success-bg);
}

.slot-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.slot-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--brand);
}

.slot-tag {
  margin-left: 4px;
}

.slot-select {
  width: 100%;
}

/* ================================================================
   操作区
   ================================================================ */
.action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 20px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: var(--shadow-sm);
  flex-wrap: wrap;
}

.action-options {
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
}

.action-buttons {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

/* ================================================================
   进度条
   ================================================================ */
.progress-bar {
  margin: 0 4px;
}

/* ================================================================
   Element Plus 主题适配
   ================================================================ */
:deep(.el-descriptions) {
  --el-descriptions-item-bordered-label-background: var(--bg-3);
}

:deep(.el-descriptions__label) {
  color: var(--text);
  font-weight: 600;
}

:deep(.el-descriptions__content) {
  color: var(--text);
}

:deep(.el-checkbox) {
  --el-checkbox-checked-bg-color: var(--brand);
  --el-checkbox-checked-input-border-color: var(--brand);
  --el-checkbox-checked-icon-color: var(--text-inverse);
}

:deep(.el-progress) {
  --el-color-success: var(--success);
}
</style>
