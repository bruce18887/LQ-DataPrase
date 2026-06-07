<template>
  <div class="batch-analysis-charts">
    <!-- Site 良率分布 & Yield 分析 -->
    <el-card shadow="never" class="section-card">
      <template #header>🟢 Site 良率分布 &amp; Yield 分析</template>
      <SiteYieldAnalysis
        ref="siteYieldRef"
        :site-yield-data="siteYieldData"
        :overall-yield="overallYield"
      />
    </el-card>

    <!-- Bin × Site 交叉表 + Bin × Site 柱状图 -->
    <el-card shadow="never" class="section-card">
      <template #header>📊 Bin &times; Site 交叉表 &amp; 柱状图</template>
      <BinSiteCrossTable
        ref="binSiteRef"
        :bin-table-data="binTableData"
        :bin-site-columns="binSiteColumns"
      />
    </el-card>

    <!-- UPH 效率分析 -->
    <el-card shadow="never" class="section-card">
      <template #header>⚡ UPH 效率分析</template>
      <UphCard :uph-data="uphData" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import SiteYieldAnalysis from '../SiteYieldAnalysis.vue'
import BinSiteCrossTable from '../BinSiteCrossTable.vue'
import UphCard from '../UphCard.vue'

const props = defineProps<{
  batchData: any
}>()

const siteYieldRef = ref<InstanceType<typeof SiteYieldAnalysis>>()
const binSiteRef = ref<InstanceType<typeof BinSiteCrossTable>>()

// Transform site_pass_data → SiteYieldAnalysis props
const siteYieldData = computed(() => {
  const rows = props.batchData?.site_pass_data || []
  return rows.map((r: any) => ({
    Site: r.site,
    Yield: r.yield,
    Total: r.total,
    PassCount: r.pass,
  }))
})

// Batch overall yield (matches single-file: kpi.overall_yield)
const overallYield = computed(() => Number(props.batchData?.kpi?.overall_yield) || 0)

const binTableData = computed(() => props.batchData?.bin_table_data || [])
const binSiteColumns = computed(() => props.batchData?.bin_site_columns || [])
const uphData = computed(() => props.batchData?.uph || null)

function handleResize() {
  siteYieldRef.value?.handleResize()
  binSiteRef.value?.handleResize()
}

defineExpose({ handleResize })
</script>

<style scoped>
.batch-analysis-charts {
  display: contents;
}

.section-card {
  margin-bottom: 16px;
  border-radius: 8px;
}

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
</style>
