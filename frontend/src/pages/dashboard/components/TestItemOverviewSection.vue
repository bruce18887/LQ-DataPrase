<template>
  <div class="panel-card overview-card">
    <div class="panel-head panel-head--flex">
      <span class="panel-title">🔬 测试项总览</span>
      <span class="panel-desc">点击参数行跳转数据分析 · 表头全列可排序</span>
      <label class="ov-check">
        <input v-model="ignoreNoLimit" type="checkbox" /> 忽略无 Limit
      </label>
      <label class="ov-check">
        <input v-model="ignoreNoValue" type="checkbox" /> 忽略无测试值
      </label>
    </div>

    <!-- CPK 等级分布：一行四色堆叠比例条（取代饼图） -->
    <div v-if="cpkSegments.length" class="cpk-strip">
      <span
        v-for="seg in cpkSegments"
        :key="seg.level"
        class="cpk-seg"
        :class="`cpk-seg--${seg.level.toLowerCase()}`"
        :style="{ flex: seg.count }"
        :title="`${seg.label} ${seg.count} 项 · ${seg.pct}%`"
      >{{ seg.icon }} {{ seg.level }} · {{ seg.count }}</span>
    </div>

    <el-table
      :data="pagedRows"
      size="small"
      max-height="480"
      class="panel-table overview-table"
      @sort-change="handleSortChange"
      @row-click="goToAnalysis"
    >
      <el-table-column prop="name" label="参数名称" min-width="170" fixed="left" show-overflow-tooltip sortable="custom">
        <template #default="{ row }">
          <span class="cell-param">{{ row.name }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="data_count" label="数据点数" width="90" align="right" sortable="custom" />
      <el-table-column prop="mean" label="Mean" width="110" align="right" sortable="custom">
        <template #default="{ row }">
          <span v-if="row.mean !== null">{{ fmtNum(row.mean) }} <span class="cell-unit">{{ row.unit }}</span></span>
          <span v-else class="cell-na">N/A</span>
        </template>
      </el-table-column>
      <el-table-column prop="std" label="STD" width="100" align="right" sortable="custom">
        <template #default="{ row }">
          <span v-if="row.std !== null">{{ fmtNum(row.std) }}</span>
          <span v-else class="cell-na">N/A</span>
        </template>
      </el-table-column>
      <el-table-column prop="min" label="Min" width="100" align="right" sortable="custom">
        <template #default="{ row }">
          <span v-if="row.min !== null">{{ fmtNum(row.min) }}</span>
          <span v-else class="cell-na">N/A</span>
        </template>
      </el-table-column>
      <el-table-column prop="max" label="Max" width="100" align="right" sortable="custom">
        <template #default="{ row }">
          <span v-if="row.max !== null">{{ fmtNum(row.max) }}</span>
          <span v-else class="cell-na">N/A</span>
        </template>
      </el-table-column>
      <el-table-column prop="lsl" label="LSL" width="100" align="right" sortable="custom">
        <template #default="{ row }">
          <span v-if="row.lsl !== null">{{ fmtNum(row.lsl) }}</span>
          <span v-else class="cell-na">N/A</span>
        </template>
      </el-table-column>
      <el-table-column prop="usl" label="USL" width="100" align="right" sortable="custom">
        <template #default="{ row }">
          <span v-if="row.usl !== null">{{ fmtNum(row.usl) }}</span>
          <span v-else class="cell-na">N/A</span>
        </template>
      </el-table-column>
      <el-table-column prop="cpk" label="CPK" width="90" align="center" sortable="custom">
        <template #default="{ row }">
          <el-tag v-if="row.cpk !== null" :type="getCpkTagType(row.cpk)" size="small">{{ row.cpk.toFixed(2) }}</el-tag>
          <span v-else class="cell-na">N/A</span>
        </template>
      </el-table-column>
      <el-table-column prop="cpk_level" label="CPK Level" width="110" align="center" sortable="custom">
        <template #default="{ row }">
          <CpkBadge v-if="row.cpk_level" :level="row.cpk_level" />
          <span v-else class="cell-na">N/A</span>
        </template>
      </el-table-column>
      <!-- Fail 列：原「Fail数量 + Fail占比」合并为 `数量 (占比%)`（0 时显示 0） -->
      <el-table-column prop="fail_count" label="Fail" width="130" align="center" sortable="custom">
        <template #default="{ row }">
          <span v-if="row.fail_count > 0" class="cell-fail">{{ row.fail_count }} ({{ row.percentage }}%)</span>
          <span v-else class="cell-inactive">0</span>
        </template>
      </el-table-column>
    </el-table>
    <div class="overview-footer">
      <span class="overview-total">共 {{ filteredRows.length }} 项 · 点击参数行跳转数据分析页</span>
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="filteredRows.length"
        layout="total, prev, pager, next"
        background
        small
      />
    </div>

    <!-- Top 10 Fail 测试项：信息 chip 行（取代柱状图），点击跳转数据分析 -->
    <template v-if="topFailChips.length">
      <div class="ov-sub">🔥 Top 10 Fail 测试项 <span>信息形式 · 点击跳转分析</span></div>
      <div class="fail-chips">
        <button
          v-for="chip in topFailChips"
          :key="chip.name"
          type="button"
          class="fail-chip"
          @click="goToAnalysis(chip)"
        >{{ chip.name }} · {{ chip.fail_count }} ({{ chip.percentage }}%)</button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAnalysisStore } from '../../../stores/analysis'
import type { TestItemOverview } from '../../../types'
import CpkBadge from '../../../components/common/CpkBadge.vue'

const props = defineProps<{
  items: TestItemOverview[]
  fileId: number | null
}>()

const router = useRouter()
const analysisStore = useAnalysisStore()

const sortKey = ref<string | null>(null)
const sortOrder = ref<'ascending' | 'descending' | null>(null)
const page = ref(1)
const pageSize = 100  // 固定 100 条/页，不提供切换
// 卡头双复选框（用户定稿）：行级过滤，默认勾选
const ignoreNoLimit = ref(true)
const ignoreNoValue = ref(true)

/** 行级过滤：无 Limit（LSL/USL 皆缺）/ 无测试值（mean 缺失） */
const filteredRows = computed(() => {
  let list = props.items
  if (ignoreNoLimit.value) list = list.filter((r) => r.lsl !== null || r.usl !== null)
  if (ignoreNoValue.value) list = list.filter((r) => r.mean !== null)
  return list
})

const sortedRows = computed(() => {
  const list = [...filteredRows.value]  // 默认保持后端原始测试项顺序
  if (!sortKey.value || !sortOrder.value) return list
  const dir = sortOrder.value === 'ascending' ? 1 : -1
  list.sort((a, b) => {
    const va = (a as any)[sortKey.value!]
    const vb = (b as any)[sortKey.value!]
    if (va == null) return 1   // null 恒排最后
    if (vb == null) return -1
    if (typeof va === 'number') return (va - vb) * dir
    return String(va).localeCompare(String(vb)) * dir
  })
  return list
})

const pagedRows = computed(() => {
  const start = (page.value - 1) * pageSize
  return sortedRows.value.slice(start, start + pageSize)
})

/** CPK 等级分布（A✓ 绿 / B● 品牌 / C◆ 琥珀 / D▼ 红，段宽按计数比例） */
const CPK_META: Record<string, { icon: string; label: string }> = {
  A: { icon: '✓', label: 'A 级' },
  B: { icon: '●', label: 'B 级' },
  C: { icon: '◆', label: 'C 级' },
  D: { icon: '▼', label: 'D 级' },
}
const cpkSegments = computed(() => {
  const counts: Record<string, number> = {}
  for (const r of props.items) {
    const lv = (r.cpk_level || '').trim().charAt(0).toUpperCase()
    if (lv && CPK_META[lv]) counts[lv] = (counts[lv] || 0) + 1
  }
  const total = Object.values(counts).reduce((s, n) => s + n, 0)
  return ['A', 'B', 'C', 'D']
    .filter((lv) => counts[lv])
    .map((lv) => ({
      level: lv,
      icon: CPK_META[lv].icon,
      label: CPK_META[lv].label,
      count: counts[lv],
      pct: total > 0 ? ((counts[lv] / total) * 100).toFixed(1) : '0',
    }))
})

/** Top 10 Fail 信息 chip（降序，与表格行点击同源交互） */
const topFailChips = computed(() =>
  props.items
    .filter((t) => t.fail_count > 0)
    .sort((a, b) => b.fail_count - a.fail_count)
    .slice(0, 10)
)

function handleSortChange({ prop, order }: { prop: string; order: 'ascending' | 'descending' | null }) {
  sortKey.value = order ? prop : null
  sortOrder.value = order
  page.value = 1  // 排序变更重置到第一页
}

function goToAnalysis(row: TestItemOverview) {
  if (!props.fileId) return
  analysisStore.selectedFileId = props.fileId
  analysisStore.selectedParam = row.name
  analysisStore.activeTab = 'single-param'
  analysisStore.chartMode = 'distribution'
  router.push('/analysis')
}

function fmtNum(v: number): string {
  return v.toFixed(4)
}

function getCpkTagType(cpk: number): string {
  if (cpk >= 1.67) return 'success'
  if (cpk >= 1.33) return 'warning'
  return 'danger'
}
</script>

<style scoped>
/* ================================================================
   Section 卡（§10.4 定稿：浅底带卡头）
   ================================================================ */
.panel-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: var(--shadow-sm);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13.5px;
  font-weight: 700;
  color: var(--text);
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg-2) 60%, var(--card));
  flex-shrink: 0;
}
.panel-head--flex {
  flex-wrap: wrap;
}
.panel-title {
  font-size: 13.5px;
  font-weight: 700;
}
.panel-desc {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-3);
}
.panel-table {
  flex: 1;
  min-height: 0;
}

/* ================================================================
   卡头双复选框（行级过滤）
   ================================================================ */
.ov-check {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-left: auto;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-2);
  cursor: pointer;
  white-space: nowrap;
}
.ov-check + .ov-check { margin-left: 4px; }
.ov-check input {
  accent-color: var(--brand);
  width: 14px;
  height: 14px;
  cursor: pointer;
}

/* ================================================================
   CPK 等级堆叠比例条
   ================================================================ */
.cpk-strip {
  display: flex;
  height: 22px;
  margin: 12px 16px 0;
  border-radius: 6px;
  overflow: hidden;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-inverse);
  box-shadow: var(--shadow-sm);
}
.cpk-seg {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 3px;
  white-space: nowrap;
  overflow: hidden;
  font-variant-numeric: tabular-nums;
  cursor: default;
}
.cpk-seg--a { background: var(--success); }
.cpk-seg--b { background: var(--brand); }
.cpk-seg--c { background: var(--warn); }
.cpk-seg--d { background: var(--error); }

/* ================================================================
   Overview specifics
   ================================================================ */
.overview-card {
  margin-bottom: 14px;
}
.overview-table :deep(.el-table__row) {
  cursor: pointer;
}
.cell-param {
  color: var(--brand);
  font-weight: 600;
}
.cell-param:hover {
  text-decoration: underline;
}
.cell-fail {
  color: var(--error);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.cell-inactive {
  color: var(--text-3);
}
.cell-na {
  color: var(--text-3);
}
.cell-unit {
  color: var(--text-3);
  font-size: 11px;
}
.overview-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border-top: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg-2) 60%, var(--card));
}
.overview-total {
  font-size: 12px;
  color: var(--text-2);
}

/* ================================================================
   Top 10 Fail 信息 chip 行
   ================================================================ */
.ov-sub {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin: 14px 16px 0;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text);
}
.ov-sub span {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-3);
}
.fail-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin: 8px 16px 14px;
}
.fail-chip {
  font: inherit;
  font-size: 11.5px;
  font-weight: 600;
  padding: 3px 10px;
  border: none;
  border-radius: 999px;
  background: color-mix(in srgb, var(--error) 10%, transparent);
  color: var(--error);
  cursor: pointer;
  font-variant-numeric: tabular-nums;
}
.fail-chip:hover {
  background: color-mix(in srgb, var(--error) 18%, transparent);
}
</style>
