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
              <el-select
                v-model="slot.fileId"
                placeholder="选择文件"
                clearable
                aria-label="选择Gage文件"
                class="slot-select"
              >
                <el-option
                  v-for="f in availableFiles(slot.key)"
                  :key="f.id"
                  :label="f.filename"
                  :value="f.id"
                />
              </el-select>
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
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { datafilesApi } from '../../api/datafiles'
import { gageApi } from '../../api/gage'

interface SiteSlot {
  key: string
  label: string
  fileId: number | null
}

const files = ref<{ id: number; filename: string }[]>([])
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

const assignedSlots = computed(() => {
  return siteSlots.value
    .filter(slot => slot.fileId !== null)
    .map(slot => ({
      ...slot,
      fileName: files.value.find(f => f.id === slot.fileId)?.filename || '-',
    }))
})

const assignedFileIds = computed(() => {
  return siteSlots.value
    .map(slot => slot.fileId)
    .filter((id): id is number => id !== null)
})

function availableFiles(currentKey: string) {
  const usedIds = new Set<number>()
  for (const slot of siteSlots.value) {
    if (slot.key !== currentKey && slot.fileId !== null) {
      usedIds.add(slot.fileId)
    }
  }
  return files.value.filter(f => !usedIds.has(f.id))
}

onMounted(async () => {
  try {
    const { data } = await datafilesApi.list()
    files.value = Array.isArray(data) ? data : (data.results ?? [])
  } catch {
    // silently ignore fetch errors
  }
})

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
    const url = URL.createObjectURL(resp.data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'Gage_Summary.xlsx'
    a.click()
    URL.revokeObjectURL(url)
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
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-left: 3px solid var(--brand-primary);
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
  color: var(--text-primary);
  letter-spacing: -0.01em;
  background: linear-gradient(135deg, var(--brand-primary) 0%, var(--color-info) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.tab-subtitle {
  margin: 0;
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.5;
}

/* ================================================================
   Section Card（与 ExportToolsTab / FileCorrelationSection 一致）
   ================================================================ */
.section-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border-muted);
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
  color: var(--text-primary);
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
  background: var(--bg-primary);
  border: 1px solid var(--border-muted);
  border-radius: 10px;
  padding: 12px;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.slot-card:hover {
  border-color: var(--brand-primary);
  box-shadow: var(--shadow-indigo-focus);
}

.slot-card.slot-filled {
  border-color: var(--color-success);
  background: var(--color-success-bg);
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
  color: var(--brand-primary);
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
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
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
  --el-descriptions-item-bordered-label-background: var(--bg-tertiary);
}

:deep(.el-descriptions__label) {
  color: var(--text-primary);
  font-weight: 600;
}

:deep(.el-descriptions__content) {
  color: var(--text-primary);
}

:deep(.el-checkbox) {
  --el-checkbox-checked-bg-color: var(--brand-primary);
  --el-checkbox-checked-input-border-color: var(--brand-primary);
  --el-checkbox-checked-icon-color: var(--text-inverse);
}

:deep(.el-progress) {
  --el-color-success: var(--color-success);
}
</style>
