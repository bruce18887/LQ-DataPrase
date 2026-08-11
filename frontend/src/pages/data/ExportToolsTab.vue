<template>
  <div class="export-tools">
    <div class="export-card">
      <div class="card-header">
        <div class="card-title-group">
          <span class="card-icon">📊</span>
          <span class="card-title">批量导出参数分布图</span>
        </div>
        <span v-if="currentFileName" class="current-file">当前文件：{{ currentFileName }}</span>
      </div>

      <div class="card-body">
        <ExportEmptyState v-if="!fileId" />

        <template v-else>
          <ExportParamSelector v-model="localParams" :params="params" />
          <ExportChartConfig
            v-model:chart-config="chartConfig"
            v-model:bar-width-percent="barWidthPercent"
            v-model:ignore-no-limit="ignoreNoLimit"
            v-model:native-chart="nativeChart"
          />
          <ExportActions
            v-model:sigma="localSigma"
            :exporting="exporting"
            :has-params="localParams.length > 0"
            @export-sigma="onExportSigma"
            @export-batch="onExportBatch"
          />
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../../api'
import { useExport } from '../analysis/composables/useExport'
import { useAnalysisStore } from '../../stores/analysis'
import ExportEmptyState from './components/export/ExportEmptyState.vue'
import ExportParamSelector from './components/export/ExportParamSelector.vue'
import ExportChartConfig from './components/export/ExportChartConfig.vue'
import ExportActions from './components/export/ExportActions.vue'

const props = defineProps<{
  files: any[]
  fileId?: number | null
}>()

const analysisStore = useAnalysisStore()

const params = ref<string[]>([])
const localParams = ref<string[]>([])
const localSigma = ref(3)
const chartConfig = ref<string[]>(analysisStore.chartConfig)
const barWidthPercent = ref(analysisStore.barWidthPercent)
const ignoreNoLimit = ref(analysisStore.ignoreNoLimit)
const nativeChart = ref(analysisStore.batchNativeChart)

const currentFileName = computed(() => {
  const f = props.files.find((item) => item.id === props.fileId)
  return f?.filename ?? ''
})

const { exporting, exportSigmaLimit, exportBatchCharts } = useExport(() => props.fileId ?? null)

// Load params when file changes
watch(() => props.fileId, async (fileId) => {
  localParams.value = []
  if (!fileId) { params.value = []; return }
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
watch(nativeChart, (val) => { analysisStore.batchNativeChart = val })

function onExportSigma() {
  // silent + 页面提示：保留超时/失败的定制文案，避免与拦截器全局提示重复
  exportSigmaLimit(localSigma.value, { onlyValidLimits: ignoreNoLimit.value }, { silent: true }).catch(() => {
    ElMessage.error('Sigma Limit 导出失败，请稍后重试')
  })
}

function onExportBatch(format: string) {
  const options = {
    show_limit: chartConfig.value.includes('limit'),
    show_3sigma: chartConfig.value.includes('s3'),
    show_4sigma: chartConfig.value.includes('s4'),
    show_6sigma: chartConfig.value.includes('s6'),
    show_normal: chartConfig.value.includes('normal'),
    show_kde: chartConfig.value.includes('kde'),
    native_chart: nativeChart.value,
  }
  exportBatchCharts(localParams.value, format, options, { silent: true }).catch((err: any) => {
    const msg = err?.code === 'ECONNABORTED' || err?.message?.includes('timeout')
      ? '导出超时，请减少参数数量后重试'
      : '批量导出失败，请稍后重试'
    ElMessage.error(msg)
  })
}
</script>

<style scoped>
.export-tools {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.export-card {
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

.current-file {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 320px;
}

.card-body {
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* Night theme overrides */
:root[data-theme="night"] .export-card {
  background: rgba(255, 255, 255, 0.03);
  border-color: rgba(255, 255, 255, 0.08);
}

:root[data-theme="night"] .card-header {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.06);
}
</style>
