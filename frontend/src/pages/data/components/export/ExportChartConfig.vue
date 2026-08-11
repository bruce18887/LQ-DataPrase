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

      <div v-if="!nativeChart" class="bar-width-group">
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

      <div class="native-chart-group">
        <el-checkbox :model-value="nativeChart" class="native-chart" @update:model-value="$emit('update:nativeChart', $event)">
          Excel 原生图表
        </el-checkbox>
        <el-tooltip placement="top" :width="300">
          <template #content>
            <div class="native-help-content">
              <div class="native-help-title">Excel 原生图表（demo）</div>
              <div class="native-help-line">1. 生成 Excel 内置图表（非图片），文件体积更小；</div>
              <div class="native-help-line">2. 导出后可在 Excel 中直接编辑图表样式；</div>
              <div class="native-help-line">3. 柱宽由 Excel 自动控制，柱宽滑块将隐藏。</div>
            </div>
          </template>
          <el-icon class="native-help-icon"><QuestionFilled /></el-icon>
        </el-tooltip>
      </div>

      <el-checkbox :model-value="ignoreNoLimit" class="ignore-no-limit" @update:model-value="$emit('update:ignoreNoLimit', $event)">
        忽略无Limit
      </el-checkbox>
    </div>
  </div>
</template>

<script setup lang="ts">
import { QuestionFilled } from '@element-plus/icons-vue'

interface Props {
  chartConfig: string[]
  barWidthPercent: number
  ignoreNoLimit: boolean
  nativeChart: boolean
}

defineProps<Props>()
defineEmits<{
  (e: 'update:chartConfig', value: string[]): void
  (e: 'update:barWidthPercent', value: number): void
  (e: 'update:ignoreNoLimit', value: boolean): void
  (e: 'update:nativeChart', value: boolean): void
}>()
</script>

<style scoped>
.step-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-muted);
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
  background: var(--brand-primary);
  color: var(--text-inverse);
  font-size: 12px;
  font-weight: 700;
  flex-shrink: 0;
}

.step-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
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

.ignore-no-limit,
.native-chart {
  height: 28px;
}

.native-chart-group {
  display: flex;
  align-items: center;
  gap: 4px;
}

.native-help-icon {
  font-size: 13px;
  color: var(--text-tertiary);
  cursor: help;
  transition: color 0.2s;
}

.native-help-icon:hover {
  color: var(--brand-primary);
}

.native-help-content {
  max-width: 280px;
}

.native-help-title {
  font-weight: 600;
  margin-bottom: 4px;
}

.native-help-line {
  font-size: 12px;
  line-height: 1.7;
}

.ignore-no-limit :deep(.el-checkbox__label),
.native-chart :deep(.el-checkbox__label) {
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
  color: var(--text-tertiary);
}

.bw-value {
  font-size: 11px;
  font-weight: 700;
  color: var(--brand-primary);
  font-family: var(--font-mono);
  min-width: 30px;
  text-align: right;
}

/* Brand-themed checkboxes */
:deep(.el-checkbox) {
  --el-checkbox-checked-bg-color: var(--brand-primary);
  --el-checkbox-checked-input-border-color: var(--brand-primary);
  --el-checkbox-checked-icon-color: var(--text-inverse);
}
</style>
