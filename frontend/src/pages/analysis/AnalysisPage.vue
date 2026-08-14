<template>
  <div>
    <h2>&#128200; 数据分析</h2>

    <el-form label-position="left" label-width="auto" class="analysis-file-selector" style="margin-bottom: 16px">
      <el-form-item label="选择数据文件">
        <FileSelect
          v-model="selectedFileId"
          :files="files"
          placeholder="选择数据文件"
          @change="onFileChange"
          class="analysis-file-selector__select"
        />
        <CircularProgress :loading="loading" />
      </el-form-item>
      <el-form-item label="异常值处理">
        <el-select
          v-model="outlierHandling"
          size="small"
          class="analysis-file-selector__select"
          style="width: 160px"
        >
          <el-option label="裁剪范围" value="clip" />
          <el-option label="不处理" value="off" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="outlierHandling !== 'off'" label="敏感度">
        <el-select
          v-model="iqrMultiplier"
          size="small"
          class="analysis-file-selector__select"
          style="width: 200px"
        >
          <el-option label="严格 (1.5x IQR)" :value="1.5" />
          <el-option label="宽松 (3.0x IQR)" :value="3.0" />
        </el-select>
        <span class="sensitivity-hint">
          {{ iqrMultiplier === 1.5 ? '标记轻微异常值' : '仅标记极端异常值' }}
        </span>
      </el-form-item>
    </el-form>

    <el-empty v-if="files.length === 0" description="请先在数据管理页面上传数据文件" />

    <el-tabs v-if="selectedFileId" v-model="activeTab" type="border-card">
      <!-- ========== 单参数分析 tab ========== -->
      <el-tab-pane label="&#128202; 单文件分析" name="single-param">
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
          :wafer-error="waferError"
          :file-id="selectedFileId ?? undefined"
          @load="loadWafer"
          @load-global="loadWaferGlobal"
        />
      </el-tab-pane>

      <!-- ========== 多文件分析 tab ========== -->
      <el-tab-pane label="&#128200; 多文件分析" name="multi-file">
        <MultiFileTab :files="files" />
      </el-tab-pane>

      <!-- ========== 相关性工具 tab ========== -->
      <el-tab-pane label="&#128279; 相关性对比" name="correlation-tools">
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
import { formatError } from '../../utils/error'
import { useAnalysisStore } from '../../stores/analysis'
import SingleParamTab from './components/SingleParamTab.vue'
import CircularProgress from '../../components/common/CircularProgress.vue'
import FileSelect from '../../components/common/FileSelect.vue'
import WaferMapPanel from './components/WaferMapPanel.vue'
import MultiFileTab from './components/MultiFileTab.vue'
import CorrelationToolsTab from './components/CorrelationToolsTab.vue'

const analysisStore = useAnalysisStore()

const files = ref<any[]>([])
const selectedFileId = ref<number | null>(analysisStore.selectedFileId)
const selectedParam = ref(analysisStore.selectedParam)
const params = ref<string[]>([])
const loading = ref(false)
const activeTab = ref(analysisStore.activeTab)
const outlierHandling = ref(analysisStore.outlierHandling)
watch(outlierHandling, (val) => { analysisStore.outlierHandling = val })
const iqrMultiplier = ref(analysisStore.iqrMultiplier)
watch(iqrMultiplier, (val) => { analysisStore.iqrMultiplier = val })

// Wafer state
const waferData = ref<any>(null)
const waferError = ref<string | null>(null)

// Track whether we've loaded params for the current file
const loadedFileId = ref<number | null>(null)

// keep-alive 组件首次挂载后 onActivated 也会触发一次。若它再次执行
// onFileChange，会把 onMounted 中按 jumpParam（仪表板跳转参数）选中的值
// 覆盖回 params[0]（第二次读取 store 时 jumpParam 已被清空）。首次挂载
// 完全由 onMounted 处理，onActivated 只在从缓存恢复时同步。
let firstActivated = true

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
  if (firstActivated) {
    // 首次挂载由 onMounted 处理，避免双 onFileChange 覆盖跳转参数。
    // 但 onMounted 时 loadFiles 可能静默失败（files 为空，选择流程未执行）：
    // 保留标志，下次恢复落入正常分支重跑完整选择流程（loadedFileId 为空 → onFileChange）
    if (files.value.length === 0) return
    firstActivated = false
    return
  }

  // 仪表板「测试项总览」跳转可能在本页 keep-alive 缓存期间改过 store，
  // setup 快照不会自动同步，需重新读 store 覆盖 ref
  if (analysisStore.selectedFileId) {
    selectedFileId.value = analysisStore.selectedFileId
  }

  // If selected file no longer exists (e.g. deleted), reset selection
  if (selectedFileId.value && !files.value.find(f => f.id === selectedFileId.value)) {
    selectedFileId.value = null
    loadedFileId.value = null
  }

  // Auto-select first file if nothing is selected
  if (!selectedFileId.value && files.value.length > 0) {
    selectedFileId.value = files.value[0].id
  }

  // Only reload params if file changed or params not loaded yet
  if (selectedFileId.value && selectedFileId.value !== loadedFileId.value) {
    await onFileChange()
  }

  // 同文件跳转时 onFileChange 被跳过，在此兜底选中 store 中的参数
  // （正常返回时 store 值 = 页面自身上次选择，幂等无害）
  if (analysisStore.selectedParam && params.value.includes(analysisStore.selectedParam)) {
    selectedParam.value = analysisStore.selectedParam
  }
})

async function loadFiles() {
  try {
    // 分页会静默截断文件列表（默认 PAGE_SIZE=20），下拉将选不到旧文件
    const { data } = await api.get('/files/', { params: { page_size: 9999 } })
    files.value = Array.isArray(data) ? data : data.results || []
  } catch {
    // silently fail
  }
}

// ========== Watch ==========
watch(selectedFileId, (val) => { analysisStore.selectedFileId = val })
watch(selectedParam, (val) => { analysisStore.selectedParam = val })
watch(activeTab, (val) => { analysisStore.activeTab = val })
watch([
  () => analysisStore.ignoreNoLimit,
  () => analysisStore.ignoreNoTestValue,
  () => analysisStore.dataOnlyBin1,
  () => analysisStore.onlyFailTestItem,
  () => analysisStore.onlyLowCpk,
  // 异常值检测敏感度影响低 CPK 判定（filtered CPK 口径），变化时刷新列表
  () => analysisStore.iqrMultiplier,
], () => { onFileChange() })

// ========== File change ==========
async function onFileChange() {
  if (!selectedFileId.value) return
  loading.value = true
  // 仪表板「测试项总览」跳转可能在 store 预置了目标参数，必须在清空前捕获
  const jumpParam = analysisStore.selectedParam
  // Reset stale state so the previous file's params (which may not exist
  // in the new file) don't linger. Without this, a `R_Kelvin_AGND` selected
  // on `gage_m_S4.csv` would still be sent to /analysis/{qqplot,histogram}/
  // and /statistics/boxplot/ after switching to an ETS88 file that has no
  // such column — causing simultaneous 400 (qqplot/boxplot: param_not_found
  // / no_valid_params) and 500 (histogram: KeyError) responses.
  params.value = []
  selectedParam.value = ''
  waferError.value = null
  waferData.value = null
  // Also clear the persisted store value so a remount of the page
  // (e.g. navigating away and back) does not restore the stale param.
  analysisStore.selectedParam = ''
  try {
    const { data } = await api.post('/analysis/histogram/', {
      file_id: selectedFileId.value,
      ignore_no_limit: analysisStore.ignoreNoLimit,
      ignore_no_test_value: analysisStore.ignoreNoTestValue,
      data_only_bin1: analysisStore.dataOnlyBin1,
      only_fail_test_item: analysisStore.onlyFailTestItem,
      only_low_cpk: analysisStore.onlyLowCpk,
      iqr_multiplier: analysisStore.iqrMultiplier,
    })
    // 过期文件响应守卫：挂载时自动加载的第一个文件与用户手动选择并发时，
    // 旧文件的慢响应（后到）不得用它自己的参数列表覆盖新文件的列表——
    // 否则 selectedParam 会指向旧文件参数（如 BZJ 的 Part_No），后续
    // boxplot/site_stats 等请求对该参数 400/500（参数不在新文件里）。
    if (data.file_id !== selectedFileId.value) return
    const results = data.results as Record<string, any>
    // Some parsers (e.g. CTA8280F trailing comma) yield an unnamed column whose
    // empty string name flows through numeric_cols. Drop blanks so the param
    // selector never offers a 400-bound empty option that breaks the QQ plot
    // and other endpoints doing `if param not in df.columns`.
    params.value = Object.keys(results || {}).filter((p) => p && p.trim() !== '')
    if (params.value.length > 0) {
      // 跳转的 param 若存在于新文件则优先选中，否则回退首个参数（自愈）
      selectedParam.value = (jumpParam && params.value.includes(jumpParam))
        ? jumpParam
        : params.value[0]
    }
    // Mark this file as loaded so onActivated won't reload unnecessarily
    loadedFileId.value = selectedFileId.value
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出（ERROR_CODE_MAP 覆盖机器码文案）
  } finally {
    loading.value = false
  }
}

// ========== Wafer ==========
// 晶圆图错误提示：缺坐标列等 400 由 axios 抛错进入 catch，不再静默空白
async function loadWafer(param: string, colorBy: string) {
  if (!selectedFileId.value) return
  loading.value = true
  try {
    const payload: any = { file_id: selectedFileId.value, color_by: colorBy }
    if (param) payload.param = param
    const { data } = await api.post('/analysis/wafer_map/', payload)
    if (data.error) {
      // 防御旧后端 200 错误载荷
      waferError.value = formatError({ response: { data } })
    } else {
      waferData.value = data
      waferError.value = null
    }
  } catch (e) {
    waferError.value = formatError(e)
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
    if (data.error) {
      // 防御旧后端 200 错误载荷
      waferError.value = formatError({ response: { data } })
    } else {
      waferData.value = data
      waferError.value = null
    }
  } catch (e) {
    waferError.value = formatError(e)
  } finally {
    loading.value = false
  }
}

</script>

<style scoped>

/* ===== 文件选择器（label 与 input 同一行） ===== */
.analysis-file-selector {
  align-items: center;
}
.analysis-file-selector :deep(.el-form-item) {
  display: flex;
  align-items: center;
  margin-bottom: 0;
  flex-wrap: wrap;
  gap: 12px;
}
.analysis-file-selector :deep(.el-form-item__label) {
  white-space: nowrap;
  color: var(--text-secondary);
  font-weight: 500;
}
.analysis-file-selector :deep(.el-form-item__content) {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
  min-width: 0;
}
.analysis-file-selector__select {
  width: 360px;
  max-width: 100%;
}

.sensitivity-hint {
  margin-left: 8px;
  font-size: 12px;
  color: var(--text-tertiary);
}
@media (max-width: 720px) {
  .analysis-file-selector__select {
    width: 100%;
  }
}

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
