<template>
  <div class="multi-file-tab">
    <el-row :gutter="12" class="main-row">
      <!-- 左侧配置面板 -->
      <el-col :span="6" class="left-panel">
        <!-- 文件多选 -->
        <el-card shadow="hover" :body-style="{ padding: '12px' }">
          <label class="section-label" for="multi-file-select">数据文件 (最少 2 个)</label>
          <el-select
            id="multi-file-select"
            v-model="fileIds"
            multiple
            filterable
            collapse-tags
            collapse-tags-tooltip
            placeholder="选择数据文件"
            size="small"
            style="width: 100%"
            :virtual="files.length > 50"
          >
            <el-option v-for="f in files" :key="f.id" :label="f.filename" :value="f.id" />
          </el-select>

          <!-- 自定义图例名 -->
          <div v-if="selectedFileObjs.length" class="custom-names">
            <div class="section-label" style="margin-top: 10px">自定义图例名</div>
            <div v-for="f in selectedFileObjs" :key="f.id" class="name-row">
              <span class="name-dot" :style="{ background: colorOf(f.id) }" />
              <label :for="`file-name-${f.id}`" class="sr-only">{{ f.filename }} 图例名</label>
              <el-input
                :id="`file-name-${f.id}`"
                v-model="fileNames[f.id]"
                :placeholder="f.filename"
                size="small"
                clearable
              />
            </div>
          </div>
        </el-card>

        <ChartConfigPanel
          variant="multi-file"
          v-model:chart-config="chartConfig"
          v-model:bar-width-percent="barWidthPercent"
          v-model:ignore-no-limit="ignoreNoLimit"
          :range-type="'RDL'"
        />

        <!-- 范围类型 -->
        <el-card shadow="hover" :body-style="{ padding: '12px' }">
          <label class="section-label" for="multi-range-type">范围类型</label>
          <el-select id="multi-range-type" v-model="rangeType" size="small" style="width: 100%">
            <el-option label="Spec Limits (RDL)" value="RDL" />
            <el-option label="Data Range (DR)" value="DR" />
            <el-option label="3 Sigma (S3)" value="S3" />
            <el-option label="4 Sigma (S4)" value="S4" />
            <el-option label="6 Sigma (S6)" value="S6" />
          </el-select>
        </el-card>

        <!-- 当前测试项各文件统计 -->
        <el-card v-if="lotStats.length" shadow="hover" :body-style="{ padding: '8px' }">
          <div class="section-label">各文件统计</div>
          <el-table :data="lotStats" size="small" stripe>
            <el-table-column prop="name" label="文件" min-width="90" show-overflow-tooltip />
            <el-table-column prop="mean" label="Mean" width="78" />
            <el-table-column prop="std" label="STD" width="70" />
            <el-table-column prop="count" label="N" width="56" />
            <el-table-column label="Yield" width="68">
              <template #default="{ row }">{{ row.yield_pct }}%</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <!-- 右侧图表区 -->
      <el-col :span="18" class="right-panel" v-loading="loading" element-loading-text="正在分析数据...">
        <el-empty
          v-if="fileIds.length < 2"
          description="请至少选择 2 个数据文件"
        />
        <el-empty
          v-else-if="commonParams.length === 0 && !paramsLoading"
          description="所选文件没有共有测试项"
        />
        <template v-else>
          <div class="top-bar">
            <ParamSelector
              :params="commonParams"
              v-model:selected-param="selectedParam"
            />
            <div class="common-hint">共有测试项：{{ commonParams.length }} 项</div>
            <CircularProgress :loading="loading" />
          </div>
          <div class="chart-wrapper">
            <MultiFileChart
              v-if="lotData && lotData.lot_data && lotData.lot_data.length > 0"
              :lot-data="lotData"
              :chart-config="chartConfig"
              :bar-width-percent="barWidthPercent"
              :file-names="resolvedNames"
              :selected-param="selectedParam"
            />
            <el-empty
              v-else-if="lotData && selectedParam"
              :description="`${selectedParam} 暂无有效数据`"
              style="height: 100%; display: flex; align-items: center; justify-content: center;"
            />
          </div>
        </template>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { computed, watch, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useAnalysisStore } from '../../../stores/analysis'
import { useMultiFile } from '../composables/useMultiFile'
import ChartConfigPanel from './ChartConfigPanel.vue'
import ParamSelector from './ParamSelector.vue'
import MultiFileChart from './MultiFileChart.vue'
import CircularProgress from '../../../components/common/CircularProgress.vue'

const props = defineProps<{ files: any[] }>()

const analysisStore = useAnalysisStore()
const {
  multiFileIds: fileIds,
  multiSelectedParam: selectedParam,
  multiFileNames: fileNames,
  multiChartConfig: chartConfig,
  multiBarWidthPercent: barWidthPercent,
  multiIgnoreNoLimit: ignoreNoLimit,
  multiRangeType: rangeType,
} = storeToRefs(analysisStore)

const { loading, paramsLoading, commonParams, lotData, loadCommonParams, loadDistribution } = useMultiFile()

// 当前选中文件对象（保持下拉顺序）
const selectedFileObjs = computed(() =>
  fileIds.value
    .map((id) => props.files.find((f) => f.id === id))
    .filter(Boolean) as any[]
)

// file_id → 调色板颜色（与后端 colors 顺序一致）
const PALETTE = ['#0077BB', '#EE7733', '#009988', '#CC3311', '#33BBEE', '#EE3377', '#BBBBBB', '#648FFF']
function colorOf(fid: number): string {
  const idx = fileIds.value.indexOf(fid)
  return PALETTE[(idx < 0 ? 0 : idx) % PALETTE.length]
}

/**
 * 从多个文件名中自动提取差异部分作为图例名。
 * 找到公共前缀和公共后缀，截去后保留中间的差异子串。
 */
function autoExtractLabel(filenames: string[]): string[] {
  if (filenames.length <= 1) return filenames

  // Find common prefix
  let prefix = filenames[0]
  for (let i = 1; i < filenames.length; i++) {
    while (prefix.length > 0 && !filenames[i].startsWith(prefix)) {
      prefix = prefix.slice(0, -1)
    }
  }

  // Find common suffix
  let suffix = filenames[0]
  for (let i = 1; i < filenames.length; i++) {
    while (suffix.length > 0 && !filenames[i].endsWith(suffix)) {
      suffix = suffix.slice(1)
    }
  }

  return filenames.map(f => {
    let mid = f.slice(prefix.length)
    if (suffix.length) mid = mid.slice(0, -suffix.length)
    // Trim leading/trailing separators
    mid = mid.replace(/^[_\-. ]+|[_\-. ]+$/g, '')
    // Truncate at meaningful separator if too long
    if (mid.length > 30) {
      const sep = mid.search(/[_\-].{8,}/)
      if (sep > 0) mid = mid.slice(0, sep)
    }
    return mid || f  // fallback to full name if empty
  })
}

// 传给图表的最终图例名：自定义优先，否则自动提取差异部分
const resolvedNames = computed<Record<number, string>>(() => {
  const map: Record<number, string> = {}
  const customExists = selectedFileObjs.value.some(
    f => (fileNames.value[f.id] || '').trim(),
  )
  if (!customExists) {
    // Auto-extract: use differentiating parts as defaults
    const names = selectedFileObjs.value.map(f => f.filename)
    const labels = autoExtractLabel(names)
    // Deduplicate: append index suffix for duplicate labels
    const seen = new Map<string, number>()
    selectedFileObjs.value.forEach((f, i) => {
      let label = labels[i]
      const count = seen.get(label) ?? 0
      if (count > 0) label = `${label} (${count + 1})`
      seen.set(label, count + 1)
      map[f.id] = label
    })
  } else {
    const seen = new Map<string, number>()
    for (const f of selectedFileObjs.value) {
      const custom = (fileNames.value[f.id] || '').trim()
      let label = custom || f.filename
      const count = seen.get(label) ?? 0
      if (count > 0) label = `${label} (${count + 1})`
      seen.set(label, count + 1)
      map[f.id] = label
    }
  }
  return map
})

// 当前测试项各文件统计
const lotStats = computed(() => {
  const lots = lotData.value?.lot_data || []
  return lots.map((lot: any) => ({
    name: resolvedNames.value[lot.file_id] || lot.name,
    mean: lot.mean,
    std: lot.std,
    count: lot.count,
    yield_pct: lot.yield_pct,
  }))
})

async function reloadParams() {
  await loadCommonParams(fileIds.value, ignoreNoLimit.value)
  // 选中项失效时回退到第一项
  if (commonParams.value.length === 0) {
    selectedParam.value = ''
  } else if (!commonParams.value.includes(selectedParam.value)) {
    selectedParam.value = commonParams.value[0]
  } else {
    // 列表变了但当前项仍有效，主动刷新一次分布
    await loadDistribution(fileIds.value, selectedParam.value, rangeType.value)
  }
}

watch(fileIds, () => { reloadParams() }, { deep: true })
watch(ignoreNoLimit, () => { reloadParams() })
watch(rangeType, () => {
  if (selectedParam.value) loadDistribution(fileIds.value, selectedParam.value, rangeType.value)
})
watch(selectedParam, (p) => {
  if (p) loadDistribution(fileIds.value, p, rangeType.value)
  else lotData.value = null
})

onMounted(() => {
  analysisStore.initFromQuery()
  if (fileIds.value.length >= 2) reloadParams()
})
</script>

<style scoped>
.multi-file-tab {
  padding: 0;
}

.main-row {
  margin-bottom: 16px;
}

.left-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.right-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section-label {
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 4px;
  font-weight: 500;
}

.custom-names {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.name-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.name-dot {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
}

.name-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
}

.top-bar {
  display: flex;
  gap: 12px;
  align-items: center;
}

.top-bar > *:first-child {
  flex: 0 0 320px;
}

.common-hint {
  font-size: 12px;
  color: var(--text-secondary);
}

.chart-wrapper {
  flex: 1;
  min-height: 520px;
  background: var(--bg-secondary);
  border-radius: 6px;
  border: 1px solid var(--border-default);
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08), 0 4px 12px rgba(0, 0, 0, 0.04);
}

.chart-wrapper > * {
  height: 100%;
}
</style>
