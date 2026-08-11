<template>
  <div>
    <h2 class="sec-title"><span>📋</span> 测试项总览</h2>
    <div class="panel-card overview-card">
      <div class="panel-head">📋 测试项总览（点击参数行跳转数据分析）</div>
      <el-table
        :data="pagedRows"
        stripe
        size="small"
        border
        max-height="480"
        class="panel-table overview-table"
        @sort-change="handleSortChange"
        @row-click="goToAnalysis"
      >
        <el-table-column prop="name" label="参数名称" min-width="170" fixed="left" show-overflow-tooltip>
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
            <span v-if="row.cpk_level" :style="{ color: row.cpk_color, fontWeight: 'bold' }">{{ row.cpk_level }}</span>
            <span v-else class="cell-na">N/A</span>
          </template>
        </el-table-column>
        <el-table-column prop="fail_count" label="Fail数量" width="90" align="center" sortable="custom">
          <template #default="{ row }">
            <span v-if="row.fail_count > 0" class="cell-fail">{{ row.fail_count }}</span>
            <span v-else class="cell-inactive">0</span>
          </template>
        </el-table-column>
        <el-table-column prop="percentage" label="Fail占比" width="90" align="center" sortable="custom">
          <template #default="{ row }">
            <span v-if="row.percentage > 0" class="cell-fail">{{ row.percentage }}%</span>
            <span v-else class="cell-inactive">0%</span>
          </template>
        </el-table-column>
      </el-table>
      <div class="overview-footer">
        <span class="overview-total">共 {{ items.length }} 项 · 点击参数行跳转数据分析页</span>
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="items.length"
          layout="total, prev, pager, next"
          background
          small
        />
      </div>
    </div>

    <OverviewCharts :items="items" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAnalysisStore } from '../../../stores/analysis'
import type { TestItemOverview } from '../../../types'
import OverviewCharts from './OverviewCharts.vue'

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

const sortedRows = computed(() => {
  const list = [...props.items]  // 默认保持后端原始测试项顺序
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
   Section Title
   ================================================================ */
.sec-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 17px;
  font-weight: 700;
  color: #1f2937;
  margin: 24px 0 12px 0;
  padding-left: 10px;
  border-left: 3px solid #2563eb;
  line-height: 1;
}

/* ================================================================
   Panel Card（复用类名，夜间主题由 DashboardPage 全局覆盖）
   ================================================================ */
.panel-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,.04);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel-head {
  font-size: 14px;
  font-weight: 650;
  color: #374151;
  padding: 10px 16px;
  border-bottom: 1px solid #f3f4f6;
  background: #fafbfc;
  flex-shrink: 0;
}
.panel-table {
  flex: 1;
  min-height: 0;
}

/* ================================================================
   Overview specifics
   ================================================================ */
.overview-card {
  margin-bottom: 20px;
}
.overview-table :deep(.el-table__row) {
  cursor: pointer;
}
.cell-param {
  color: #2563eb;
  font-weight: 600;
}
.cell-param:hover {
  text-decoration: underline;
}
.cell-fail {
  color: #dc2626;
  font-weight: 700;
}
.cell-inactive {
  color: #9ca3af;
}
.cell-na {
  color: #9ca3af;
}
.cell-unit {
  color: #9ca3af;
  font-size: 11px;
}
.overview-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border-top: 1px solid #f3f4f6;
  background: #fafbfc;
}
.overview-total {
  font-size: 12px;
  color: #6b7280;
}
</style>
