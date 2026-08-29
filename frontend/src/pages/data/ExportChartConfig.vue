<template>
  <div class="chart-config-panel">
    <div class="panel-header">
      <span class="panel-icon">⚙️</span>
      <span class="panel-title">图表配置</span>
    </div>

    <div class="panel-body">
      <!-- Overlay Lines -->
      <div class="config-group">
        <span class="group-label">叠加线条</span>
        <el-checkbox-group :model-value="chartConfig" @change="onChartConfigChange" aria-label="图表配置选项" class="checkbox-row">
          <el-checkbox value="limit">Limit</el-checkbox>
          <el-checkbox value="s3">3σ</el-checkbox>
          <el-checkbox value="s4">4σ</el-checkbox>
          <el-checkbox value="s6">6σ</el-checkbox>
          <el-checkbox value="normal">正态分布</el-checkbox>
        </el-checkbox-group>
      </div>

      <!-- Bar Width -->
      <div class="config-group">
        <div class="group-header">
          <span class="group-label">柱宽</span>
          <span class="value-tag">{{ barWidthPercent }}%</span>
        </div>
        <el-slider
          :model-value="barWidthPercent"
          :min="10"
          :max="100"
          :step="5"
          size="small"
          @change="onBarWidthChange"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
interface Props {
  chartConfig: string[]
  barWidthPercent: number
}

defineProps<Props>()

const emit = defineEmits<{
  (e: 'update:chartConfig', val: string[]): void
  (e: 'update:barWidthPercent', val: number): void
}>()

function onChartConfigChange(val: string[]) {
  emit('update:chartConfig', val)
}

function onBarWidthChange(val: number) {
  emit('update:barWidthPercent', val)
}
</script>

<style scoped>
.chart-config-panel {
  width: 220px;
  flex-shrink: 0;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  overflow: hidden;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
}

.panel-icon {
  font-size: 14px;
}

.panel-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.panel-body {
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.config-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.group-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.group-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.value-tag {
  font-size: 11px;
  font-weight: 700;
  color: var(--brand);
  font-family: var(--font-mono);
}

.checkbox-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.checkbox-row :deep(.el-checkbox) {
  margin-right: 0;
  height: 24px;
}

.checkbox-row :deep(.el-checkbox__label) {
  font-size: 12px;
  padding-left: 4px;
}

/* ============================
   Night Theme Overrides
   ============================ */
:root[data-theme="night"] .chart-config-panel {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.08);
}

:root[data-theme="night"] .panel-header {
  border-color: rgba(255, 255, 255, 0.06);
}
</style>
