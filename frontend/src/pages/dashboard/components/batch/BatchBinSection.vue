<template>
  <!-- Bin 分布卡（指南 §11.3 ⑦）：全套对齐单文件定稿——
       Pareto + Site 柱线双列 + Bin×Site 表格/热力图页签 + UPH 紧凑行；
       阶段下拉在卡头（范围随胶囊过滤收窄），单阶段现算口径不变。 -->
  <CollapsibleSection title="📋 Bin 分布" default-open @toggle="onBinSectionToggle">
    <template #header-extra>
      <span class="bin-scope" :class="{ 'bin-scope--filtered': !!scope }">
        <el-icon class="bin-scope-icon"><Filter /></el-icon>
        {{ scopeLabel }}
      </span>
      <div class="bin-selector">
        <el-select
          v-model="selectedPhase"
          placeholder="选择阶段查看Bin分布"
          size="small"
          style="width: 200px"
        >
          <el-option v-for="p in phases" :key="phaseKey(p)" :label="phaseLabel(p)" :value="phaseKey(p)" />
        </el-select>
      </div>
    </template>

    <!-- 图表双列：Bin 构成 Pareto + Site 良率柱线组合（<900px 堆叠） -->
    <div class="bin-charts">
      <div class="chart-box">
        <div class="cb-title">Bin 构成 <span class="cb-phase">（{{ selectedPhase || '-' }}）</span></div>
        <BinDistribution :bin-pie-data="phaseBinPieData" />
      </div>
      <SiteYieldAnalysis
        ref="siteYieldRef"
        :site-yield-data="phaseSiteYieldRows"
        :overall-yield="phaseOverallYield"
      />
    </div>

    <!-- Bin × Site 交叉表（表格 / 热力图页签） -->
    <div class="bin-sub-title">
      Bin × Site 交叉表 <span class="cb-phase">（{{ selectedPhase || '-' }}）</span>
    </div>
    <BinSiteCrossTable
      v-if="phaseBinSite.bin_table_data.length"
      ref="binSiteRef"
      embedded
      :bin-table-data="phaseBinSite.bin_table_data"
      :bin-site-columns="phaseBinSite.bin_site_columns"
    />
    <el-empty v-else :image-size="60" description="该阶段无 Bin × Site 数据" />

    <!-- UPH 紧凑明细行 -->
    <div class="bin-sub-title">
      ⚡ UPH 效率明细 <span class="cb-phase">（{{ selectedPhase || '-' }}）</span>
    </div>
    <UphCard v-if="phaseUph" embedded :uph-data="phaseUph" />
    <el-empty v-else :image-size="60" description="该阶段无 UPH 数据" class="bin-subpanel-empty" />
  </CollapsibleSection>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onActivated } from 'vue'
import { Filter } from '@element-plus/icons-vue'
import { aggregateSiteYield, aggregateBinSiteTable } from '../../../../utils/batchAggregation'
import CollapsibleSection from '../../../../components/common/CollapsibleSection.vue'
import SiteYieldAnalysis from '../SiteYieldAnalysis.vue'
import BinSiteCrossTable from '../BinSiteCrossTable.vue'
import BinDistribution from '../BinDistribution.vue'
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
const binSectionOpen = ref(true) // Bin 分布卡默认展开

// Ref to child chart components
const siteYieldRef = ref<InstanceType<typeof SiteYieldAnalysis>>()
const binSiteRef = ref<InstanceType<typeof BinSiteCrossTable>>()

// ── 单阶段口径：Site 良率 / Bin×Site / UPH 与阶段下拉一致，
//    全部从「所选阶段（单个文件）」现算，随阶段选择器切换 ──
const phaseBinPieData = computed(() => {
  const info = selectedPhaseData.value?.bin_info || []
  return info.map((b: any) => ({ name: String(b.name), value: b.value || 0 }))
})

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
}

// 阶段过滤后选中的 Bin 阶段可能已不存在 → 回退到首个阶段
watch(() => props.phases, () => {
  if (!selectedPhase.value || !props.phases.some((p: any) => phaseKey(p) === selectedPhase.value)) {
    selectedPhase.value = props.phases.length ? phaseKey(props.phases[0]) : ''
  }
}, { deep: true, immediate: true })

function handleResize() {
  siteYieldRef.value?.handleResize()
  binSiteRef.value?.handleResize()
}

onMounted(() => {
  nextTick(() => {
    siteYieldRef.value?.handleResize()
  })
})

onActivated(() => {
  nextTick(() => {
    siteYieldRef.value?.handleResize()
    binSiteRef.value?.handleResize()
  })
})

defineExpose({ handleResize })
</script>

<style scoped>
/* 卡头右侧：范围指示 + 阶段下拉 */
.bin-selector {
  display: inline-flex;
  align-items: center;
}

.bin-hint {
  font-size: 12px;
  color: var(--text-2);
}

/* 「当前范围」指示：阶段过滤态高亮，提示下方聚合区块的当前口径 */
.bin-scope {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-2);
  background: var(--bg-3);
  border: 1px solid var(--border-2);
  white-space: nowrap;
}

.bin-scope--filtered {
  color: var(--brand);
  border-color: var(--brand);
  background: color-mix(in srgb, var(--brand) 10%, transparent);
}

/* 图表双列（<900px 堆叠） */
.bin-charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 14px;
}
@media (max-width: 900px) {
  .bin-charts { grid-template-columns: 1fr; }
}

.chart-box {
  border: 1px solid var(--border-2);
  border-radius: 10px;
  background: var(--bg);
  padding: 12px;
  display: flex;
  flex-direction: column;
}
.cb-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.cb-phase {
  color: var(--brand);
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

/* 分区小标题（Bin×Site / UPH） */
.bin-sub-title {
  margin: 16px 0 8px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
  font-size: 12px;
  font-weight: 700;
  color: var(--text);
}

/* UPH 空态占位 */
.bin-subpanel-empty {
  min-height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-2);
  border: 1px solid var(--border-2);
  border-radius: 8px;
}
</style>
