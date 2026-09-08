<template>
  <div class="wafer-stat-tables">
    <!-- 分区良率：zonal_yield 三区常驻表（非分区模式也展示，数字口径与图同源） -->
    <div class="stat-card" data-wafer-zone-table>
      <div class="stat-card-h">分区良率</div>
      <table class="stat-table">
        <thead>
          <tr><th>环带</th><th class="n">Die</th><th class="n">Pass</th><th class="n">Yield</th></tr>
        </thead>
        <tbody>
          <tr v-for="z in zones" :key="z.name">
            <td>{{ z.name }}</td>
            <td class="n">{{ z.total }}</td>
            <td class="n">{{ z.pass }}</td>
            <td class="n" :class="zoneYieldClass(z.yield)">{{ fmtYield(z.yield) }}</td>
          </tr>
          <tr v-if="!zones.length">
            <td colspan="4" class="stat-empty">{{ zoneError || '暂无分区数据' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 该片统计：stats + wafer 几何（坐标列/die_size 后端已下发） -->
    <div class="stat-card" data-wafer-stat-table>
      <div class="stat-card-h">该片统计</div>
      <table class="stat-table">
        <tbody>
          <tr><td>总 die</td><td class="n">{{ stats?.total ?? '-' }}</td></tr>
          <tr><td>Pass</td><td class="n">{{ stats?.pass_count ?? '-' }}</td></tr>
          <tr><td>Fail</td><td class="n" :class="{ 'val-fail': (stats?.fail_count ?? 0) > 0 }">{{ stats?.fail_count ?? '-' }}</td></tr>
          <tr><td>良率</td><td class="n">{{ fmtYield(stats?.yield_pct ?? null) }}</td></tr>
          <tr><td>坐标列</td><td class="n">{{ coordCols }}</td></tr>
          <tr><td>die 尺寸</td><td class="n">{{ dieSize }}</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  zones: { name: string; total: number; pass: number; fail: number; yield: number | null }[]
  zoneError?: string
  stats: { total?: number; pass_count?: number; fail_count?: number; yield_pct?: number | null } | null
  xCol?: string
  yCol?: string
  dieSize?: number | null
}>()

const coordCols = computed(() =>
  props.xCol && props.yCol ? `${props.xCol} / ${props.yCol}` : '-')

const dieSize = computed(() =>
  props.dieSize != null && Number.isFinite(props.dieSize) ? String(props.dieSize) : '-')

function fmtYield(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '-'
  return `${v.toFixed(1)}%`
}

/* 预览稿口径：≥99.6% 绿、否则警示色；None（空区）不着色 */
function zoneYieldClass(v: number | null): Record<string, boolean> {
  if (v == null || !Number.isFinite(v)) return {}
  return { 'val-good': v >= 99.6, 'val-warn': v < 99.6 }
}
</script>

<style scoped>
.stat-card {
  background: var(--card);
  border: 1px solid var(--border-2);
  border-radius: 6px;
  overflow: hidden;
}
.stat-card-h {
  padding: 7px 10px;
  background: var(--bg-3);
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}
.stat-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.stat-table th,
.stat-table td {
  padding: 5px 8px;
  text-align: left;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  white-space: nowrap;
}
.stat-table th {
  color: var(--text-2);
  font-weight: 500;
  background: var(--bg-3);
}
.stat-table td.n,
.stat-table th.n {
  text-align: right;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.stat-table tbody tr:last-child td { border-bottom: 0; }
.stat-empty {
  color: var(--text-2);
  font-size: 11.5px;
}
.val-good { color: var(--success); }
.val-warn { color: var(--warn); }
.val-fail { color: var(--error); font-weight: 600; }
</style>
