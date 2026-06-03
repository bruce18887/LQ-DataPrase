<template>
  <div>
    <el-tabs v-model="activeTab">
      <!-- Tab 1: Distribution Comparison (existing functionality, unchanged) -->
      <el-tab-pane label="📊 分布对比" name="dist">
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
      </el-tab-pane>

      <!-- Tab 2: Yield Comparison (new) -->
      <el-tab-pane label="✅ 良率对比" name="yield">
        <el-row :gutter="12" style="margin-bottom:12px">
          <el-col :span="12">
            <el-select v-model="yieldFileIds" multiple placeholder="选择文件 (最少2个)" style="width:100%">
              <el-option v-for="f in files" :key="f.id" :label="f.filename" :value="f.id" />
            </el-select>
          </el-col>
          <el-col :span="6" :offset="6">
            <el-button type="success" @click="onLoadYield" :loading="yieldLoading" :disabled="yieldFileIds.length < 2">
              加载良率对比
            </el-button>
          </el-col>
        </el-row>

        <!-- Yield Bar Chart -->
        <el-card v-if="yieldResult" style="margin-bottom:16px">
          <div ref="yieldChartRef" style="height:400px" />
        </el-card>

        <!-- Yield Summary Table -->
        <el-table v-if="yieldResult && yieldResult.yield_data && yieldResult.yield_data.length" :data="yieldResult.yield_data" stripe style="margin-bottom:16px">
          <el-table-column prop="filename" label="Lot" />
          <el-table-column prop="total" label="Total" width="80" />
          <el-table-column prop="pass" label="Pass" width="80" />
          <el-table-column prop="fail" label="Fail" width="80" />
          <el-table-column prop="yield" label="Yield %" width="100">
            <template #default="{row}">{{ row.yield }}%</template>
          </el-table-column>
          <el-table-column label="Anomaly" width="100" align="center">
            <template #default="{row}">
              <el-tag v-if="isOutlier(row.file_id)" type="warning" effect="dark" size="small">⚠️</el-tag>
            </template>
          </el-table-column>
        </el-table>

        <!-- Chi-Square Test Result -->
        <el-card v-if="chiSquare" style="margin-bottom:16px">
          <template #header>
            <span>卡方检验 (Chi-Square Test)</span>
          </template>
          <div>
            <p>统计量: {{ chiSquare.statistic }}</p>
            <p>
              p-value: {{ chiSquare.p_value }}
              <el-tag v-if="chiSquare.significant" type="danger" size="small" style="margin-left:8px">显著差异</el-tag>
              <el-tag v-else type="success" size="small" style="margin-left:8px">无显著差异</el-tag>
            </p>
          </div>
        </el-card>

        <!-- Global Statistics -->
        <el-card v-if="globalStats">
          <template #header>
            <span>全局统计 (Global Statistics)</span>
          </template>
          <el-row :gutter="16">
            <el-col :span="6">
              <div style="text-align:center">
                <div style="font-size:12px;color:#909399">Mean</div>
                <div style="font-size:18px;font-weight:bold">{{ globalStats.mean_yield }}%</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div style="text-align:center">
                <div style="font-size:12px;color:#909399">STD</div>
                <div style="font-size:18px;font-weight:bold">{{ globalStats.std_yield }}%</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div style="text-align:center">
                <div style="font-size:12px;color:#909399">Min</div>
                <div style="font-size:18px;font-weight:bold">{{ globalStats.min_yield }}%</div>
              </div>
            </el-col>
            <el-col :span="6">
              <div style="text-align:center">
                <div style="font-size:12px;color:#909399">Max</div>
                <div style="font-size:18px;font-weight:bold">{{ globalStats.max_yield }}%</div>
              </div>
            </el-col>
          </el-row>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted, computed } from 'vue'
import * as echarts from 'echarts'
import { getChartInitOpts } from '../../../utils/echarts-theme'
import { useThemeStore } from '../../../stores/theme'
import api from '../../../api'
import { ElMessage } from 'element-plus'

const _tc = () => getComputedStyle(document.documentElement).getPropertyValue('--text-primary').trim() || '#ffffff'
const themeStore = useThemeStore()

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

// --- Tab state ---
const activeTab = ref('dist')

// --- Distribution tab state (unchanged) ---
const localFiles = ref<number[]>([])
const localParam = ref('')
const chartRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null

// --- Yield tab state ---
const yieldFileIds = ref<number[]>([])
const yieldLoading = ref(false)
const yieldResult = ref<any>(null)
const yieldChartRef = ref<HTMLElement>()
let yieldChartInstance: echarts.ECharts | null = null

// Computed helpers for yield data
const chiSquare = computed(() => yieldResult.value?.chi_square ?? null)
const globalStats = computed(() => yieldResult.value?.global_stats ?? null)
const outliers = computed<number[]>(() => yieldResult.value?.outliers ?? [])

function isOutlier(fileId: number): boolean {
  return outliers.value.includes(fileId)
}

const COLORS_SITE_8 = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4']

// --- Distribution tab functions (unchanged) ---
function onLoad() {
  if (localFiles.value.length >= 2 && localParam.value) {
    emit('load', localFiles.value, localParam.value)
  }
}

function initChart() {
  if (!chartRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value, undefined, getChartInitOpts())
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
    legend: { data: series.map((s: any) => s.name), top: 'bottom', type: 'scroll' as const, textStyle: { color: _tc() } },
    xAxis: { type: 'value' as const, min: data.chart_min, max: data.chart_max, axisLabel: { color: _tc() } },
    yAxis: { type: 'value' as const, name: '百分比 (%)', max: 100, axisLabel: { color: _tc() }, nameTextStyle: { color: _tc() } },
    series,
  })
}

// --- Yield tab functions ---
async function onLoadYield() {
  if (yieldFileIds.value.length < 2) {
    ElMessage.warning('请至少选择2个文件')
    return
  }
  yieldLoading.value = true
  try {
    const { data } = await api.post('/analysis/multi_lot/', {
      file_ids: yieldFileIds.value,
      mode: 'yield',
    })
    yieldResult.value = data
    ElMessage.success('良率对比数据加载成功')
  } catch (error: any) {
    console.error('Failed to load yield data:', error)
    ElMessage.error(error.response?.data?.error || '加载良率对比数据失败')
  } finally {
    yieldLoading.value = false
  }
}

function yieldColor(pct: number): string {
  if (pct >= 95) return '#67C23A'   // green
  if (pct >= 90) return '#E6A23C'   // yellow/amber
  return '#F56C6C'                  // red
}

function initYieldChart() {
  if (!yieldChartRef.value) return
  if (!yieldChartInstance) {
    yieldChartInstance = echarts.init(yieldChartRef.value, undefined, getChartInitOpts())
  }
}

function renderYieldChart() {
  if (!yieldChartInstance || !yieldResult.value) return
  yieldChartInstance.clear()

  const data = yieldResult.value.yield_data || []
  if (!data.length) return

  const filenames = data.map((d: any) => d.filename)
  const yields = data.map((d: any) => d.yield)
  const colors = yields.map((y: number) => yieldColor(y))
  const meanYield = globalStats.value?.mean_yield || 0

  yieldChartInstance.setOption({
    tooltip: {
      trigger: 'axis' as const,
      formatter: (params: any) => {
        const p = Array.isArray(params) ? params[0] : params
        return `${p.name}<br/>Yield: ${p.value}%`
      },
    },
    xAxis: {
      type: 'category' as const,
      data: filenames,
      axisLabel: { color: _tc(), interval: 0, rotate: 30 },
    },
    yAxis: {
      type: 'value' as const,
      name: 'Yield (%)',
      min: 0,
      max: 100,
      axisLabel: { color: _tc(), formatter: '{value}%' },
      nameTextStyle: { color: _tc() },
    },
    series: [{
      type: 'bar' as const,
      data: yields.map((y: number, i: number) => ({
        value: y,
        itemStyle: { color: colors[i] },
      })),
      barWidth: '50%' as const,
      label: {
        show: true,
        position: 'top',
        formatter: (p: any) => `${p.value}%`,
        color: _tc(),
      },
      markLine: {
        symbol: 'none' as const,
        lineStyle: { color: '#FF6384', type: 'dashed' as const, width: 2 },
        label: {
          formatter: `Mean: ${meanYield}%`,
          color: '#FF6384',
          position: 'insideEndTop' as const,
        },
        data: [{ yAxis: meanYield }],
      },
    }],
  })
}

// --- Common lifecycle ---
function resize() {
  chartInstance?.resize()
  yieldChartInstance?.resize()
}

// Watch distribution data -> render distribution chart
watch(() => props.lotData, () => {
  nextTick(() => {
    initChart()
    renderChart()
  })
})

// Watch yield result -> render yield chart
watch(yieldResult, () => {
  nextTick(() => {
    initYieldChart()
    renderYieldChart()
  })
})

// Re-render yield chart when switching to yield tab (if data already loaded)
watch(activeTab, (tab) => {
  if (tab === 'yield' && yieldResult.value) {
    nextTick(() => {
      initYieldChart()
      renderYieldChart()
    })
  }
})

// Theme change -> re-render both charts
watch(() => themeStore.currentTheme, () => {
  if (!chartRef.value?.isConnected) return
  nextTick(() => {
    renderChart()
    renderYieldChart()
  })
})

onMounted(() => {
  window.addEventListener('resize', resize)
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  chartInstance?.dispose()
  chartInstance = null
  yieldChartInstance?.dispose()
  yieldChartInstance = null
})
</script>
