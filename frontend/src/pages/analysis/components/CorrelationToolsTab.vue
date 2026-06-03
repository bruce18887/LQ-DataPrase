<template>
  <div class="correlation-tools-tab">
    <!-- 参数相关性 -->
    <ParameterCorrelationSection
      :file-id="fileId"
      :params="params"
    />
  </div>
</template>

<script setup lang="ts">
import ParameterCorrelationSection from './correlation/ParameterCorrelationSection.vue'

defineProps<{
  fileId: number | null
  params: string[]
}>()
</script>

<style scoped>
.correlation-tools-tab {
  width: 100%;
}
</style>
