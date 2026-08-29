<template>
  <div class="bin-dist">
    <div class="panel-row panel-row--h420">
      <div class="panel-card">
        <div class="panel-head">🔴 Bin 分布饼图</div>
        <div class="panel-body"><div ref="binChart" class="chart-fill" role="img" aria-label="Bin分布饼图" /></div>
      </div>
      <div class="panel-card">
        <div class="panel-head">💹 Bin 占比一览</div>
        <el-table :data="binPieTableData" stripe size="small" max-height="380" border class="panel-table">
          <el-table-column prop="name" label="Bin" min-width="90">
            <template #default="{ row }">
              <el-tag :type="row.name.includes('1') ? 'success' : 'danger'" size="small">{{ row.name }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="value" label="数量" width="80" align="right" sortable />
          <el-table-column prop="pct" label="占比" width="130" align="center">
            <template #default="{ row }">
              <!-- 进度条宽度 = 百分比值，0.001% 是亚像素不可见 → 保底最小宽度
                   (MIN_BAR_HEIGHT_PCT)，文字用 format 显示真实占比 -->
              <el-progress
                :percentage="Math.max(Number(row.pct), MIN_BAR_HEIGHT_PCT)"
                :format="() => `${formatPercent(Number(row.pct))}%`"
                :color="row.name.includes('1') ? '#059669' : '#dc2626'"
                :stroke-width="12"
              />
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onActivated, onBeforeUnmount } from 'vue'
import { initEchartsWhenReady, type EchartsHandle } from '../../../utils/echarts-init'
import { useThemeStore } from '../../../stores/theme'
import { formatPercent, MIN_BAR_HEIGHT_PCT } from '../../../utils/chart-bar'

const themeStore = useThemeStore()

const props = defineProps<{
  binPieData: { name: string; value: number }[]
}>()

const binChart = ref<HTMLElement>()
let binHandle: EchartsHandle | null = null

const binPieTableData = computed(() => {
  const pieData = props.binPieData || []
  const total = pieData.reduce((s, item) => s + item.value, 0)
  return pieData.map(item => ({
    name: item.name,
    value: item.value,
    // 保留全精度数值（不再 toFixed(1)：0.001% 会被截成 "0.0"），显示交给 formatPercent
    pct: total > 0 ? (item.value / total) * 100 : 0,
  }))
})

function _tc() {
  return getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#ffffff'
}

function buildBinOption() {
  // CVD 色盲安全 10 色（组合搜索验证 protan/deutan ΔE≥15；原板存在 绿/粉、
  // 蓝/紫、琥珀/橙、绿/绿 等不可分对；b1 保持 pass 绿语义）
  const allBinColors = ['#059669', '#dc2626', '#d97706', '#2563eb', '#1F3864', '#475569', '#0284c7', '#56B4E9', '#0d9488', '#F0E442']

  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', left: 'left', top: 'center', type: 'scroll', textStyle: { color: _tc() } },
    series: [{
      type: 'pie',
      radius: ['35%', '75%'],
      center: ['60%', '50%'],
      data: props.binPieData,
      color: allBinColors,
      label: { formatter: '{b}\n{d}%', fontSize: 11 },
      emphasis: { label: { fontSize: 14, fontWeight: 'bold' } },
      itemStyle: { borderRadius: 8, borderColor: '#fff', borderWidth: 2 },
    }],
  }
}

function renderBinChart() {
  if (!binChart.value || !props.binPieData?.length) return
  if (binHandle) {
    binHandle.chart?.setOption(buildBinOption() as any, { notMerge: true, lazyUpdate: true })
  } else {
    binHandle = initEchartsWhenReady(binChart.value, { option: buildBinOption() as any, reuse: true })
  }
}

function handleResize() {
  binHandle?.chart?.resize()
}

watch(() => props.binPieData, () => {
  nextTick(() => renderBinChart())
}, { deep: true, immediate: true })

// 主题切换时重新渲染图表，更新文字颜色
watch(() => themeStore.currentTheme, () => {
  nextTick(() => renderBinChart())
})

onMounted(() => {
  window.addEventListener('resize', handleResize)
  nextTick(() => renderBinChart())
})

onActivated(() => {
  // keep-alive 重新激活后，旧实例可能绑定到已 detached 的 DOM，强制重建
  if (binHandle) { binHandle.dispose(); binHandle = null }
  nextTick(() => renderBinChart())
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  binHandle?.dispose(); binHandle = null
})

defineExpose({ handleResize })
</script>

<style scoped>
.panel-row {
  display: flex;
  gap: 16px;
}
.panel-row--h420 {
  min-height: 420px;
}
.panel-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg-2);
  border: 1px solid var(--border-2);
  border-radius: 8px;
  overflow: hidden;
}
.panel-head {
  flex-shrink: 0;
  padding: 10px 16px;
  font-weight: 600;
  font-size: 14px;
  color: var(--text);
  background: var(--bg-3);
  border-bottom: 1px solid var(--border-2);
}
.panel-body {
  flex: 1;
  min-height: 0;
  padding: 12px;
}
.chart-fill {
  width: 100%;
  height: 100%;
  min-height: 340px;
}
.panel-table {
  width: 100%;
}
</style>
