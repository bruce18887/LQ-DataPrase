<template>
  <CollapsibleSection title="📋 Bin 分布" default-open @toggle="onBinSectionToggle">
    <!-- 7.1 Bin 分布（per-phase 表格 + Bin 饼图 + Top Fail Bin 柱图） -->
    <div class="bin-selector">
      <el-select v-model="selectedPhase" placeholder="选择阶段查看Bin分布" @change="onPhaseChange" style="width: 220px">
        <el-option v-for="p in phases" :key="phaseKey(p)" :label="phaseLabel(p)" :value="phaseKey(p)" />
      </el-select>
      <span class="bin-hint">本卡所有表格与图表均按所选单阶段切换显示</span>
      <!-- 当前范围：阶段过滤后下拉可选的文件范围（单阶段数据由所选阶段现算） -->
      <span class="bin-scope" :class="{ 'bin-scope--filtered': !!scope }">
        <el-icon class="bin-scope-icon"><Filter /></el-icon>
        当前范围：{{ scopeLabel }}
      </span>
    </div>

    <el-row :gutter="16">
      <!-- Left: per-phase bin table (2/5) -->
      <el-col :xs="24" :lg="9">
        <div class="chart-title">各阶段 Bin 明细（{{ selectedPhase || '-' }}）</div>
        <el-table
          v-if="selectedPhaseData"
          :data="selectedPhaseData.bin_info" stripe size="small" :border="true" max-height="640"
        >
          <el-table-column prop="name" label="Bin" width="80" />
          <el-table-column prop="value" label="数量" width="70" align="center" />
          <el-table-column prop="pct" label="占比" width="70" align="center" />
          <template v-for="site in sortedSites" :key="site">
            <el-table-column :label="site" width="80" align="center">
              <template #default="{row}">{{ row.sites?.[site] || 0 }}</template>
            </el-table-column>
          </template>
        </el-table>
        <el-empty v-else :image-size="60" description="无阶段数据" />
      </el-col>

      <!-- Right: charts (3/5) -->
      <el-col :xs="24" :lg="15">
        <div class="chart-title">阶段 Fail Bin（{{ selectedPhase || '-' }}）</div>
        <div ref="binPieRef" class="chart-container chart-sm" />
        <div class="chart-title" style="margin-top: 12px;">阶段 Top Fail Bin（{{ selectedPhase || '-' }}）</div>
        <div ref="binBarRef" class="chart-container chart-sm" />
      </el-col>
    </el-row>

    <!-- 7.2 Site 良率分布 & UPH 效率分析：与左侧 Bin 明细同口径，随阶段选择器按「单阶段（单文件）」切换；大屏并排，小屏堆叠 -->
    <el-divider class="bin-card-divider">
      <span class="bin-card-section-title">
        🟢 Site 良率分布 &amp; ⚡ UPH 效率分析
        <span class="bin-section-phase">（{{ selectedPhase || '-' }}）</span>
      </span>
    </el-divider>
    <el-row :gutter="16">
      <el-col :xs="24" :lg="14">
        <SiteYieldAnalysis
          ref="siteYieldRef"
          compact
          :site-yield-data="phaseSiteYieldRows"
          :overall-yield="phaseOverallYield"
        />
      </el-col>
      <el-col :xs="24" :lg="10">
        <UphCard v-if="phaseUph" embedded :uph-data="phaseUph" />
        <el-empty v-else :image-size="60" description="该阶段无 UPH 数据" class="bin-subpanel-empty" />
      </el-col>
    </el-row>

    <!-- 7.3 Bin × Site 交叉表 & 柱状图：同样按所选单阶段切换；列数随站点数增长，独占整行 -->
    <el-divider class="bin-card-divider">
      <span class="bin-card-section-title">
        📊 Bin &times; Site 交叉表 &amp; 柱状图
        <span class="bin-section-phase">（{{ selectedPhase || '-' }}）</span>
      </span>
    </el-divider>
    <BinSiteCrossTable
      v-if="phaseBinSite.bin_table_data.length"
      ref="binSiteRef"
      :bin-table-data="phaseBinSite.bin_table_data"
      :bin-site-columns="phaseBinSite.bin_site_columns"
    />
    <el-empty v-else :image-size="60" description="该阶段无 Bin × Site 数据" />
  </CollapsibleSection>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onActivated, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'
import { Filter } from '@element-plus/icons-vue'
import { getChartInitOpts, useEChartsTheme } from '../../../../utils/echarts-theme'
import { useThemeStore } from '../../../../stores/theme'
import { aggregateSiteYield, aggregateBinSiteTable } from '../../../../utils/batchAggregation'
import CollapsibleSection from '../../../../components/common/CollapsibleSection.vue'
import SiteYieldAnalysis from '../SiteYieldAnalysis.vue'
import BinSiteCrossTable from '../BinSiteCrossTable.vue'
import UphCard from '../UphCard.vue'

const props = defineProps<{
  /** 当前（可能按阶段过滤后的）phase 列表 */
  phases: any[]
  sortedSites: string[]
  /** 当前阶段过滤值（'' = 全部）；用于「当前范围」指示（阶段下拉的可选文件范围） */
  scope?: string
  /** 当前范围的 phase 数（指示用） */
  phaseCount?: number
}>()

const scopeLabel = computed(() => {
  if (!props.scope) return props.phaseCount != null ? `全部阶段（${props.phaseCount} 个文件）` : '全部阶段'
  return `${props.scope} 阶段（${props.phaseCount ?? 0} 个文件）`
})

const selectedPhase = ref('')
const binSectionOpen = ref(true) // Bin 分布卡默认展开，展开态用于过滤后重建内联图表

// Ref to child chart components
const siteYieldRef = ref<InstanceType<typeof SiteYieldAnalysis>>()
const binSiteRef = ref<InstanceType<typeof BinSiteCrossTable>>()

// ── 单阶段口径：Site 良率 / Bin×Site / UPH 与左侧 Bin 明细一致，
//    全部从「所选阶段（单个文件）」现算，随阶段选择器切换 ──
const phaseSiteYieldRows = computed(() => {
  if (!selectedPhaseData.value) return []
  return aggregateSiteYield([selectedPhaseData.value], props.sortedSites).map((r) => ({
    Site: r.site,
    Yield: r.yield,
    Total: r.total,
    PassCount: r.pass,
  }))
})

const phaseBinSite = computed(() => {
  if (!selectedPhaseData.value) return { bin_table_data: [] as Record<string, any>[], bin_site_columns: [] as string[] }
  return aggregateBinSiteTable([selectedPhaseData.value], props.sortedSites)
})

const phaseUph = computed(() => selectedPhaseData.value?.uph ?? null)

const phaseOverallYield = computed(() => Number(selectedPhaseData.value?.yield_pct) || 0)

// Chart refs for phase-scoped Bin analysis (remain inline)
const binPieRef = ref<HTMLElement>()
const binBarRef = ref<HTMLElement>()
let binPieChart: echarts.ECharts | null = null
let binBarChart: echarts.ECharts | null = null

const themeStore = useThemeStore()

const selectedPhaseData = computed(() => {
  if (!props.phases.length || !selectedPhase.value) return null
  return props.phases.find((p: any) => phaseKey(p) === selectedPhase.value) || null
})

function phaseKey(p: any): string {
  return p.wafer_id ? `${p.phase}-W${p.wafer_id}` : p.phase
}

function phaseLabel(p: any): string {
  return p.wafer_id ? `${p.phase}-W${p.wafer_id}` : p.phase
}

function onBinSectionToggle(open: boolean) {
  binSectionOpen.value = open
  // v-if 重挂载后容器是新的 DOM，旧实例绑定在 detached 节点上 → 销毁重建
  if (open) {
    disposeBinCharts()
    nextTick(() => renderInlineCharts())
  }
}

function disposeBinCharts() {
  if (binPieChart && !binPieChart.isDisposed()) { binPieChart.dispose(); binPieChart = null }
  if (binBarChart && !binBarChart.isDisposed()) { binBarChart.dispose(); binBarChart = null }
}

function onPhaseChange() {
  nextTick(() => {
    renderBinPieChart()
    renderBinBarChart()
  })
}

// 阶段过滤后选中的 Bin 阶段可能已不存在 → 回退到首个阶段并重建内联图表
watch(() => props.phases, () => {
  if (!selectedPhase.value || !props.phases.some((p: any) => phaseKey(p) === selectedPhase.value)) {
    selectedPhase.value = props.phases.length ? phaseKey(props.phases[0]) : ''
  }
  if (binSectionOpen.value) {
    disposeBinCharts()
    nextTick(() => renderInlineCharts())
  }
}, { deep: true, immediate: true })

function renderInlineCharts() {
  if (selectedPhaseData.value) {
    renderBinPieChart()
    renderBinBarChart()
  }
}

// Per-phase Bin pie chart (fail bins only)
function renderBinPieChart() {
  if (!binPieRef.value || !selectedPhaseData.value?.bin_info) return
  if (!binPieChart) binPieChart = echarts.init(binPieRef.value, undefined, getChartInitOpts())
  else binPieChart.clear()

  const failBins = selectedPhaseData.value.bin_info.filter(
    (b: any) => b.value > 0 && b.name !== '1' && !b.name.toLowerCase().includes('pass')
  )
  if (failBins.length === 0) return

  const palette = ['#f5576c', '#f9a825', '#4facfe', '#ff6b6b', '#74b9ff', '#fd79a8', '#e17055', '#00b894']
  // 注意：ECharts/zrender 不解析 CSS 变量，此处必须用主题实时色值（2026-08-26 修复）
  const tc = useEChartsTheme().colors.value.textColor
  binPieChart.setOption({
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', left: 'left', top: 'center', type: 'scroll', textStyle: { color: tc } },
    series: [{
      type: 'pie',
      radius: ['35%', '65%'],
      center: ['60%', '50%'],
      data: failBins,
      color: palette,
      label: { formatter: '{b}\n{d}%', color: tc },
      itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 },
    }],
  })
}

// Per-phase Bin horizontal bar chart (top 10 fail bins)
function renderBinBarChart() {
  if (!binBarRef.value || !selectedPhaseData.value?.bin_info) return
  if (!binBarChart) binBarChart = echarts.init(binBarRef.value, undefined, getChartInitOpts())
  else binBarChart.clear()

  const failBins = selectedPhaseData.value.bin_info
    .filter((b: any) => b.value > 0 && b.name !== '1' && !b.name.toLowerCase().includes('pass'))
    .sort((a: any, b: any) => b.value - a.value)
    .slice(0, 10)

  if (failBins.length === 0) return

  const tc = useEChartsTheme().colors.value.textColor
  binBarChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '8%', bottom: '3%', top: '3%', containLabel: true },
    xAxis: { type: 'value' },
    yAxis: {
      type: 'category',
      data: failBins.map((b: any) => b.name).reverse(),
      axisLabel: { color: tc, fontSize: 11 },
    },
    series: [{
      type: 'bar',
      data: failBins.map((b: any) => b.value).reverse(),
      itemStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 1, y2: 0,
          colorStops: [{ offset: 0, color: '#f093fb' }, { offset: 1, color: '#f5576c' }],
        },
      },
      label: { show: true, position: 'right', fontSize: 10, color: tc },
    }],
  })
}

function handleResize() {
  siteYieldRef.value?.handleResize()
  binSiteRef.value?.handleResize()
  if (binPieChart && !binPieChart.isDisposed()) binPieChart.resize()
  if (binBarChart && !binBarChart.isDisposed()) binBarChart.resize()
}

// keep-alive 页面激活：内联图表在缓存期间实例可能绑定到 detached DOM，强制重建
onMounted(() => {
  // 初始挂载（父级 v-if=batchData 时 props 已就绪）：默认选中首个阶段并渲染内联图表
  nextTick(() => {
    disposeBinCharts()
    renderInlineCharts()
  })
})

onActivated(() => {
  disposeBinCharts()
  nextTick(() => renderInlineCharts())
})

// 主题切换重建内联图表（Bin 饼图/柱图直接 echarts.init，不会自动跟随主题，
// 而颜色来自 useEChartsTheme 实时色值——不重建就保留旧主题颜色）
watch(() => themeStore.currentTheme, () => {
  nextTick(() => {
    disposeBinCharts()
    renderInlineCharts()
  })
})

onBeforeUnmount(() => {
  disposeBinCharts()
})

defineExpose({ handleResize })
</script>

<style scoped>
.bin-selector {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.bin-hint {
  font-size: 12px;
  color: var(--text-secondary);
}

/* 「当前范围」指示：阶段过滤态高亮，提示下方聚合区块的当前口径 */
.bin-scope {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  background: var(--bg-tertiary);
  border: 1px solid var(--border-default);
  white-space: nowrap;
}

.bin-scope--filtered {
  color: var(--brand-primary);
  border-color: var(--brand-primary);
  background: color-mix(in srgb, var(--brand-primary) 10%, transparent);
}

.bin-card-divider {
  margin: 24px 0 16px;
}

/* UPH 空态占位：与左侧 Site 良率柱图同高，避免并排时右侧塌陷 */
.bin-subpanel-empty {
  height: 100%;
  min-height: 280px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-secondary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
}

.bin-card-section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: 0.3px;
}

/* 分区标题上的当前所选阶段标识（跟随阶段选择器） */
.bin-section-phase {
  color: var(--brand-primary);
  font-variant-numeric: tabular-nums;
}

.chart-container {
  height: 320px;
}

.chart-sm {
  height: 280px;
}

.chart-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
  text-align: center;
}
</style>
