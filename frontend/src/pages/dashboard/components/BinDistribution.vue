<template>
  <!-- Bin 构成 = Pareto 横向条（指南 §11.1，取代饼图+占比表）：
       按数量降序；pass 绿 / fail 红（色即语义，无图例）；
       条内右侧「数量 · 占比%」（全精度 formatPercent）；
       超多 Bin（>12）容器内滚动保持降序可读。 -->
  <div class="pareto" role="img" aria-label="Bin构成Pareto图">
    <template v-if="rows.length">
      <div v-for="r in rows" :key="r.name" class="p-row" :title="`${r.name}: ${r.value.toLocaleString()} (${formatPercent(r.pct)}%)`">
        <span class="p-name">{{ r.name }}</span>
        <div class="p-track">
          <div
            class="p-bar"
            :class="r.pass ? 'p-bar--pass' : 'p-bar--fail'"
            :style="{ width: r.widthPct + '%' }"
          />
        </div>
        <span class="p-val"><b>{{ r.value.toLocaleString() }}</b> · {{ formatPercent(r.pct) }}%</span>
      </div>
    </template>
    <el-empty v-else :image-size="60" description="暂无 Bin 数据" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { formatPercent } from '../../../utils/chart-bar'

const props = defineProps<{
  binPieData: { name: string; value: number }[]
}>()

const rows = computed(() => {
  const data = props.binPieData || []
  const total = data.reduce((s, item) => s + item.value, 0)
  const sorted = [...data].sort((a, b) => b.value - a.value)
  const max = sorted.length ? sorted[0].value : 0
  return sorted.map((item) => ({
    name: item.name,
    value: item.value,
    pass: item.name.includes('1'),
    pct: total > 0 ? (item.value / total) * 100 : 0,
    // 相对最大 Bin 的条宽；非零保底 1.5% 避免亚像素不可见
    widthPct: max > 0 ? Math.max((item.value / max) * 100, item.value > 0 ? 1.5 : 0) : 0,
  }))
})
</script>

<style scoped>
.pareto {
  display: flex;
  flex-direction: column;
  gap: 9px;
  max-height: 280px;
  overflow-y: auto;
}

.p-row {
  display: grid;
  grid-template-columns: 72px 1fr 118px;
  align-items: center;
  gap: 10px;
  font-size: 12px;
}

.p-name {
  font-weight: 600;
  color: var(--text-2);
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.p-track {
  height: 16px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--bg-3) 70%, transparent);
  overflow: hidden;
}

.p-bar {
  height: 100%;
  border-radius: 4px;
}
.p-bar--pass { background: var(--success); }
.p-bar--fail { background: var(--error); }

.p-val {
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.p-val b {
  color: var(--text);
  font-weight: 700;
}
</style>
