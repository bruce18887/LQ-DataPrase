<template>
  <div>
    <h2 class="sec-title"><span>🔍</span> 数据质量概览</h2>
    <div class="summary-row">
      <div class="summary-card summary-card--blue">
        <h4>📊 测试项统计</h4>
        <p>数值测试项: <b>{{ quality.numeric_items }}</b></p>
        <p>有 Limit 测试项: <b>{{ quality.items_with_limits }}</b></p>
        <p>Site 数量: <b>{{ quality.site_count }}</b></p>
      </div>
      <div class="summary-card summary-card--red">
        <h4>🎯 Bin 分布</h4>
        <p>Bin 种类: <b>{{ quality.bin_types }}</b></p>
        <p>Fail Bin: <b>{{ quality.fail_bin_count }}</b></p>
        <p>Pass 率: <b>{{ metrics.yield_pct?.toFixed(2) }}%</b></p>
      </div>
      <div class="summary-card summary-card--green">
        <h4>⚠️ 关键问题</h4>
        <p>Top Fail 项: <b>{{ topFailItem }}</b></p>
        <p>Fail 次数: <b>{{ topFailCount }}</b></p>
        <p>总 Fail 项: <b>{{ failTestItemsLength }}</b></p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  quality: {
    numeric_items: number
    items_with_limits: number
    site_count: number
    bin_types: number
    fail_bin_count: number
  }
  metrics: {
    yield_pct: number
  }
  topFailItem: string
  topFailCount: number
  failTestItemsLength: number
}>()
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
  color: var(--text);
  margin: 24px 0 12px 0;
  padding-left: 10px;
  border-left: 3px solid var(--brand);
  line-height: 1;
}

/* ================================================================
   Summary Cards (数据质量概览)
   ================================================================ */
.summary-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-bottom: 20px;
}
@media (max-width: 768px) { .summary-row { grid-template-columns: 1fr; } }

.summary-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 18px 20px;
  border-left: 3px solid var(--brand);
  transition: transform .2s ease, box-shadow .2s ease;
}
.summary-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0,0,0,.06);
}
.summary-card h4 {
  margin: 0 0 10px 0;
  font-size: 14px;
  font-weight: 650;
}
.summary-card p {
  margin: 6px 0;
  font-size: 13px;
  color: var(--text-2);
}
.summary-card p b {
  color: var(--text);
}
.summary-card--blue  { border-left-color: var(--brand); }
.summary-card--blue  h4 { color: var(--brand); }
.summary-card--red   { border-left-color: var(--error-2); }
.summary-card--red   h4 { color: var(--error-2); }
.summary-card--green { border-left-color: var(--success); }
.summary-card--green h4 { color: var(--success); }
</style>
