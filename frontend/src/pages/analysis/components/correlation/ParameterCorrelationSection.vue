<template>
  <div class="param-correlation-section">
    <el-card header="🔗 参数相关性分析" shadow="hover" style="margin-bottom: 16px">
      <CorrelationPanel
        :params="params"
        :loading="corrLoading"
        :pearson-r="corrPearsonR"
        :chart-data="corrResult"
        v-model:axis-mode="corrAxisMode"
        @analyze="loadCorrelation"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import CorrelationPanel from '../CorrelationPanel.vue'
import { useCorrelation } from '../../composables/useCorrelation'

const props = defineProps<{
  fileId: number | null
  params: string[]
}>()

const {
  corrLoading,
  corrResult,
  corrPearsonR,
  corrAxisMode,
  loadCorrelation,
} = useCorrelation(() => props.fileId)
</script>

<style scoped>
.param-correlation-section {
  width: 100%;
}
</style>
