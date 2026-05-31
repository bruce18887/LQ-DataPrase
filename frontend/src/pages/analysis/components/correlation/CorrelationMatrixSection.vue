<template>
  <div class="correlation-matrix-section">
    <el-card header="📊 相关性矩阵" shadow="hover" style="margin-bottom: 16px">
      <CorrelationMatrixPanel
        :loading="matrixLoading"
        :matrix-data="correlationMatrix"
        @calculate="loadCorrelationMatrix"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import CorrelationMatrixPanel from '../CorrelationMatrixPanel.vue'
import { useCorrelationMatrix } from '../../composables/useCorrelationMatrix'

const props = defineProps<{
  fileId: number | null
}>()

const { loading: matrixLoading, matrixData: correlationMatrix, loadCorrelationMatrix } = useCorrelationMatrix(
  () => props.fileId
)
</script>

<style scoped>
.correlation-matrix-section {
  width: 100%;
}
</style>
