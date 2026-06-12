<!-- frontend/src/pages/analysis/components/distribution/BoxPlotSection.vue -->
<template>
  <AnalysisTabLayout :loading="loading">
    <!-- 工具栏：分组模式切换 -->
    <template #toolbar>
      <el-radio-group v-model="groupBy" size="small">
        <el-radio-button value="">不分组</el-radio-button>
        <el-radio-button value="site">按 Site 分组</el-radio-button>
        <el-radio-button value="bin">按 Bin 分组</el-radio-button>
      </el-radio-group>
      <el-button
        type="primary"
        size="small"
        :loading="loading"
        :disabled="selectedParams.length === 0"
        @click="loadData"
      >
        生成箱线图
      </el-button>
    </template>

    <!-- 左侧面板：参数选择 + 说明 -->
    <template #left-panel>
      <el-card shadow="hover" :body-style="{ padding: '12px' }">
        <label class="section-label">选择参数（可多选）</label>
        <el-select
          v-model="selectedParams"
          multiple
          filterable
          placeholder="选择要分析的参数"
          style="width: 100%"
          :disabled="loading"
        >
          <el-option
            v-for="param in availableParams"
            :key="param"
            :label="param"
            :value="param"
          />
        </el-select>
      </el-card>

      <el-collapse>
        <el-collapse-item title="箱线图说明" name="info">
          <ul class="info-list">
            <li>箱体表示数据的四分位数范围（Q1-Q3）</li>
            <li>箱体中的线表示中位数</li>
            <li>须（whiskers）延伸到 1.5×IQR 范围内的最大/最小值</li>
            <li>红色点表示异常值（outliers）</li>
          </ul>
        </el-collapse-item>
      </el-collapse>
    </template>

    <!-- 右侧面板：图表 -->
    <template #right-panel>
      <!-- 无数据时的空状态 -->
      <el-empty
        v-if="!loading && !boxPlotData"
        description="请选择参数并点击生成箱线图"
      />

      <!-- 图表列表 -->
      <div v-if="boxPlotData && !loading" class="boxplot-list">
        <div
          v-for="param in Object.keys(boxPlotData)"
          :key="param"
          class="boxplot-item"
        >
          <div class="boxplot-item__header">
            <strong>{{ param }}</strong>
            <span v-if="boxPlotData[param]?.overall" class="boxplot-stats">
              Min: {{ boxPlotData[param].overall.min?.toFixed(4) }}
              | Q1: {{ boxPlotData[param].overall.q1?.toFixed(4) }}
              | Median: {{ boxPlotData[param].overall.median?.toFixed(4) }}
              | Q3: {{ boxPlotData[param].overall.q3?.toFixed(4) }}
              | Max: {{ boxPlotData[param].overall.max?.toFixed(4) }}
              | Outliers: {{ boxPlotData[param].overall.outliers?.length ?? 0 }}
            </span>
          </div>
          <div class="chart-wrapper">
            <BoxPlotChart :data="{ param, ...boxPlotData[param] }" :title="`Box Plot - ${param}`" />
          </div>
        </div>
      </div>
    </template>
  </AnalysisTabLayout>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import AnalysisTabLayout from '../AnalysisTabLayout.vue'
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
.section-label {
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 4px;
  font-weight: 500;
  display: block;
}

.info-list {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.8;
}

.boxplot-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.boxplot-item__header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 8px;
}

.boxplot-item__header strong {
  font-size: 14px;
  color: var(--text-primary);
}

.boxplot-stats {
  font-size: 12px;
  color: var(--text-secondary);
}

.chart-wrapper {
  flex: 1;
  min-height: 480px;
  background: var(--bg-secondary, #fff);
  border-radius: 6px;
  border: 1px solid var(--border-default, #e4e7ed);
  overflow: hidden;
}

.chart-wrapper > * {
  height: 100%;
}
</style>
