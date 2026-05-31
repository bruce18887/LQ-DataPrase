<template>
  <div class="distribution-comparison-tab">
    <el-card shadow="hover">
      <!-- 模式切换 -->
      <div class="mode-selector">
        <el-radio-group v-model="comparisonMode" size="large">
          <el-radio-button value="boxplot">
            📦 箱线图分析 - 单文件多参数
          </el-radio-button>
          <el-radio-button value="multilot">
            📊 多Lot对比 - 多文件单参数
          </el-radio-button>
        </el-radio-group>
      </div>

      <!-- 条件渲染 -->
      <BoxPlotSection
        v-if="comparisonMode === 'boxplot'"
        :file-id="fileId"
        :available-params="params"
      />
      <MultiLotSection
        v-if="comparisonMode === 'multilot'"
        :files="files"
        :common-params="commonParams"
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAnalysisStore } from '../../../stores/analysis'
import BoxPlotSection from './distribution/BoxPlotSection.vue'
import MultiLotSection from './distribution/MultiLotSection.vue'

const props = defineProps<{
  fileId: number | null
  files: any[]
  params: string[]
  commonParams: string[]
}>()

const analysisStore = useAnalysisStore()
const comparisonMode = ref<'boxplot' | 'multilot'>(analysisStore.comparisonMode || 'boxplot')

// Sync to store
watch(comparisonMode, (val) => {
  analysisStore.comparisonMode = val
})
</script>

<style scoped>
.distribution-comparison-tab {
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
