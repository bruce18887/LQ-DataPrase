<template>
  <div class="correlation-tools-tab">
    <!-- 参数相关性 -->
    <ParameterCorrelationSection
      :file-id="fileId"
      :params="params"
    />

    <el-divider />

    <!-- 相关性矩阵 -->
    <CorrelationMatrixSection
      :file-id="fileId"
    />

    <el-divider />

    <!-- 文件相关性 -->
    <FileCorrelationSection
      :files="files"
    />

    <el-divider />

    <!-- 批量导出 -->
    <BatchExportSection
      :file-id="fileId"
      :params="params"
    />
  </div>
</template>

<script setup lang="ts">
import ParameterCorrelationSection from './correlation/ParameterCorrelationSection.vue'
import CorrelationMatrixSection from './correlation/CorrelationMatrixSection.vue'
import FileCorrelationSection from './correlation/FileCorrelationSection.vue'
import BatchExportSection from './correlation/BatchExportSection.vue'

const props = defineProps<{
  fileId: number | null
  files: any[]
  params: string[]
}>()
</script>

<style scoped>
.correlation-tools-tab {
  width: 100%;
  padding: 0;
}
</style>
