<template>
  <div class="batch-export-section">
    <el-card header="📥 批量导出" shadow="hover">
      <BatchExportPanel
        :params="params"
        :exporting="exporting"
        @export-sigma="onExportSigma"
        @export-batch="onExportBatch"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import BatchExportPanel from '../BatchExportPanel.vue'
import { useExport } from '../../composables/useExport'
import { useAnalysisStore } from '../../../../stores/analysis'

const props = defineProps<{
  fileId: number | null
  params: string[]
}>()

const analysisStore = useAnalysisStore()

const { exporting, exportSigmaLimit, exportBatchCharts } = useExport(() => props.fileId)

// 图表配置的「仅用Pass数据(Bin1)」开关跟随导出，保证导出图表与分析页视图一致
function onExportSigma(sigma: number) {
  exportSigmaLimit(sigma, { data_only_bin1: analysisStore.dataOnlyBin1 })
}

function onExportBatch(params: string[], format: string) {
  exportBatchCharts(params, format, { data_only_bin1: analysisStore.dataOnlyBin1 })
}
</script>

<style scoped>
.batch-export-section {
  width: 100%;
}
</style>
