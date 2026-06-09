<template>
  <div>
    <h2>&#128200; 数据分析</h2>

    <el-row :gutter="16" style="margin-bottom: 16px" align="middle">
      <el-col :span="8">
        <el-select v-model="selectedFileId" placeholder="选择数据文件" @change="onFileChange" style="width: 100%">
          <el-option v-for="f in files" :key="f.id" :label="f.filename" :value="f.id" />
        </el-select>
      </el-col>
      <el-col :span="2">
        <CircularProgress :loading="loading" />
      </el-col>
    </el-row>

    <el-empty v-if="files.length === 0" description="请先在数据管理页面上传数据文件" />

    <el-tabs v-if="selectedFileId" v-model="activeTab" type="border-card">
      <!-- ========== 单参数分析 tab ========== -->
      <el-tab-pane label="&#128202; 单参数分析" name="single-param">
        <SingleParamTab
          :file-id="selectedFileId"
          :params="params"
          v-model:selected-param="selectedParam"
          :loading="loading"
        />
      </el-tab-pane>

      <!-- ========== 晶圆图 tab ========== -->
      <el-tab-pane label="&#128309; 晶圆图" name="wafer">
        <WaferMapPanel
          :params="params"
          :loading="loading"
          :wafer-data="waferData"
          :file-id="selectedFileId ?? undefined"
          @load="loadWafer"
          @load-global="loadWaferGlobal"
        />
      </el-tab-pane>

      <!-- ========== 箱线图 tab ========== -->
      <el-tab-pane label="&#128202; 箱线图" name="boxplot">
        <BoxPlotSection
          :file-id="selectedFileId"
          :available-params="params"
        />
      </el-tab-pane>

      <!-- ========== 多文件分析 tab ========== -->
      <el-tab-pane label="&#128200; 多文件分析" name="multi-file">
        <MultiFileTab :files="files" />
      </el-tab-pane>

      <!-- ========== 相关性工具 tab ========== -->
      <el-tab-pane label="&#128279; 相关性工具" name="correlation-tools">
        <CorrelationToolsTab
          :file-id="selectedFileId"
          :params="params"
        />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onActivated, watch } from 'vue'
import api from '../../api'
import { useAnalysisStore } from '../../stores/analysis'
import SingleParamTab from './components/SingleParamTab.vue'
import CircularProgress from '../../components/common/CircularProgress.vue'
import WaferMapPanel from './components/WaferMapPanel.vue'
import BoxPlotSection from './components/distribution/BoxPlotSection.vue'
import MultiFileTab from './components/MultiFileTab.vue'
import CorrelationToolsTab from './components/CorrelationToolsTab.vue'

const analysisStore = useAnalysisStore()

const files = ref<any[]>([])
const selectedFileId = ref<number | null>(analysisStore.selectedFileId)
const selectedParam = ref(analysisStore.selectedParam)
const params = ref<string[]>([])
const loading = ref(false)
const activeTab = ref(analysisStore.activeTab)

// Wafer state
const waferData = ref<any>(null)

// ========== Lifecycle ==========
onMounted(async () => {
  await loadFiles()
  // Auto-select first file if nothing is selected
  if (!selectedFileId.value && files.value.length > 0) {
    selectedFileId.value = files.value[0].id
  }
  if (selectedFileId.value) {
    await onFileChange()
  }
})

onActivated(async () => {
  await loadFiles()
  // Auto-select first file if nothing is selected
  if (!selectedFileId.value && files.value.length > 0) {
    selectedFileId.value = files.value[0].id
  }
  if (selectedFileId.value) {
    await onFileChange()
  }
})

async function loadFiles() {
  try {
    const { data } = await api.get('/files/')
    files.value = Array.isArray(data) ? data : data.results || []
  } catch {
    // silently fail
  }
}

// ========== Watch ==========
watch(selectedFileId, (val) => { analysisStore.selectedFileId = val })
watch(selectedParam, (val) => { analysisStore.selectedParam = val })
watch(activeTab, (val) => { analysisStore.activeTab = val })
watch(() => analysisStore.ignoreNoLimit, () => { onFileChange() })

// ========== File change ==========
async function onFileChange() {
  if (!selectedFileId.value) return
  loading.value = true
  try {
    const { data } = await api.post('/analysis/histogram/', {
      file_id: selectedFileId.value,
      ignore_no_limit: analysisStore.ignoreNoLimit,
    })
    const results = data.results as Record<string, any>
    // Some parsers (e.g. CTA8280F trailing comma) yield an unnamed column whose
    // empty string name flows through numeric_cols. Drop blanks so the param
    // selector never offers a 400-bound empty option that breaks the QQ plot
    // and other endpoints doing `if param not in df.columns`.
    params.value = Object.keys(results || {}).filter((p) => p && p.trim() !== '')
    if (params.value.length > 0 && (!selectedParam.value || !params.value.includes(selectedParam.value))) {
      selectedParam.value = params.value[0]
    }
  } catch {
    // silently fail
  } finally {
    loading.value = false
  }
}

// ========== Wafer ==========
async function loadWafer(param: string, colorBy: string) {
  if (!selectedFileId.value) return
  loading.value = true
  try {
    const payload: any = { file_id: selectedFileId.value, color_by: colorBy }
    if (param) payload.param = param
    const { data } = await api.post('/analysis/wafer_map/', payload)
    if (!data.error) waferData.value = data
  } catch {
    // silently fail
  } finally {
    loading.value = false
  }
}

async function loadWaferGlobal(colorBy: string) {
  if (!selectedFileId.value) return
  loading.value = true
  try {
    const { data } = await api.post('/analysis/wafer_map/', {
      file_id: selectedFileId.value,
      global_judgment: true,
      color_by: colorBy,
    })
    if (!data.error) waferData.value = data
  } catch {
    // silently fail
  } finally {
    loading.value = false
  }
}

</script>

<style scoped>
.param-select-dropdown .el-select-dropdown__list {
  max-height: 360px;
  overflow-y: auto;
}

.range-active-row {
  background-color: rgba(37, 99, 235, 0.08) !important;
  font-weight: bold;
  color: var(--color-error);
}

/* Element Plus 组件覆盖 */
:deep(.el-select) {
  --el-select-input-focus-border-color: var(--brand-primary);
}

:deep(.el-tabs--border-card) {
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.06);
}

:deep(.el-tabs--border-card > .el-tabs__header) {
  background-color: var(--bg-tertiary);
  border-bottom: 1px solid var(--border-default);
}

:deep(.el-tabs--border-card > .el-tabs__header .el-tabs__item) {
  color: var(--text-secondary);
  border-right: 1px solid var(--border-default);
}

:deep(.el-tabs--border-card > .el-tabs__header .el-tabs__item.is-active) {
  background-color: var(--bg-secondary);
  color: var(--brand-primary);
  font-weight: 600;
}

:deep(.el-tabs--border-card > .el-tabs__header .el-tabs__item:hover) {
  color: var(--brand-primary);
}

:deep(.el-empty) {
  --el-empty-description-color: var(--text-secondary);
}
</style>
