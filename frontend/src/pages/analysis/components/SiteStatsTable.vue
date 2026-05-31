<template>
  <el-card shadow="hover" :body-style="{ padding: '8px' }">
    <div class="table-header">📱 Site统计</div>
    <el-table
      v-if="siteStats.length"
      :data="siteStats"
      size="small"
      :border="true"
      :header-cell-style="{ background: '#f5f5f5', fontSize: '10px', padding: '3px 2px' }"
      :cell-style="{ fontSize: '10px', padding: '3px 4px' }"
    >
      <el-table-column prop="Site" label="Site" min-width="55" align="center" show-overflow-tooltip />
      <el-table-column prop="Yield" label="Yield" min-width="60" align="center" show-overflow-tooltip />
      <el-table-column prop="FailCount" label="Fail" width="42" align="center" />
      <el-table-column prop="ExceedMin" label="&lt;Min" min-width="55" align="center" show-overflow-tooltip />
      <el-table-column prop="ExceedMax" label="&gt;Max" min-width="55" align="center" show-overflow-tooltip />
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
</script>

<style scoped>
.table-header {
  font-weight: 600;
  font-size: 12px;
  color: #303133;
  margin-bottom: 6px;
}

.error-msg {
  padding: 12px;
  color: #f5576c;
  font-size: 11px;
  text-align: center;
}
</style>
