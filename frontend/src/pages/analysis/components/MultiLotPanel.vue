<template>
  <div>
    <el-row :gutter="12" style="margin-bottom:12px">
      <el-col :span="12">
        <el-select v-model="localFiles" multiple placeholder="选择文件 (最少2个)" style="width:100%">
          <el-option v-for="f in files" :key="f.id" :label="f.filename" :value="f.id" />
        </el-select>
      </el-col>
      <el-col :span="6">
        <el-select v-model="localParam" placeholder="选择参数" style="width:100%">
          <el-option v-for="p in commonParams" :key="p" :label="p" :value="p" />
        </el-select>
      </el-col>
      <el-col :span="6">
        <el-button type="primary" @click="onLoad" :loading="loading" :disabled="localFiles.length < 2">加载对比</el-button>
      </el-col>
    </el-row>
    <el-card v-if="lotData" style="margin-bottom:16px">
      <div ref="chartRef" style="height:400px" />
    </el-card>
    <el-table v-if="summary.length" :data="summary" stripe>
      <el-table-column prop="name" label="Lot" />
      <el-table-column prop="count" label="Count" width="80" />
      <el-table-column prop="mean" label="Mean" width="100" />
      <el-table-column prop="std" label="STD" width="100" />
      <el-table-column prop="yield_pct" label="Yield" width="90">
        <template #default="{row}">{{ row.yield_pct }}%</template>
      </el-table-column>
      <el-table-column prop="fail" label="Fail" width="80" />
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'

const props = defineProps<{
  files: any[]
  loading: boolean
  lotData: any
  summary: any[]
  commonParams: string[]
}>()

const emit = defineEmits<{
  load: [fileIds: number[], param: string]
}>()

const localFiles = ref<number[]>([])
const localParam = ref('')
const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

const COLORS_SITE_8 = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4']

function onLoad() {
  if (localFiles.value.length >= 2 && localParam.value) {
    emit('load', localFiles.value, localParam.value)
  }
}

function initChart() {
  if (!chartRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value)
  }
}

function renderChart() {
  if (!chartInstance || !props.lotData) return
  chartInstance.clear()

  const data = props.lotData
  const lotDataArr: any[] = data.lot_data || []
  const series = lotDataArr.map((lot: any, idx: number) => ({
    name: lot.name,
    type: 'bar' as const,
    data: lot.bar_data,
    itemStyle: { color: lot.color || COLORS_SITE_8[idx % COLORS_SITE_8.length] },
    barWidth: '80%' as const,
  }))

  chartInstance.setOption({
    tooltip: { trigger: 'axis' as const },
    legend: { data: series.map((s: any) => s.name), top: 'bottom', type: 'scroll' as const },
    xAxis: { type: 'value' as const, min: data.chart_min, max: data.chart_max },
    yAxis: { type: 'value' as const, name: '百分比 (%)', max: 100 },
    series,
  })
}

function resize() {
  chartInstance?.resize()
}

watch(() => props.lotData, () => {
  nextTick(() => {
    initChart()
    renderChart()
  })
})

onMounted(() => {
  window.addEventListener('resize', resize)
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>
