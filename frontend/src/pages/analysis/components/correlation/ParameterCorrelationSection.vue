<template>
  <div class="param-correlation-section">
    <CorrelationPanel
      :params="params"
      :loading="corrLoading"
      :chart-data="corrResult"
      @analyze="loadCorrelation"
    />
  </div>
</template>

<script setup lang="ts">
import CorrelationPanel from '../CorrelationPanel.vue'
import { useCorrelation } from '../../composables/useCorrelation'

const props = defineProps<{
  fileId: number | null
  params: string[]
}>()

const { corrLoading, corrResult, loadCorrelation } = useCorrelation(() => props.fileId)
</script>

<style scoped>
.param-correlation-section { width: 100%; }
</style>
