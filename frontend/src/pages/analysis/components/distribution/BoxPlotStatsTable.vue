<!-- frontend/src/pages/analysis/components/distribution/BoxPlotStatsTable.vue -->
<template>
  <el-card v-if="rows.length" shadow="hover" class="boxplot-stats-table" :body-style="{ padding: '8px' }">
    <div class="table-header">📊 箱线图统计</div>
    <el-table
      :data="rows"
      size="small"
      :border="true"
      :header-cell-style="{ background: 'var(--bg-3)', fontSize: '10px', padding: '3px 6px', whiteSpace: 'nowrap' }"
      :cell-style="{ fontSize: '10px', padding: '3px 6px', whiteSpace: 'nowrap' }"
      table-layout="auto"
    >
      <el-table-column prop="grp" label="组" align="center" />
      <el-table-column prop="whisker" label="须端" align="center" />
      <el-table-column prop="q1" label="Q1" align="center" />
      <el-table-column prop="median" label="中位" align="center" />
      <el-table-column prop="q3" label="Q3" align="center" />
    </el-table>
    <div class="table-note">须端 = 围栏内（非离群）最小/最大值，非绝对 Min/Max</div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface BoxGroup {
  min: number | null; q1: number | null; median: number | null; q3: number | null; max: number | null
  outliers?: number[]; count?: number
}
interface BoxPlotData {
  overall?: BoxGroup; by_site?: Record<string, BoxGroup>; by_bin?: Record<string, BoxGroup>
}

const props = defineProps<{ data: BoxPlotData | null; groupBy?: string }>()

// 后端 NaN→JSON null：分组字段可能为 null（如过滤后计数为 0）。
// 裸 .toFixed 会 TypeError 打断渲染，统一走 fmt 兜底（对齐 OutlierHintBar / QQPlotStatsTable）
const fmt = (v: unknown): string =>
  typeof v === 'number' && Number.isFinite(v) ? v.toFixed(4) : '-'

const ok = (g?: BoxGroup | null): g is BoxGroup =>
  !!g && typeof g.min === 'number' && Number.isFinite(g.min)

// 数值 key 加 Site/Bin 前缀，非数值 key 原样（与 BoxPlotChart 类目命名一致）
const labelOf = (key: string, prefix: string) =>
  /^\d+(\.\d+)?$/.test(key) ? `${prefix} ${key}` : key

const sortNum = (a: string, b: string): number => {
  const na = parseFloat(a), nb = parseFloat(b)
  if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb
  return a.localeCompare(b)
}

const rows = computed(() => {
  const d = props.data
  if (!d) return []
  let list: { label: string; g: BoxGroup }[] = []
  if (props.groupBy === 'site' && d.by_site) {
    list = Object.keys(d.by_site).sort(sortNum).map(k => ({ label: labelOf(k, 'Site'), g: d.by_site![k] }))
  } else if (props.groupBy === 'bin' && d.by_bin) {
    list = Object.keys(d.by_bin).sort(sortNum).map(k => ({ label: labelOf(k, 'Bin'), g: d.by_bin![k] }))
  } else if (d.overall) {
    list = [{ label: 'All', g: d.overall }]
  }
  // 分组结果为空（如单 Site 文件未回 by_site）→ 回退 overall 单行，避免整表不渲染
  if (!list.some(r => ok(r.g)) && d.overall && ok(d.overall)) {
    list = [{ label: 'All', g: d.overall }]
  }
  // 全 null 组整组剔除、不占行（对齐图侧 groupOk 口径）
  return list
    .filter(r => ok(r.g))
    .map(r => ({
      grp: `${r.label} · n=${r.g.count ?? '-'}`,
      whisker: `${fmt(r.g.min)}–${fmt(r.g.max)}`,
      q1: fmt(r.g.q1),
      median: fmt(r.g.median),
      q3: fmt(r.g.q3),
    }))
})
</script>

<style scoped>
.table-header {
  font-weight: 600;
  font-size: 12px;
  color: var(--text);
  margin-bottom: 6px;
}
.table-note {
  margin-top: 4px;
  font-size: 10px;
  line-height: 1.3;
  color: var(--text-3);
}
</style>
