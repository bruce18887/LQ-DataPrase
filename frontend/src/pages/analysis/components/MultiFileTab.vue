<template>
  <div class="multi-file-tab">
    <el-row :gutter="12" class="main-row">
      <!-- 左侧配置面板 -->
      <el-col :span="6" class="left-panel">
        <!-- 文件多选（本 tab 自己的一份，与其他 tab 无关） -->
        <el-card shadow="hover" :body-style="{ padding: '12px' }">
          <AnalysisFilePicker
            v-model="fileIds"
            :files="files"
            scope="multi"
            multiple
            label="数据文件 (最少 2 个)"
            block
          />

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
          :bar-width-max="barWidthMax"
          :range-type="'RDL'"
        />

        <!-- 数据筛选：多文件图表不消费前端裁剪口径 → 不显示「异常值处理」，
             敏感度仅作为低 CPK 判定阈值透给 multi_lot -->
        <DataFilterSection
          scope="multi"
          v-model:ignore-no-limit="ignoreNoLimit"
          v-model:ignore-no-test-value="ignoreNoTestValue"
          v-model:data-only-bin1="dataOnlyBin1"
          v-model:only-fail-test-item="onlyFailTestItem"
          v-model:only-low-cpk="onlyLowCpk"
          v-model:iqr-multiplier="iqrMultiplier"
          :show-outlier="false"
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
        <ErrorBanner
          v-else-if="paramsError"
          :message="paramsError"
          title="共有测试项加载失败"
          @retry="reloadParams"
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
            <ErrorBanner
              v-else-if="distError"
              :message="distError"
              title="多文件分布加载失败"
              @retry="loadDistribution(fileIds, selectedParam, rangeType, multiFilters)"
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
import { computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { storeToRefs } from 'pinia'
import { useMultiTabStore } from '../../../stores/analysisTabs'
import { useMultiFile } from '../composables/useMultiFile'
import { getMaxBarWidthPercent, mapLotColorToTheme, SITE_COLORS_8_LIGHT } from '../../../utils/chart-bar'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import ChartConfigPanel from './ChartConfigPanel.vue'
import DataFilterSection from './DataFilterSection.vue'
import AnalysisFilePicker from './AnalysisFilePicker.vue'
import ParamSelector from './ParamSelector.vue'
import MultiFileChart from './MultiFileChart.vue'
import CircularProgress from '../../../components/common/CircularProgress.vue'
import ErrorBanner from '../../../components/common/ErrorBanner.vue'

const props = defineProps<{ files: any[] }>()

const multiStore = useMultiTabStore()
const {
  fileIds,
  selectedParam,
  fileNames,
  chartConfig,
  barWidthPercent,
  ignoreNoLimit,
  rangeType,
  ignoreNoTestValue,
  dataOnlyBin1,
  onlyFailTestItem,
  onlyLowCpk,
  iqrMultiplier,
} = storeToRefs(multiStore)

// 数据筛选开关载荷（5 开关 + 敏感度：后端 multi_lot 用 iqr 算低 CPK 候选集）
const multiFilters = computed(() => ({
  ignore_no_test_value: ignoreNoTestValue.value,
  data_only_bin1: dataOnlyBin1.value,
  only_fail_test_item: onlyFailTestItem.value,
  only_low_cpk: onlyLowCpk.value,
  iqr_multiplier: iqrMultiplier.value,
}))

const { loading, paramsLoading, paramsError, distError, commonParams, lotData, lotParam, loadCommonParams, loadDistribution } = useMultiFile()

// 柱宽 slider 上限：随文件数联动（N 系列并排柱组必须 ≤ bin 宽，否则贴限柱体
// 越过 USL 线——回归 limit-line-cross）
const barWidthMax = computed(() => {
  const n = lotData.value?.lot_data?.length ?? 0
  return getMaxBarWidthPercent(n > 1 ? n : 1)
})
// 文件数变化时把已超上限的柱宽 clamp（barWidthPercent 就是 store 的 ref，
// 写它即写 store）
watch(barWidthMax, (max) => {
  if (barWidthPercent.value > max) barWidthPercent.value = max
})

// 当前选中文件对象（保持下拉顺序）
const selectedFileObjs = computed(() =>
  fileIds.value
    .map((id) => props.files.find((f) => f.id === id))
    .filter(Boolean) as any[]
)

const { isDark } = useEChartsTheme()

/**
 * 图例名色点 = 后端 lot.color（事实来源）经主题映射——与 MultiFileChart 的
 * 柱/线颜色严格一致（此前本地 PALETTE 按选择顺序取色，与后端按 datasets
 * 字典序分配错位时色点≠柱色，2026-08-20 修复）；lotData 未含该文件时按
 * 选择顺序回退浅色板。
 */
function colorOf(fid: number): string {
  const lot = lotData.value?.lot_data?.find((l: any) => l.file_id === fid)
  if (lot?.color) return mapLotColorToTheme(lot.color, isDark.value)
  const idx = fileIds.value.indexOf(fid)
  return mapLotColorToTheme(
    SITE_COLORS_8_LIGHT[(idx < 0 ? 0 : idx) % SITE_COLORS_8_LIGHT.length],
    isDark.value,
  )
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
  // 合并请求：loadCommonParams 的响应已含首个公共参数的分布（lotParam 标记）。
  // 必须传当前 rangeType——后端合并分支无该参数时默认 S4，先切类型再选文件/
  // URL 恢复场景下初始图表会与下拉不一致（2026-08-13 回归）
  await loadCommonParams(fileIds.value, ignoreNoLimit.value, rangeType.value, multiFilters.value)
  // 选中项失效时回退到第一项
  if (commonParams.value.length === 0) {
    selectedParam.value = ''
  } else if (!commonParams.value.includes(selectedParam.value)) {
    selectedParam.value = commonParams.value[0]
    // watch(selectedParam) 触发时若 lotParam === 该参数则跳过（分布已随合并响应到达）
  } else if (lotParam.value !== selectedParam.value) {
    // 列表变了但当前项仍有效且分布未随合并响应到达，主动刷新一次
    await loadDistribution(fileIds.value, selectedParam.value, rangeType.value, multiFilters.value)
  }
}

// fileIds 多选过程中逐个勾选会触发多次 reload —— 150ms 防抖合并为一次
let fileDebounce: ReturnType<typeof setTimeout> | null = null
watch(fileIds, () => {
  if (fileDebounce) clearTimeout(fileDebounce)
  fileDebounce = setTimeout(() => { reloadParams() }, 150)
}, { deep: true })
// 本 tab 是 lazy 的 el-tab-pane，切走即销毁：watcher 会随组件作用域停止，
// 但已排期的 setTimeout 仍会在 150ms 内触发 reloadParams() → 对已卸载的
// tab 发幽灵请求（勾选文件后立即切 tab 就能复现）。
onBeforeUnmount(() => {
  if (fileDebounce) clearTimeout(fileDebounce)
  fileDebounce = null
})
watch(ignoreNoLimit, () => { reloadParams() })
// 数据筛选开关变化 → 重载公共参数列表（合并请求携带全部开关；敏感度只
// 影响低 CPK 候选集，但同样走这条合并请求）
watch([ignoreNoTestValue, dataOnlyBin1, onlyFailTestItem, onlyLowCpk, iqrMultiplier], () => { reloadParams() })
watch(rangeType, () => {
  // 范围类型变化总是需要按新 range_type 重算分布（合并请求用的是默认类型）
  if (selectedParam.value) loadDistribution(fileIds.value, selectedParam.value, rangeType.value, multiFilters.value)
})
watch(selectedParam, (p) => {
  if (p) {
    if (lotParam.value !== p) loadDistribution(fileIds.value, p, rangeType.value, multiFilters.value)
  } else lotData.value = null
})

onMounted(() => {
  multiStore.initFromQuery()
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
  color: var(--text-2);
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
  color: var(--text-2);
}

.chart-wrapper {
  flex: 1;
  min-height: 520px;
  background: var(--bg-2);
  border-radius: 6px;
  border: 1px solid var(--border-2);
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08), 0 4px 12px rgba(0, 0, 0, 0.04);
}

.chart-wrapper > * {
  height: 100%;
}
</style>
