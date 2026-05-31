<template>
  <div class="param-trend-section">
    <el-alert
      title="参数趋势分析需要选择多个数据文件"
      type="info"
      :closable="false"
      style="margin-bottom: 16px"
    />

    <!-- File Selection -->
    <el-form style="margin-bottom: 16px">
      <el-form-item label="选择数据文件（多选）">
        <el-select
          v-model="selectedFileIds"
          multiple
          placeholder="选择要对比的数据文件"
          style="width: 100%"
          :disabled="loading"
        >
          <el-option
            v-for="file in files"
            :key="file.id"
            :label="file.filename"
            :value="file.id"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="选择参数">
        <el-row :gutter="16">
          <el-col :span="18">
            <el-select
              v-model="selectedParam"
              placeholder="选择要分析的参数"
              style="width: 100%"
              :disabled="loading || selectedFileIds.length === 0"
            >
              <el-option
                v-for="param in availableParams"
                :key="param"
                :label="param"
                :value="param"
              />
            </el-select>
          </el-col>
          <el-col :span="6">
            <el-button
              type="primary"
              @click="loadData"
              :loading="loading"
              :disabled="selectedFileIds.length < 2 || !selectedParam"
              style="width: 100%"
            >
              生成趋势图
            </el-button>
          </el-col>
        </el-row>
      </el-form-item>
    </el-form>

    <el-skeleton v-if="loading" :rows="8" animated />

    <div v-if="trendData && !loading">
      <el-descriptions :column="3" border style="margin-bottom: 16px">
        <el-descriptions-item label="参数名称">{{ trendData.param }}</el-descriptions-item>
        <el-descriptions-item label="文件数量">{{ trendData.files.length }}</el-descriptions-item>
        <el-descriptions-item label="规格限">
          <span v-if="trendData.limits.lsl !== null && trendData.limits.usl !== null">
            {{ trendData.limits.lsl.toFixed(4) }} ~ {{ trendData.limits.usl.toFixed(4) }}
          </span>
          <span v-else style="color: #999">未设置</span>
        </el-descriptions-item>
      </el-descriptions>

      <ParameterTrendChart :data="trendData" :title="`Parameter Trend - ${trendData.param}`" />

      <el-alert
        title="趋势分析说明"
        type="info"
        :closable="false"
        style="margin-top: 16px"
      >
        <template #default>
          <ul style="margin: 0; padding-left: 20px">
            <li>蓝色实线：参数均值趋势</li>
            <li>绿色虚线：均值 ± 标准差范围（浅绿色阴影区域）</li>
            <li>红色菱形：CPK 趋势（右侧 Y 轴）</li>
            <li>红色实线：规格上下限（USL/LSL）</li>
          </ul>
        </template>
      </el-alert>
    </div>

    <el-empty
      v-if="!loading && !trendData"
      description="请选择至少 2 个文件和 1 个参数，然后点击生成趋势图"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import ParameterTrendChart from '../ParameterTrendChart.vue'
import { useParameterTrend } from '../../composables/useParameterTrend'

const props = defineProps<{
  files: any[]
  availableParams: string[]
}>()

const selectedFileIds = ref<number[]>([])
const selectedParam = ref<string>('')

const { loading, trendData, loadParameterTrend } = useParameterTrend(
  selectedFileIds,
  selectedParam
)

function loadData() {
  loadParameterTrend()
}

// Auto-select first param when params change
watch(() => props.availableParams, (newParams) => {
  if (newParams.length > 0 && !selectedParam.value) {
    selectedParam.value = newParams[0]
  }
}, { immediate: true })

// Auto-select first 2 files when files change
watch(() => props.files, (newFiles) => {
  if (newFiles.length >= 2 && selectedFileIds.value.length === 0) {
    selectedFileIds.value = newFiles.slice(0, 2).map(f => f.id)
  }
}, { immediate: true })
</script>

<style scoped>
.param-trend-section {
  width: 100%;
}
</style>
