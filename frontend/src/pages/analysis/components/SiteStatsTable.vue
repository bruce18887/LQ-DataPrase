<template>
  <el-card shadow="hover" :body-style="{ padding: '8px' }">
    <div class="table-header">📱 Site统计</div>
    <el-table
      v-if="siteStats.length"
      :data="siteStats"
      size="small"
      :border="true"
      scrollbar-always-on
      :row-class-name="siteRowClass"
      :header-cell-style="{ background: 'var(--bg-3)', fontSize: '10px', padding: '3px 6px', whiteSpace: 'nowrap' }"
      :cell-style="{ fontSize: '10px', padding: '3px 6px', whiteSpace: 'nowrap' }"
      table-layout="auto"
    >
      <el-table-column prop="Site" label="Site" align="center" min-width="65" />
      <el-table-column prop="Yield" label="Yield" align="center" min-width="75" />
      <el-table-column prop="FailCount" label="Fail" align="center" min-width="55" />
      <el-table-column prop="ExceedMin" label="&lt;Min" align="center" min-width="60" />
      <el-table-column prop="ExceedMax" label="&gt;Max" align="center" min-width="60" />
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
  FailCount: string | number
  ExceedMin: string | number
  ExceedMax: string | number
  /** 数字字段（后端下发，供行样式等逻辑使用；展示用字符串在上面） */
  FailCountNum?: number
}

interface Props {
  siteStats: SiteStatRow[]
  siteStatsError: string
}

defineProps<Props>()

function siteRowClass({ row }: { row: SiteStatRow }) {
  return (row.FailCountNum ?? 0) > 0 ? 'site-fail-row' : ''
}
</script>

<style scoped>
.table-header {
  font-weight: 600;
  font-size: 12px;
  color: var(--text);
  margin-bottom: 6px;
}

.error-msg {
  padding: 12px;
  color: var(--error-2);
  font-size: 11px;
  text-align: center;
}

/* 有 Fail 的行高亮：scoped + 特指到 td.el-table__cell（含 hover 态），
   天然压过 EP 的单元格底色，故不再需要全局块与 !important（R7） */
:deep(.el-table tr.site-fail-row > td.el-table__cell),
:deep(.el-table tr.site-fail-row:hover > td.el-table__cell) {
  background-color: color-mix(in srgb, var(--error) 12%, transparent);
  color: var(--error);
  font-weight: 700;
}
</style>
