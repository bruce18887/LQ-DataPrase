<template>
  <el-card shadow="hover" :body-style="{ padding: '12px' }">
    <div class="config-header">
      <span class="config-title">⚙️ 图表显示</span>
    </div>

    <!-- 图表元素开关 -->
    <div class="config-section">
      <div class="section-label">显示元素</div> 
      <el-checkbox-group :model-value="chartConfig" @change="onChartConfigChange" class="config-checkboxes">
        <el-checkbox value="limit">Limit</el-checkbox>
        <template v-if="variant === 'full'">
          <el-checkbox value="s3">3σ线</el-checkbox>
          <el-checkbox value="s4">4σ线</el-checkbox>
          <el-checkbox value="s6">6σ线</el-checkbox>
          <el-checkbox value="kde">KDE曲线</el-checkbox>
          <el-checkbox value="kde_full">KDE含超限</el-checkbox>
        </template>
        <el-checkbox value="normal">正态分布</el-checkbox>
        <el-checkbox v-if="variant === 'multi-file'" value="kde">KDE曲线</el-checkbox>
      </el-checkbox-group>
    </div>

    <!-- 范围类型（仅单参数完整版） -->
    <div v-if="variant === 'full'" class="config-section">
      <div class="section-label">范围类型</div>
      <el-select :model-value="rangeType" size="small" style="width: 100%" @change="onRangeTypeChange">
        <el-option label="RowDataLimit" value="RDL" />
        <el-option label="Data Range" value="DR" />
        <el-option label="CustomLimit" value="CL" />
        <el-option label="3 Sigma" value="S3" />
        <el-option label="4 Sigma" value="S4" />
        <el-option label="6 Sigma" value="S6" />
      </el-select>
    </div>

    <!-- CustomLimit 输入 -->
    <div v-if="variant === 'full' && rangeType === 'CL'" class="config-section custom-limit-section">
      <div class="section-label">自定义范围</div>
      <div class="custom-limit-inputs">
        <el-input-number
          :model-value="customLow"
          placeholder="下限"
          size="small"
          :precision="6"
          :controls="false"
          style="flex: 1"
          @change="onCustomLowChange"
        />
        <span class="limit-sep">~</span>
        <el-input-number
          :model-value="customHigh"
          placeholder="上限"
          size="small"
          :precision="6"
          :controls="false"
          style="flex: 1"
          @change="onCustomHighChange"
        />
      </div>
    </div>

    <!-- 柱状图宽度：仅多文件分析版（单文件版的柱宽/柱体重合已移入直布图标题栏
         齿轮面板，2026-09-13 工具栏齿轮化） -->
    <div v-if="variant === 'multi-file'" class="config-section">
      <div class="section-label flex-between">
        <span>柱宽</span>
        <span class="value-hint">{{ displayBarWidth }}%</span>
      </div>
      <!-- 必须监听 update:modelValue：EP slider 的值更新走 update:modelValue，
           change 事件发出的是 props.modelValue（单向绑定下永远是旧值）——
           此前只绑 @change 导致柱宽设置永远无效 -->
      <!-- max 随系列数联动（barWidthMax）：多系列并排柱组必须 ≤ bin 宽，
           否则贴限柱体越过 USL 线（回归 limit-line-cross）；min/step 从 10/5
           收窄到 1/1 以适配 8-site 时上限 ≈9% -->
      <el-slider :model-value="displayBarWidth" :min="1" :max="barWidthMax" :step="1" size="small" @update:model-value="onBarWidthChange" />
    </div>

    <!-- 数据筛选与异常值处理已移到 DataFilterSection（每 tab 一份，2026-09-05） -->
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  chartConfig: string[]
  rangeType: string
  /** 柱宽（%）：仅 multi-file 变体消费；full 变体不需要（已移入直方图齿轮面板） */
  barWidthPercent?: number
  /** 柱宽 slider 上限（%）：随系列数联动（多系列并排柱组 ≤ bin 宽） */
  barWidthMax?: number
  customLow?: number | null
  customHigh?: number | null
  /** 'full' = 单参数分析完整配置；'multi-file' = 多文件分析阉割版（仅 Limit + 柱宽） */
  variant?: 'full' | 'multi-file'
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'full',
  barWidthPercent: 20,
  barWidthMax: 100,
})

const emit = defineEmits<{
  (e: 'update:chartConfig', val: string[]): void
  (e: 'update:rangeType', val: string): void
  (e: 'update:barWidthPercent', val: number): void
  (e: 'update:customLow', val: number | null): void
  (e: 'update:customHigh', val: number | null): void
}>()

/** slider 显示值：柱宽被系列数上限 clamp（多系列并排柱组 ≤ bin 宽） */
const displayBarWidth = computed(() => Math.min(props.barWidthPercent, props.barWidthMax))

function onChartConfigChange(val: string[]) {
  emit('update:chartConfig', val)
}

function onRangeTypeChange(val: string) {
  emit('update:rangeType', val)
}

function onBarWidthChange(val: number) {
  emit('update:barWidthPercent', val)
}

function onCustomLowChange(val: number | null) {
  emit('update:customLow', val)
}

function onCustomHighChange(val: number | null) {
  emit('update:customHigh', val)
}
</script>

<style scoped>
.config-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.config-title {
  font-weight: 600;
  font-size: 13px;
  color: var(--text);
}

.config-section {
  margin-bottom: 10px;
}

.config-section:last-child {
  margin-bottom: 0;
}

.section-label {
  font-size: 11px;
  color: var(--text-2);
  margin-bottom: 4px;
  font-weight: 500;
}

.flex-between {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.value-hint {
  font-size: 11px;
  color: var(--text);
  font-weight: 600;
}

.config-checkboxes {
  display: flex;
  flex-wrap: wrap;
  gap: 0 12px;
}

.config-checkboxes :deep(.el-checkbox) {
  margin-right: 0;
  height: 24px;
}

.config-checkboxes :deep(.el-checkbox__label) {
  font-size: 12px;
  padding-left: 4px;
}

.custom-limit-section {
  background: var(--bg-3, #f0f7ff);
  border-radius: 4px;
  padding: 8px;
  margin: -4px -4px 10px -4px;
}

.custom-limit-inputs {
  display: flex;
  align-items: center;
  gap: 6px;
}

.limit-sep {
  font-size: 12px;
  color: var(--text-2);
  font-weight: 500;
}
</style>
