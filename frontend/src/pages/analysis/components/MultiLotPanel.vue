<template>
  <div>
    <el-tabs v-model="activeTab">
      <!-- Tab 1: Distribution Comparison -->
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

      <!-- Tab 2: Yield Comparison -->
      <el-tab-pane label="✅ 良率对比" name="yield">
        <el-row :gutter="12" style="margin-bottom:12px">
          <el-col :span="12">
            <el-select v-model="yieldFileIds" multiple placeholder="选择文件 (最少2个)" style="width:100%">
              <el-option v-for="f in files" :key="f.id" :label="f.filename" :value="f.id" />
            </el-select>
          </el-col>
          <el-col :span="6">
            <el-button type="primary" @click="onLoadYield" :loading="yieldLoading" :disabled="yieldFileIds.length < 2">加载良率对比</el-button>
          </el-col>
        </el-row>

        <template v-if="yieldResult">
          <!-- Chi-square & global stats -->
          <el-row :gutter="16" style="margin-bottom:16px">
            <el-col :span="8"><el-card shadow="never"><div class="stat-label">卡方检验</div><div class="stat-value" :class="chiSquare?.significant ? 'sig' : 'not-sig'">{{ chiSquare?.chi_square?.toFixed(4) ?? '-' }}<span class="p-value">p={{ chiSquare?.p_value?.toFixed(4) ?? '-' }}</span></div></el-card></el-col>
            <el-col :span="8"><el-card shadow="never"><div class="stat-label">平均良率</div><div class="stat-value">{{ globalStats?.mean_yield?.toFixed(2) ?? '-' }}%</div></el-card></el-col>
            <el-col :span="8"><el-card shadow="never"><div class="stat-label">异常文件</div><div class="stat-value" :class="outliers.length ? 'outlier-warn' : ''">{{ outliers.length ? outliers.length + ' 个' : '无' }}</div></el-card></el-col>
          </el-row>

          <div ref="yieldChartRef" style="height:400px; margin-bottom:16px" />

          <el-table :data="yieldResult.yield_data || []" stripe>
            <el-table-column prop="filename" label="文件" min-width="200" />
            <el-table-column prop="total" label="Total" width="80" />
            <el-table-column prop="pass_count" label="Pass" width="80" />
            <el-table-column label="Yield" width="100">
              <template #default="{row}"><span :style="{ color: yieldColor(row.yield) }">{{ row.yield }}%</span></template>
            </el-table-column>
            <el-table-column label="状态" width="80">
              <template #default="{row}"><el-tag v-if="isOutlier(row.file_id)" type="danger" size="small">异常</el-tag><el-tag v-else type="success" size="small">正常</el-tag></template>
            </el-table-column>
          </el-table>
        </template>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useChart } from '../../../composables/useChart'
import { useEChartsTheme } from '../../../utils/echarts-theme'
import api from '../../../api'
import { ElMessage } from 'element-plus'

const props = defineProps<{ files: any[]; loading: boolean; lotData: any; summary: any[]; commonParams: string[] }>()
const emit = defineEmits<{ load: [fileIds: number[], param: string] }>()
const { colors } = useEChartsTheme()

const activeTab = ref('dist')
const localFiles = ref<number[]>([])
const localParam = ref('')
const COLORS_SITE_8 = ['#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4']

// --- Yield tab state ---
const yieldFileIds = ref<number[]>([])
const yieldLoading = ref(false)
const yieldResult = ref<any>(null)
const chiSquare = computed(() => yieldResult.value?.chi_square ?? null)
const globalStats = computed(() => yieldResult.value?.global_stats ?? null)
const outliers = computed<number[]>(() => yieldResult.value?.outliers ?? [])
function isOutlier(fileId: number): boolean { return outliers.value.includes(fileId) }
function yieldColor(pct: number): string { return pct >= 95 ? '#67C23A' : pct >= 90 ? '#E6A23C' : '#F56C6C' }

function onLoad() { if (localFiles.value.length >= 2 && localParam.value) emit('load', localFiles.value, localParam.value) }

async function onLoadYield() {
  if (yieldFileIds.value.length < 2) { ElMessage.warning('请至少选择2个文件'); return }
  yieldLoading.value = true
  try {
    const { data } = await api.post('/analysis/multi_lot/', { file_ids: yieldFileIds.value, mode: 'yield' })
    yieldResult.value = data
    ElMessage.success('良率对比数据加载成功')
  } catch (error: any) {
    console.error('Failed to load yield data:', error)
    ElMessage.error(error.response?.data?.error || '加载良率对比数据失败')
  } finally { yieldLoading.value = false }
}

// --- Distribution chart (useChart) ---
function buildDistOption() {
  if (!props.lotData) return {}
  const tc = colors.value.textColor
  const data = props.lotData
  const lotDataArr: any[] = data.lot_data || []
  const series = lotDataArr.map((lot: any, idx: number) => ({
    name: lot.name, type: 'bar' as const, data: lot.bar_data,
    itemStyle: { color: lot.color || COLORS_SITE_8[idx % COLORS_SITE_8.length] }, barWidth: '80%' as const,
  }))
  return {
    tooltip: { trigger: 'axis' as const },
    legend: { data: series.map((s: any) => s.name), top: 'bottom', type: 'scroll' as const, textStyle: { color: tc } },
    xAxis: { type: 'value' as const, min: data.chart_min, max: data.chart_max, axisLabel: { color: tc } },
    yAxis: { type: 'value' as const, name: '百分比 (%)', max: 100, axisLabel: { color: tc }, nameTextStyle: { color: tc } },
    series,
  }
}

const { chartRef } = useChart(buildDistOption, [() => props.lotData])

// --- Yield chart (useChart) ---
function buildYieldOption() {
  if (!yieldResult.value) return {}
  const tc = colors.value.textColor
  const data = yieldResult.value.yield_data || []
  if (!data.length) return {}
  const filenames = data.map((d: any) => d.filename)
  const yields = data.map((d: any) => d.yield)
  const yColors = yields.map((y: number) => yieldColor(y))
  const meanYield = globalStats.value?.mean_yield || 0
  return {
    tooltip: { trigger: 'axis' as const, formatter: (params: any) => { const p = Array.isArray(params) ? params[0] : params; return `${p.name}<br/>Yield: ${p.value}%` } },
    xAxis: { type: 'category' as const, data: filenames, axisLabel: { color: tc, interval: 0, rotate: 30 } },
    yAxis: { type: 'value' as const, name: 'Yield (%)', min: 0, max: 100, axisLabel: { color: tc, formatter: '{value}%' }, nameTextStyle: { color: tc } },
    series: [{
      type: 'bar' as const, barWidth: '50%' as const,
      data: yields.map((y: number, i: number) => ({ value: y, itemStyle: { color: yColors[i] } })),
      label: { show: true, position: 'top', formatter: (p: any) => `${p.value}%`, color: tc },
      markLine: { symbol: 'none' as const, lineStyle: { color: '#FF6384', type: 'dashed' as const, width: 2 }, label: { formatter: `Mean: ${meanYield}%`, color: '#FF6384', position: 'insideEndTop' as const }, data: [{ yAxis: meanYield }] },
    }],
  }
}

const { chartRef: yieldChartRef } = useChart(buildYieldOption, [yieldResult, activeTab])
</script>

<style scoped>
.stat-label { font-size: 12px; color: var(--text-secondary, #909399); margin-bottom: 4px; }
.stat-value { font-size: 20px; font-weight: 700; color: var(--text-primary, #303133); }
.stat-value.sig { color: #E6A23C; }
.stat-value.not-sig { color: #67C23A; }
.stat-value.outlier-warn { color: #F56C6C; }
.p-value { font-size: 12px; color: var(--text-secondary, #909399); margin-left: 8px; font-weight: 400; }
</style>
