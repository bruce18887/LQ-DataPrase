<template>
  <div class="kpi-row">
    <div class="kpi-card kpi-card--blue">
      <div class="kpi-icon" aria-hidden="true">📋</div>
      <div class="kpi-label">总记录数</div>
      <div class="kpi-value">{{ metrics.total_rows?.toLocaleString() }}</div>
    </div>
    <div class="kpi-card kpi-card--green">
      <div class="kpi-icon" aria-hidden="true">✅</div>
      <div class="kpi-label">Pass 数量</div>
      <div class="kpi-value">{{ metrics.pass_count?.toLocaleString() }}</div>
    </div>
    <div class="kpi-card kpi-card--amber">
      <div class="kpi-icon" aria-hidden="true">📈</div>
      <div class="kpi-label">Yield</div>
      <div class="kpi-value">{{ metrics.yield_pct?.toFixed(2) }}<span class="kpi-unit">%</span></div>
      <div class="kpi-sub">Fail: {{ metrics.fail_count?.toLocaleString() }}</div>
    </div>
    <div class="kpi-card kpi-card--slate">
      <div class="kpi-icon" aria-hidden="true">🔧</div>
      <div class="kpi-label">数据格式</div>
      <el-tag effect="dark" round size="small" type="info" class="kpi-tag">{{ metrics.format }}</el-tag>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  metrics: {
    total_rows: number
    pass_count: number
    fail_count: number
    yield_pct: number
    format: string
  }
}>()
</script>

<style scoped>
/* ================================================================
   KPI Cards — 4-column grid
   ================================================================ */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 20px;
}
@media (max-width: 992px) { .kpi-row { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 576px) { .kpi-row { grid-template-columns: 1fr; } }

.kpi-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 18px 16px 14px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  min-height: 112px;
  position: relative;
  overflow: hidden;
  transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease;
  box-shadow: 0 1px 3px rgba(0,0,0,.04);
}
@media (prefers-reduced-motion: reduce) {
  .kpi-card { transition: none; }
}
.kpi-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(0,0,0,.08);
}
/* Top accent bar — invisible until hover */
.kpi-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  border-radius: 10px 10px 0 0;
  transform: scaleX(0);
  transform-origin: left;
  transition: transform .25s ease;
}
.kpi-card:hover::before { transform: scaleX(1); }

.kpi-card--blue  { --kpi-accent: #2563eb; }
.kpi-card--green { --kpi-accent: #059669; }
.kpi-card--amber { --kpi-accent: #d97706; }
.kpi-card--slate { --kpi-accent: #4b5563; }
.kpi-card--blue::before  { background: linear-gradient(90deg, #1d4ed8, #3b82f6); }
.kpi-card--green::before { background: linear-gradient(90deg, #047857, #10b981); }
.kpi-card--amber::before { background: linear-gradient(90deg, #b45309, #f59e0b); }
.kpi-card--slate::before { background: linear-gradient(90deg, #374151, #6b7280); }

.kpi-card:hover { border-color: var(--kpi-accent, #2563eb); }

.kpi-icon   { font-size: 22px; line-height: 1; }
.kpi-label  { font-size: 12px; color: #6b7280; font-weight: 500; text-transform: uppercase; letter-spacing: .4px; }
.kpi-value  { font-size: 28px; font-weight: 700; color: #111827; line-height: 1.15; }
.kpi-unit   { font-size: 16px; font-weight: 600; color: #6b7280; margin-left: 1px; }
.kpi-sub    { font-size: 11px; color: #9ca3af; margin-top: 1px; }
.kpi-tag    { margin-top: 4px; }
</style>
