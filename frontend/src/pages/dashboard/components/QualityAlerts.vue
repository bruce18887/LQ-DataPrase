<template>
  <div v-if="alerts.length" class="alerts-bar">
    <el-alert
      v-for="a in alerts"
      :key="a.type"
      :type="a.level"
      :title="a.message"
      :closable="false"
      show-icon
      class="alerts-bar-item"
    >
      <template v-if="a.params">
        <div class="alerts-detail">问题参数: {{ a.params.join(', ') }}</div>
      </template>
      <template v-if="a.max_site">
        <div class="alerts-detail">最高: {{ a.max_site }} | 最低: {{ a.min_site }}</div>
      </template>
    </el-alert>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  alerts: any[]
}>()
</script>

<style scoped>
/* ================================================================
   Alerts Bar
   ================================================================ */
.alerts-bar { margin-bottom: 20px; }
.alerts-bar-item { margin-bottom: 8px; }
.alerts-detail { font-size: 12px; margin-top: 4px; }
</style>
