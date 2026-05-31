<template>
  <div class="pareto-panel">
    <el-card shadow="hover">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span style="font-weight: bold">📊 Pareto 分析 - 失效项目分布</span>
          <el-button type="primary" size="small" @click="loadData" :loading="loading">
            刷新数据
          </el-button>
        </div>
      </template>

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
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import ParetoChart from './ParetoChart.vue'
import { ElMessage } from 'element-plus'

interface ParetoData {
  categories: string[]
  values: number[]
  cumulative: number[]
}

const props = defineProps<{
  fileId: number | null
  filename?: string
}>()

const loading = ref(false)
const paretoData = ref<ParetoData | null>(null)

const filename = computed(() => props.filename || `File ${props.fileId}`)

async function loadData() {
  if (!props.fileId) {
    ElMessage.warning('请先选择数据文件')
    return
  }

  loading.value = true
  try {
    // Get fail test item statistics from the existing API
    // Note: In production, this should call a dedicated fail statistics endpoint
    // For now, we'll use mock data to demonstrate the Pareto chart

    // Mock data - replace with actual API call when available
    const categories = ['Test_Item_1', 'Test_Item_2', 'Test_Item_3', 'Test_Item_4', 'Test_Item_5']
    const values = [150, 80, 45, 30, 20]

    // Calculate cumulative percentages
    const total = values.reduce((sum, val) => sum + val, 0)
    const cumulative: number[] = []
    let cumulativeSum = 0

    values.forEach(val => {
      cumulativeSum += val
      cumulative.push((cumulativeSum / total) * 100)
    })

    paretoData.value = {
      categories,
      values,
      cumulative
    }

    ElMessage.success('Pareto 数据加载成功')
  } catch (error: any) {
    console.error('Failed to load Pareto data:', error)
    ElMessage.error(error.response?.data?.error || '加载 Pareto 数据失败')
  } finally {
    loading.value = false
  }
}

// Auto-load when file changes
watch(() => props.fileId, (newFileId) => {
  if (newFileId) {
    loadData()
  } else {
    paretoData.value = null
  }
}, { immediate: true })
</script>

<style scoped>
.pareto-panel {
  width: 100%;
}
</style>
