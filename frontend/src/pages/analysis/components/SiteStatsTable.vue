<template>
  <el-card shadow="hover" :body-style="{ padding: '8px' }">
    <div class="table-header">📱 Site统计</div>
    <el-table
      v-if="siteStats.length"
      :data="siteStats"
      size="small"
      :border="true"
      :row-class-name="siteRowClass"
      :header-cell-style="{ background: '#f5f5f5', fontSize: '10px', padding: '3px 6px', whiteSpace: 'nowrap' }"
      :cell-style="{ fontSize: '10px', padding: '3px 6px', whiteSpace: 'nowrap' }"
      table-layout="auto"
    >
      <el-table-column prop="Site" label="Site" align="center" />
      <el-table-column prop="Yield" label="Yield" align="center" />
      <el-table-column prop="FailCount" label="Fail" align="center" />
      <el-table-column prop="ExceedMin" label="&lt;Min" align="center" />
      <el-table-column prop="ExceedMax" label="&gt;Max" align="center" />
    </el-table>
    <el-empty v-else-if="!siteStatsError" description="暂无数据" :image-size="40" />
    <div v-else class="error-msg">
      {{ siteStatsError }}
    </div>
  </el-card>
</template>

<script setup lang="ts">
interface SiteStatRow {
  Site: string | number
  Yield: string | number
  FailCount: number
  ExceedMin: number
  ExceedMax: number
}

interface Props {
  siteStats: SiteStatRow[]
  siteStatsError: string
}

defineProps<Props>()

function siteRowClass({ row }: { row: SiteStatRow }) {
  return row.FailCount > 0 ? 'site-fail-row' : ''
}
</script>

<style scoped>
.table-header {
  font-weight: 600;
  font-size: 12px;
  color: var(--text-primary);
  margin-bottom: 6px;
}

.error-msg {
  padding: 12px;
  color: #f5576c;
  font-size: 11px;
  text-align: center;
}
</style>

<style>
.el-table tr.site-fail-row > td {
  background-color: #fdecea !important;
  color: #dc2626 !important;
  font-weight: 700;
  text-shadow: 0 0 1px #fff, 0 0 2px #fff;
}
:root.theme-night .el-table tr.site-fail-row > td {
  background-color: rgba(245, 87, 108, 0.28) !important;
  color: #ff8a95 !important;
  font-weight: 700;
  text-shadow: 0 0 1px #1a1a2e, 0 0 2px #1a1a2e;
}
</style>
