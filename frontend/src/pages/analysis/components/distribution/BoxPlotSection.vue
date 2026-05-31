<template>
  <div class="boxplot-section">
    <el-alert
      v-if="!fileId"
      title="请先选择数据文件"
      type="info"
      :closable="false"
      style="margin-bottom: 16px"
    />

    <div v-if="fileId">
      <!-- Parameter Selection -->
      <el-form :inline="true" style="margin-bottom: 16px">
        <el-form-item label="选择参数">
          <el-select
            v-model="selectedParams"
            multiple
            placeholder="选择要分析的参数"
            style="width: 300px"
            :disabled="loading"
          >
            <el-option
              v-for="param in availableParams"
              :key="param"
              :label="param"
              :value="param"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="分组方式">
          <el-select v-model="groupBy" placeholder="选择分组" style="width: 150px" :disabled="loading">
            <el-option label="不分组" value="" />
            <el-option label="按 Site 分组" value="site" />
            <el-option label="按 Bin 分组" value="bin" />
          </el-select>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="loadData" :loading="loading" :disabled="selectedParams.length === 0">
            生成箱线图
          </el-button>
        </el-form-item>
      </el-form>

      <el-skeleton v-if="loading" :rows="8" animated />

      <div v-if="boxPlotData && !loading">
        <div v-for="param in Object.keys(boxPlotData)" :key="param" style="margin-bottom: 24px">
          <el-divider content-position="left">
            <strong>{{ param }}</strong>
          </el-divider>
          <BoxPlotChart :data="{ param, ...boxPlotData[param] }" :title="`Box Plot - ${param}`" />
        </div>

        <el-alert
          title="箱线图说明"
          type="info"
          :closable="false"
          style="margin-top: 16px"
        >
          <template #default>
            <ul style="margin: 0; padding-left: 20px">
              <li>箱体表示数据的四分位数范围（Q1-Q3）</li>
              <li>箱体中的线表示中位数</li>
              <li>须（whiskers）延伸到 1.5×IQR 范围内的最大/最小值</li>
              <li>红色点表示异常值（outliers）</li>
            </ul>
          </template>
        </el-alert>
      </div>

      <el-empty v-if="!loading && !boxPlotData" description="请选择参数并点击生成箱线图" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import BoxPlotChart from '../BoxPlotChart.vue'
import { useBoxPlot } from '../../composables/useBoxPlot'

const props = defineProps<{
  fileId: number | null
  availableParams: string[]
}>()

const selectedParams = ref<string[]>([])
const groupBy = ref<string>('')

const { loading, boxPlotData, loadBoxPlot } = useBoxPlot(
  () => props.fileId,
  selectedParams,
  groupBy
)

function loadData() {
  loadBoxPlot()
}

// Auto-select first param when params change
watch(() => props.availableParams, (newParams) => {
  if (newParams.length > 0 && selectedParams.value.length === 0) {
    selectedParams.value = [newParams[0]]
  }
}, { immediate: true })

// Reset when file changes
watch(() => props.fileId, () => {
  boxPlotData.value = null
  selectedParams.value = []
})
</script>

<style scoped>
.boxplot-section {
  width: 100%;
}
</style>
