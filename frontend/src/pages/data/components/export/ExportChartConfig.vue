<template>
  <div class="step-card">
    <div class="step-header">
      <span class="step-number">2</span>
      <span class="step-title">图表配置</span>
    </div>
    <div class="step-body">
      <el-checkbox-group :model-value="chartConfig" class="inline-checkboxes" @update:model-value="$emit('update:chartConfig', $event)">
        <el-checkbox value="limit">Limit</el-checkbox>
        <el-checkbox value="s3">3σ</el-checkbox>
        <el-checkbox value="s4">4σ</el-checkbox>
        <el-checkbox value="s6">6σ</el-checkbox>
        <el-checkbox value="normal">正态分布</el-checkbox>
        <el-checkbox value="kde">KDE曲线</el-checkbox>
      </el-checkbox-group>

      <div class="bar-width-group">
        <span class="bw-label">柱宽</span>
        <el-slider
          :model-value="barWidthPercent"
          :min="10"
          :max="100"
          :step="5"
          size="small"
          style="width: 120px"
          @update:model-value="$emit('update:barWidthPercent', $event)"
        />
        <span class="bw-value">{{ barWidthPercent }}%</span>
      </div>

      <el-checkbox :model-value="ignoreNoLimit" class="ignore-no-limit" @update:model-value="$emit('update:ignoreNoLimit', $event)">
        忽略无Limit
      </el-checkbox>
    </div>
  </div>
</template>

<script setup lang="ts">
interface Props {
  chartConfig: string[]
  barWidthPercent: number
  ignoreNoLimit: boolean
}

defineProps<Props>()
defineEmits<{
  (e: 'update:chartConfig', value: string[]): void
  (e: 'update:barWidthPercent', value: number): void
  (e: 'update:ignoreNoLimit', value: boolean): void
}>()
</script>

<style scoped>
.step-card {
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
}

.step-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.step-number {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--brand);
  color: var(--text-inverse);
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

.step-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.step-body {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}

.inline-checkboxes {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: wrap;
}

.inline-checkboxes :deep(.el-checkbox) {
  margin-right: 0;
  height: 28px;
  padding: 0 8px;
}

.inline-checkboxes :deep(.el-checkbox__label) {
  font-size: 12px;
  padding-left: 3px;
}

.ignore-no-limit {
  height: 28px;
}

.ignore-no-limit :deep(.el-checkbox__label) {
  font-size: 12px;
  padding-left: 3px;
}

.bar-width-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.bw-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-3);
}

.bw-value {
  font-size: 11px;
  font-weight: 700;
  color: var(--brand);
  font-family: var(--font-mono);
  min-width: 30px;
  text-align: right;
}

/* Brand-themed checkboxes */
:deep(.el-checkbox) {
  --el-checkbox-checked-bg-color: var(--brand);
  --el-checkbox-checked-input-border-color: var(--brand);
  --el-checkbox-checked-icon-color: var(--text-inverse);
}
</style>
