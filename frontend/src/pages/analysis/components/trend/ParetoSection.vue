<template>
  <div class="pareto-section">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px">
      <span style="font-weight: bold; font-size: 14px">📊 Pareto 分析 - 失效项目分布</span>
      <el-button type="primary" size="small" @click="loadData" :loading="loading">
        刷新数据
      </el-button>
    </div>

    <el-alert
      v-if="!fileId"
      title="请先选择数据文件"
      type="info"
      :closable="false"
      style="margin-bottom: 16px"
    />

    <div v-if="fileId && !loading && !paretoData">
      <el-empty description="暂无失效数据">
        <el-button type="primary" @click="loadData">加载数据</el-button>
      </el-empty>
    </div>

    <el-skeleton v-if="loading" :rows="8" animated />

    <div v-if="paretoData && !loading">
      <el-descriptions :column="2" border style="margin-bottom: 16px">
        <el-descriptions-item label="数据文件">{{ filename }}</el-descriptions-item>
        <el-descriptions-item label="失效项目数">{{ paretoData.categories.length }}</el-descriptions-item>
      </el-descriptions>

      <ParetoChart :data="paretoData" :title="`Pareto Chart - ${filename}`" />

      <el-alert
        title="Pareto 原则"
        type="success"
        :closable="false"
        style="margin-top: 16px"
      >
        <template #default>
          80% 的问题通常由 20% 的原因造成。图中绿色虚线标记 80% 累积百分比位置，
          帮助识别需要优先解决的关键失效项目。
        </template>
      </el-alert>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ParetoChart from '../ParetoChart.vue'
import { usePareto } from '../../composables/usePareto'

const props = defineProps<{
  fileId: number | null
  filename?: string
}>()

const filename = computed(() => props.filename || `File ${props.fileId}`)

const { loading, paretoData, loadPareto } = usePareto(
  () => props.fileId
)

function loadData() {
  loadPareto()
}
</script>

<style scoped>
.pareto-section {
  width: 100%;
}
</style>
