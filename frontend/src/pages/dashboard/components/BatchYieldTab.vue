<template>
  <div class="batch-yield-tab">
    <!-- Batch selector -->
    <BatchSelectorBar
      :batches="batches"
      :selected-batch="selectedBatch"
      :loading="loading"
      :exporting="exporting"
      :has-data="!!batchData"
      @update:selectedBatch="onBatchSelect"
      @load="loadBatchData"
      @export="exportExcel"
    />

    <template v-if="batchData">
      <!-- 1. 阶段胶囊过滤条：点击即全局过滤（替代原分阶段良率表） -->
      <StageFilterBar
        :stages="batchData.stage_yields || []"
        :model-value="stageFilter"
        @update:modelValue="onStageFilter"
      />

      <!-- 2. QA 数量校验：紧凑单行条（替代原整卡表格），仅全部/FT 阶段可见 -->
      <QaValidationBar :checks="visibleQaChecks" />

      <!-- 3. 阶段汇总（总览条 + 树形：stage 聚合行 → 版本明细行） -->
      <el-card v-if="filteredStages.length" shadow="never" class="section-card">
        <template #header>📋 阶段汇总</template>
        <PhaseSummaryTree
          :stages="filteredStages"
          :phases="filteredSummary"
          :kpi="summaryKpi"
          :stage-filtered="!!stageFilter"
        />
      </el-card>

      <!-- 4. Yield Trend Combo Chart (Bar + Line)，随阶段过滤收窄 -->
      <el-card v-if="filteredPhases.length" shadow="never" class="section-card">
        <template #header>📈 良率趋势</template>
        <YieldTrendChart ref="yieldTrendChartRef" :phases="filteredPhases" />
      </el-card>

      <!-- 5. Phase Detail Table（默认展开，可手动收起；max-height 提升以多显示行） -->
      <CollapsibleSection title="📊 阶段明细表" default-open>
        <el-table :data="filteredPhases" stripe size="small" :border="true" max-height="560" :row-key="(row: any) => row.filename">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="phase-detail-expand">
                <div class="detail-row">
                  <span class="detail-label">完整文件名</span>
                  <span class="detail-value mono">{{ row.filename }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">测试程序</span>
                  <span class="detail-value">{{ row.program_name || '---' }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">Lot ID</span>
                  <span class="detail-value">{{ row.lot_id || '---' }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">开始时间</span>
                  <span class="detail-value">{{ row.start_time || '---' }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">结束时间</span>
                  <span class="detail-value">{{ row.end_time || '---' }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">操作员</span>
                  <span class="detail-value">{{ row.operator || '---' }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">工站</span>
                  <span class="detail-value">{{ row.station || '---' }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">Device</span>
                  <span class="detail-value">{{ row.device_name || '---' }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">Tester</span>
                  <span class="detail-value">{{ row.tester_type || '---' }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">总测试时间</span>
                  <span class="detail-value">{{ row.total_test_time || '---' }}</span>
                </div>
                <div class="detail-row">
                  <span class="detail-label">Handler</span>
                  <span class="detail-value">{{ row.handler || '---' }}</span>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="phase" label="阶段" width="80" fixed show-overflow-tooltip />
          <el-table-column label="WAFER_ID" width="100" align="center">
            <template #default="{row}">{{ row.wafer_id || '-' }}</template>
          </el-table-column>
          <el-table-column prop="program_name" label="程序名称" width="140" />
          <el-table-column prop="lot_id" label="Lot ID" width="120" />
          <el-table-column prop="total" label="测试总数" width="90" align="center" />
          <el-table-column prop="pass_count" label="Pass" width="80" align="center" />
          <el-table-column prop="fail_count" label="Fail" width="70" align="center">
            <template #default="{row}">
              <span :style="{ color: row.fail_count > 0 ? 'var(--color-error)' : 'var(--color-success)', fontWeight: 'bold' }">
                {{ row.fail_count }}
              </span>
            </template>
          </el-table-column>
          <el-table-column prop="yield_pct" label="良率" width="80" align="center">
            <template #default="{row}">
              <el-tag size="small" :type="row.yield_pct >= 95 ? 'success' : row.yield_pct >= 90 ? 'warning' : 'danger'">
                {{ row.yield_pct }}%
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="start_time" label="开始时间" width="170" />
          <el-table-column prop="end_time" label="结束时间" width="170" />
          <el-table-column prop="operator" label="操作员" width="100" />
          <el-table-column prop="station" label="工站" width="100" />
          <el-table-column prop="device_name" label="Device" width="140" />
          <el-table-column prop="tester_type" label="Tester" width="100" />
          <el-table-column prop="total_test_time" label="总测试时间" width="110" />
          <el-table-column prop="handler" label="Handler" width="100" />
        </el-table>
      </CollapsibleSection>

      <!-- 6. Site Yield Matrix（默认展开，可手动收起；min-width 弹性撑满 UI） -->
      <CollapsibleSection title="🏭 各 Site 良率矩阵" default-open>
        <el-table :data="filteredSiteMatrix" stripe size="small" :border="true" max-height="350">
          <el-table-column prop="phase" label="阶段" min-width="80" fixed show-overflow-tooltip />
          <template v-for="site in batchData.sorted_sites" :key="site">
            <el-table-column :label="`${site} 良率`" min-width="110" align="center">
              <template #default="{row}">
                <span :class="getYieldClass(row[`${site}_yield`])">{{ row[`${site}_yield`] }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="`${site} Pass/Total`" min-width="110" align="center">
              <template #default="{row}">{{ row[`${site}_ratio`] }}</template>
            </el-table-column>
          </template>
          <el-table-column label="All Site 良率" min-width="120" align="center" fixed="right">
            <template #default="{row}">
              <span :class="getYieldClass(row['all_yield'])">{{ row['all_yield'] }}</span>
            </template>
          </el-table-column>
          <el-table-column label="All Site Pass/Total" min-width="130" align="center" fixed="right">
            <template #default="{row}">{{ row['all_ratio'] }}</template>
          </el-table-column>
        </el-table>
      </CollapsibleSection>

      <!-- 7. Bin 分布（阶段下拉可选范围随阶段过滤收窄；卡内各表/图均按所选单阶段切换） -->
      <BatchBinSection
        ref="binSectionRef"
        :phases="filteredPhases"
        :sorted-sites="batchData.sorted_sites || []"
        :scope="stageFilter"
        :phase-count="filteredPhases.length"
      />
    </template>

    <el-empty v-else-if="!loading" description="选择批次并加载数据" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onActivated, onBeforeUnmount, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { batchApi } from '../../../api/batch'
import { useFilesStore } from '../../../stores/files'
import BatchSelectorBar from './batch/BatchSelectorBar.vue'
import StageFilterBar from './batch/StageFilterBar.vue'
import PhaseSummaryTree from './batch/PhaseSummaryTree.vue'
import YieldTrendChart from './batch/YieldTrendChart.vue'
import QaValidationBar from './batch/QaValidationBar.vue'
import BatchBinSection from './batch/BatchBinSection.vue'
import CollapsibleSection from '../../../components/common/CollapsibleSection.vue'

const batches = ref<any[]>([])
const selectedBatch = ref('')
const loading = ref(false)
const exporting = ref(false)
const batchData = ref<any>(null)
const stageFilter = ref('')

const filesStore = useFilesStore()

// Ref to child chart components
const yieldTrendChartRef = ref<InstanceType<typeof YieldTrendChart>>()
const binSectionRef = ref<InstanceType<typeof BatchBinSection>>()

// ── 阶段全局过滤：胶囊条点击 → 下方所有区块收窄到该 stage ──
const filteredStages = computed(() => {
  const stages = batchData.value?.stage_yields || []
  return stageFilter.value ? stages.filter((s: any) => s.stage === stageFilter.value) : stages
})

const filteredPhases = computed(() => {
  const phases = batchData.value?.phases || []
  return stageFilter.value ? phases.filter((p: any) => p.stage === stageFilter.value) : phases
})

const filteredSummary = computed(() => {
  const summary = batchData.value?.phase_summary || []
  return stageFilter.value ? summary.filter((s: any) => s.stage === stageFilter.value) : summary
})

const filteredSiteMatrix = computed(() => {
  const rows = batchData.value?.site_matrix || []
  return stageFilter.value ? rows.filter((r: any) => r.stage === stageFilter.value) : rows
})

// QA 校验属于 FT 阶段（QA ⊂ FT），过滤为全部或 FT 时可见
const visibleQaChecks = computed(() => {
  if (stageFilter.value && stageFilter.value !== 'FT') return []
  return batchData.value?.qa_checks || []
})

// 总览条：未过滤 → 批次整体 KPI；选中阶段 → 该阶段汇总值
const summaryKpi = computed(() => {
  const k = batchData.value?.kpi
  if (!k) return { input_total: 0, pass: 0, fail: 0, overall_yield: null }
  if (!stageFilter.value) {
    return {
      input_total: k.input_total ?? 0,
      pass: k.pass ?? 0,
      fail: k.fail ?? 0,
      overall_yield: k.overall_yield ?? null,
    }
  }
  const s = (batchData.value?.stage_yields || []).find((x: any) => x.stage === stageFilter.value)
  if (!s) return { input_total: 0, pass: 0, fail: 0, overall_yield: null }
  return {
    input_total: s.total,
    pass: s.pass_count,
    fail: s.fail_count,
    overall_yield: s.yield_pct,
  }
})

// ── Site / Bin×Site / UPH 已下沉为 Bin 分布卡内的「单阶段」口径 ──
//（由 BatchBinSection 从所选阶段现算，见 phaseSiteYieldRows/phaseBinSite/phaseUph）

function getYieldClass(val: string): string {
  if (!val || val === 'N/A') return ''
  const v = parseFloat(val)
  if (v >= 95) return 'yield-good'
  if (v >= 90) return 'yield-warn'
  return 'yield-bad'
}

function onStageFilter(v: string) {
  stageFilter.value = v
}

function onBatchSelect(val: string) {
  selectedBatch.value = val
  onBatchChange()
}

function onBatchChange() {
  batchData.value = null
  stageFilter.value = ''
}

async function loadBatches() {
  try {
    const { data } = await batchApi.listBatches()
    batches.value = data.batches || []
    // Reconcile: if the currently-selected batch was deleted, clear the view
    // so stale yield data doesn't linger after a delete/re-import.
    if (selectedBatch.value && !batches.value.some((b: any) => b.batch_name === selectedBatch.value)) {
      selectedBatch.value = ''
      onBatchChange()
    }
  } catch { /* ignore */ }
}

async function loadBatchData() {
  if (!selectedBatch.value) return
  loading.value = true
  try {
    const { data } = await batchApi.getBatchYieldData(selectedBatch.value)
    batchData.value = data
  } catch {
    // 错误 toast 由 axios 拦截器统一弹出
  } finally {
    loading.value = false
  }
}

async function exportExcel() {
  if (!batchData.value) return
  exporting.value = true
  try {
    // Get file IDs from the batch
    await batchApi.generateReport(
      batchData.value.phases.map((_: any, i: number) => i) // placeholder
    )
    ElMessage.info('导出功能开发中')
  } finally {
    exporting.value = false
  }
}

function handleResize() {
  yieldTrendChartRef.value?.handleResize()
  binSectionRef.value?.handleResize()
}

onMounted(() => {
  loadBatches()
  window.addEventListener('resize', handleResize)
})

// keep-alive 页面激活 / 文件变更（SFTP 下载、导入、删除）后刷新批次列表，
// 否则新下载的批次不会出现在选择器里（DashboardPage 被 keep-alive 缓存）。
onActivated(() => {
  loadBatches()
})
watch(() => filesStore.filesVersion, () => {
  loadBatches()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
})

defineExpose({ handleResize })
</script>

<style scoped>
.batch-yield-tab {
  padding: 0;
}

.section-card {
  margin-bottom: 16px;
  border-radius: 8px;
}

.yield-good { color: var(--color-success); font-weight: 600; }
.yield-warn { color: var(--color-warning); font-weight: 600; }
.yield-bad { color: var(--color-error); font-weight: 600; }

:deep(.el-card) {
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
}

:deep(.el-card__header) {
  background-color: var(--bg-tertiary);
  border-bottom: 1px solid var(--border-default);
  color: var(--text-primary);
  font-weight: 600;
  padding: 10px 16px;
}

:deep(.el-table) {
  --el-table-bg-color: var(--bg-secondary);
  --el-table-tr-bg-color: var(--bg-secondary);
  --el-table-header-bg-color: var(--bg-tertiary);
  --el-table-border-color: var(--border-default);
  --el-table-text-color: var(--text-primary);
  --el-table-header-text-color: var(--text-primary);
}

:deep(.el-table__body tr:hover > td) {
  background-color: var(--bg-tertiary) !important;
}

.phase-detail-expand {
  padding: 12px 20px;
  background-color: var(--bg-secondary);
}

.detail-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
  padding: 4px 0;
}

.detail-label {
  flex-shrink: 0;
  width: 96px;
  font-size: 12px;
  color: var(--text-secondary);
  text-align: right;
}

.detail-value {
  font-size: 13px;
  color: var(--text-primary);
  word-break: break-all;
}

.detail-value.mono {
  font-family: var(--font-mono);
  font-size: 12px;
}
</style>
