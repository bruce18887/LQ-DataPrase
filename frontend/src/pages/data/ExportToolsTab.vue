<template>
  <div class="export-tools">
    <!-- File Correlation -->
    <FileCorrelationSection :files="files" />

    <!-- Batch Export -->
    <div class="batch-export-card">
      <!-- Header: title + file selector -->
      <div class="card-header">
        <div class="card-title-group">
          <span class="card-icon">📥</span>
          <span class="card-title">批量导出参数分布图</span>
        </div>
        <div class="file-selector">
          <el-select
            v-model="selectedFileId"
            placeholder="选择文件"
            filterable
            size="small"
            style="width: 300px"
            aria-label="选择数据文件"
          >
            <el-option v-for="f in files" :key="f.id" :label="f.filename" :value="f.id" />
          </el-select>
          <span v-if="selectedFileId && params.length" class="params-count">
            {{ params.length }} 个参数
          </span>
        </div>
      </div>

      <!-- Body -->
      <div class="card-body">
        <!-- Row 1: Chart config inline strip -->
        <div class="config-strip">
          <div class="strip-label">
            <span class="strip-icon">⚙️</span>
            <span>图表配置</span>
          </div>
          <div class="strip-controls">
            <el-checkbox-group :model-value="chartConfig" @change="onChartConfigChange" class="inline-checkboxes">
              <el-checkbox value="limit">Limit</el-checkbox>
              <el-checkbox value="s3">3σ</el-checkbox>
              <el-checkbox value="s4">4σ</el-checkbox>
              <el-checkbox value="s6">6σ</el-checkbox>
              <el-checkbox value="normal">正态分布</el-checkbox>
            </el-checkbox-group>
            <el-checkbox v-model="ignoreNoLimit" class="ignore-no-limit">忽略无Limit</el-checkbox>
            <div class="bar-width-group">
              <span class="bw-label">柱宽</span>
              <el-slider
                :model-value="barWidthPercent"
                :min="10"
                :max="100"
                :step="5"
                size="small"
                style="width: 120px"
                @change="onBarWidthChange"
              />
              <span class="bw-value">{{ barWidthPercent }}%</span>
            </div>
          </div>
        </div>

        <!-- Row 2: Parameter select -->
        <div class="param-row">
          <span class="row-label">选择参数</span>
          <el-select v-model="localParams" multiple placeholder="点击选择要导出的参数" collapse-tags collapse-tags-tooltip style="flex: 1" aria-label="选择导出参数">
            <el-option v-for="p in params" :key="p" :label="p" :value="p" />
          </el-select>
          <el-button size="small" @click="selectAll" :disabled="params.length === 0">全选</el-button>
          <el-button size="small" @click="clearAll" :disabled="localParams.length === 0">清空</el-button>
        </div>

        <!-- Row 3: Export actions -->
        <div class="action-row">
          <el-select v-model="localSigma" size="default" class="sigma-select" aria-label="选择Sigma范围">
            <el-option :value="3" label="3 Sigma" />
            <el-option :value="4" label="4 Sigma" />
            <el-option :value="6" label="6 Sigma" />
          </el-select>
          <el-button @click="onExportSigma" :loading="exporting">导出 Sigma Limit</el-button>
          <div class="action-spacer" />
          <el-button type="primary" @click="onExportBatch('xlsx')" :loading="exporting">
            📊 批量导出 Excel
          </el-button>
          <el-button @click="onExportBatch('pptx')" :loading="exporting">
            📽️ 批量导出 PPT
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import api from '../../api'
import { useExport } from '../analysis/composables/useExport'
import FileCorrelationSection from '../analysis/components/correlation/FileCorrelationSection.vue'
import { useAnalysisStore } from '../../stores/analysis'

const props = defineProps<{
  files: any[]
  fileId?: number | null
}>()

const analysisStore = useAnalysisStore()

const selectedFileId = ref<number | null>(props.fileId ?? null)
const params = ref<string[]>([])
const localParams = ref<string[]>([])
const localSigma = ref(3)
const chartConfig = ref<string[]>(analysisStore.chartConfig)
const barWidthPercent = ref(analysisStore.barWidthPercent)
const ignoreNoLimit = ref(analysisStore.ignoreNoLimit)

const { exporting, exportSigmaLimit, exportBatchCharts } = useExport(() => selectedFileId.value)

// Sync fileId from parent
watch(() => props.fileId, (id) => {
  if (id != null) selectedFileId.value = id
})

// Load params when file changes
watch(selectedFileId, async (fileId) => {
  if (!fileId) { params.value = []; localParams.value = []; return }
  try {
    const { data } = await api.post('/analysis/histogram/', { file_id: fileId, params: [] })
    params.value = Object.keys(data.results || {})
  } catch {
    params.value = []
  }
}, { immediate: true })

// Persist UI config to store
watch(chartConfig, (val) => { analysisStore.chartConfig = val }, { deep: true })
watch(barWidthPercent, (val) => { analysisStore.barWidthPercent = val })
watch(ignoreNoLimit, (val) => { analysisStore.ignoreNoLimit = val })

function selectAll() {
  localParams.value = [...params.value]
}

function clearAll() {
  localParams.value = []
}

function onChartConfigChange(val: string[]) {
  chartConfig.value = val
}

function onBarWidthChange(val: number) {
  barWidthPercent.value = val
}

function onExportSigma() {
  exportSigmaLimit(localSigma.value, { onlyValidLimits: ignoreNoLimit.value })
}

function onExportBatch(format: string) {
  exportBatchCharts(localParams.value, format, {
    chartConfig: chartConfig.value,
    barWidthPercent: barWidthPercent.value,
  })
}
</script>

<style scoped>
.export-tools {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ============================
   Batch Export Card
   ============================ */
.batch-export-card {
  background: var(--bg-primary);
  border: 1px solid var(--border-muted);
  border-radius: 12px;
  overflow: hidden;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border-muted);
}

.card-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.card-icon { font-size: 16px; }
.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.file-selector {
  display: flex;
  align-items: center;
  gap: 10px;
}

.params-count {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-info);
  padding: 2px 8px;
  background: var(--bg-primary);
  border: 1px solid var(--border-muted);
  border-radius: 10px;
  white-space: nowrap;
}

.card-body {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* ============================
   Config Strip (inline)
   ============================ */
.config-strip {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 14px;
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
  border-radius: 8px;
}

.strip-label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  white-space: nowrap;
  flex-shrink: 0;
}

.strip-icon { font-size: 13px; }

.strip-controls {
  display: flex;
  align-items: center;
  gap: 20px;
  flex: 1;
}

.inline-checkboxes {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: wrap;
}

.inline-checkboxes :deep(.el-checkbox) {
  margin-right: 0;
  height: 28px;
  padding: 0 8px;
}

.inline-checkboxes :deep(.el-checkbox__label) {
  font-size: 12px;
  padding-left: 3px;
}

.ignore-no-limit {
  margin-left: 4px;
  height: 28px;
}

.ignore-no-limit :deep(.el-checkbox__label) {
  font-size: 12px;
  padding-left: 3px;
}

.bar-width-group {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
  flex-shrink: 0;
}

.bw-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-tertiary);
}

.bw-value {
  font-size: 11px;
  font-weight: 700;
  color: var(--brand-primary);
  font-family: var(--font-mono);
  min-width: 30px;
  text-align: right;
}

/* ============================
   Param Row
   ============================ */
.param-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.row-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  white-space: nowrap;
  flex-shrink: 0;
}

/* ============================
   Action Row
   ============================ */
.action-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-top: 4px;
  border-top: 1px solid var(--border-muted);
}

.action-spacer {
  flex: 1;
}

.sigma-select {
  width: 120px;
}

/* Brand-themed checkboxes (与 GageSummary / BuyoffForm 一致) */
:deep(.el-checkbox) {
  --el-checkbox-checked-bg-color: var(--brand-primary);
  --el-checkbox-checked-input-border-color: var(--brand-primary);
  --el-checkbox-checked-icon-color: var(--text-inverse);
}

/* ============================
   Night Theme
   ============================ */
:root[data-theme="night"] .batch-export-card {
  background: rgba(255, 255, 255, 0.03);
  border-color: rgba(255, 255, 255, 0.08);
}

:root[data-theme="night"] .card-header {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.06);
}

:root[data-theme="night"] .params-count {
  background: rgba(255, 255, 255, 0.06);
  border-color: rgba(255, 255, 255, 0.1);
}

:root[data-theme="night"] .config-strip {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.06);
}

:root[data-theme="night"] .action-row {
  border-color: rgba(255, 255, 255, 0.06);
}
</style>
