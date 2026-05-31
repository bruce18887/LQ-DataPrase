<template>
  <div class="trend-failure-tab">
    <el-card shadow="hover">
      <!-- 模式切换 -->
      <div class="mode-selector">
        <el-radio-group v-model="analysisMode" size="large">
          <el-radio-button value="trend">
            📈 参数趋势 - 多文件参数变化
          </el-radio-button>
          <el-radio-button value="pareto">
            📊 Pareto分析 - 失效项目分布
          </el-radio-button>
        </el-radio-group>
      </div>

      <!-- 条件渲染 -->
      <ParameterTrendSection
        v-if="analysisMode === 'trend'"
        :files="files"
        :available-params="params"
      />
      <ParetoSection
        v-if="analysisMode === 'pareto'"
        :file-id="fileId"
        :filename="filename"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAnalysisStore } from '../../../stores/analysis'
import ParameterTrendSection from './trend/ParameterTrendSection.vue'
import ParetoSection from './trend/ParetoSection.vue'

const props = defineProps<{
  fileId: number | null
  files: any[]
  params: string[]
  filename?: string
}>()

const analysisStore = useAnalysisStore()
const analysisMode = ref<'trend' | 'pareto'>(analysisStore.analysisMode || 'trend')

// Sync to store
watch(analysisMode, (val) => {
  analysisStore.analysisMode = val
})
</script>

<style scoped>
.trend-failure-tab {
  width: 100%;
}

.mode-selector {
  margin-bottom: 20px;
  padding: 12px;
  background: #f8f9fa;
  border-radius: 6px;
  display: flex;
  justify-content: center;
}

.mode-selector :deep(.el-radio-button__inner) {
  padding: 12px 24px;
  font-size: 14px;
}
</style>
