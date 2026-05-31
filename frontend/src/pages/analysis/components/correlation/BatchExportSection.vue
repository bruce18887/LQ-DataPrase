<template>
  <div class="batch-export-section">
    <el-card header="📥 批量导出" shadow="hover">
      <BatchExportPanel
        :params="params"
        :exporting="exporting"
        @export-sigma="exportSigmaLimit"
        @export-batch="exportBatchCharts"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import BatchExportPanel from '../BatchExportPanel.vue'
import { useExport } from '../../composables/useExport'

const props = defineProps<{
  fileId: number | null
  params: string[]
}>()

const { exporting, exportSigmaLimit, exportBatchCharts } = useExport(() => props.fileId)
</script>

<style scoped>
.batch-export-section {
  width: 100%;
}
</style>
