<template>
  <el-dialog
    :model-value="visible"
    :title="dialogTitle"
    width="min(960px, 92vw)"
    append-to-body
    @close="emit('close')"
  >
    <div v-loading="loading" class="hist-body">
      <HistogramChart
        v-if="result"
        :result="result"
        :chart-config="[]"
        range-type="RDL"
        :bar-width-percent="20"
        :selected-param="param"
        outlier-handling="off"
      />
      <StatsSummary v-if="statCards.length" :stat-cards="statCards" />
      <el-empty v-else-if="!loading" description="该列无可用统计" :image-size="60" />
      <el-alert
        v-if="errorMsg"
        :title="errorMsg"
        type="error"
        :closable="false"
        show-icon
        style="margin-top: 8px"
      />
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import api from '../../../../api'
import { useThemeStore } from '../../../../stores/theme'
import HistogramChart from '../../../analysis/components/HistogramChart.vue'
import StatsSummary from '../../../analysis/components/StatsSummary.vue'
import type { StatCard } from '../../../analysis/components/StatsSummary.vue'

interface Props {
  visible: boolean
  fileId: number | null
  param: string
  unit?: string
}

interface Emits {
  (e: 'close'): void
}

const props = defineProps<Props>()
const emit = defineEmits<Emits>()

const themeStore = useThemeStore()
const isDark = computed(() => themeStore.currentTheme === 'night')

const loading = ref(false)
const result = ref<any>(null)
const statCards = ref<StatCard[]>([])
const errorMsg = ref('')

const dialogTitle = computed(() => `${props.param}${props.unit ? ` (${props.unit})` : ''} 分布`)

async function load() {
  if (!props.visible || !props.fileId || !props.param) return
  loading.value = true
  errorMsg.value = ''
  result.value = null
  statCards.value = []
  try {
    const resp = await api.post('/analysis/histogram/', {
      file_id: props.fileId,
      params: [props.param],
      ignore_no_limit: false,
      range_type: 'RDL',
      custom_low: null,
      custom_high: null,
      iqr_multiplier: 1.5,
    })
    const r = resp.data?.results?.[props.param]
    if (!r) {
      errorMsg.value = '该参数无统计数据'
      return
    }
    result.value = r
    const clr: Record<string, string> = isDark.value
      ? { green: '#14b8a6', orange: '#fcd34d', red: '#fb7185', gray: '#9CA3AF' }
      : { green: '#4CAF50', orange: '#FF9800', red: '#F44336', gray: '#9E9E9E' }
    statCards.value = [
      { label: 'N', value: r.total_count?.toLocaleString() ?? '-' },
      { label: 'Mean', value: r.mean != null ? r.mean.toFixed(4) : '-' },
      { label: 'Median', value: r.median != null ? r.median.toFixed(4) : '-' },
      { label: 'STD', value: r.std != null ? r.std.toFixed(4) : '-' },
      { label: 'Min', value: r.data_min != null ? r.data_min.toFixed(4) : '-' },
      { label: 'Max', value: r.data_max != null ? r.data_max.toFixed(4) : '-' },
      {
        label: 'CPK',
        value: r.cpk != null ? `${r.cpk.toFixed(4)} (${r.cpk_level ?? ''})` : '-',
        color: clr[r.cpk_color] ?? undefined,
      },
      { label: 'LSL', value: r.lower_limit != null ? r.lower_limit.toFixed(4) : '-' },
      { label: 'USL', value: r.upper_limit != null ? r.upper_limit.toFixed(4) : '-' },
    ]
  } catch {
    errorMsg.value = '加载直方图失败'
  } finally {
    loading.value = false
  }
}

watch(() => [props.visible, props.fileId, props.param], load)
</script>

<style scoped>
.hist-body {
  display: flex;
  flex-direction: column;
  height: min(520px, 70vh);
}
</style>
