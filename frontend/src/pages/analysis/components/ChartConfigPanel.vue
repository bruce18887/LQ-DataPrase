<template>
  <el-card shadow="hover" :body-style="{ padding: '12px' }">
    <div class="config-header">
      <span class="config-title">⚙️ 图表配置</span>
      <el-button
        v-if="variant === 'full'"
        link
        size="small"
        class="more-btn"
        @click="showMore = !showMore"
      >
        <el-icon><Setting /></el-icon>
        更多
      </el-button>
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

    <!-- 柱状图宽度：完整版藏在「更多」里，多文件版直接展开 -->
    <el-collapse-transition>
      <div v-show="variant === 'multi-file' || showMore">
        <div class="config-section">
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
        <!-- 柱体重合：重合越高柱组越窄、柱宽上限越高（仅单参数完整版） -->
        <div v-if="variant === 'full'" class="config-section">
          <div class="section-label flex-between">
            <span>柱体重合</span>
            <span class="value-hint">{{ barOverlapPercent }}%</span>
          </div>
          <el-slider :model-value="barOverlapPercent" :min="0" :max="100" :step="5" size="small" @update:model-value="onBarOverlapChange" />
        </div>
      </div>
    </el-collapse-transition>

    <!-- 数据筛选：忽略无Limit 两种变体都显示，其余四项仅单参数完整版 -->
    <div class="config-section filter-section">
      <div class="section-label">数据筛选</div>
      <div class="filter-checkboxes">
        <el-checkbox :model-value="ignoreNoLimit" size="small" @change="onIgnoreNoLimitChange">
          忽略无Limit
        </el-checkbox>
        <template v-if="variant === 'full' || fullFilters">
          <el-checkbox :model-value="ignoreNoTestValue" size="small" @change="onIgnoreNoTestValueChange">
            忽略无测试值
          </el-checkbox>
          <el-checkbox :model-value="dataOnlyBin1" size="small" @change="onDataOnlyBin1Change">
            仅用Pass数据(Bin1)
          </el-checkbox>
          <el-checkbox :model-value="onlyFailTestItem" size="small" @change="onOnlyFailTestItemChange">
            仅显示Fail测试项
          </el-checkbox>
          <el-checkbox :model-value="onlyLowCpk" size="small" @change="onOnlyLowCpkChange">
            仅显示低CPK项
          </el-checkbox>
        </template>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Setting } from '@element-plus/icons-vue'

interface Props {
  chartConfig: string[]
  rangeType: string
  barWidthPercent: number
  /** 柱宽 slider 上限（%）：随系列数联动（多系列并排柱组 ≤ bin 宽） */
  barWidthMax?: number
  /** 柱体重合度 0-100（barGap 负值）：重合越高柱组越窄、柱宽上限越高 */
  barOverlapPercent?: number
  ignoreNoLimit: boolean
  customLow?: number | null
  customHigh?: number | null
  /** 数据筛选开关（默认仅单参数完整版显示；multi-file 变体传 full-filters 开启全部 5 个） */
  ignoreNoTestValue?: boolean
  dataOnlyBin1?: boolean
  onlyFailTestItem?: boolean
  onlyLowCpk?: boolean
  /** 多文件/其它变体强制显示完整数据筛选区（2026-08-20） */
  fullFilters?: boolean
  /** 'full' = 单参数分析完整配置；'multi-file' = 多文件分析阉割版（仅 Limit + 柱宽 + 忽略无Limit） */
  variant?: 'full' | 'multi-file'
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'full',
  ignoreNoTestValue: false,
  dataOnlyBin1: false,
  onlyFailTestItem: false,
  onlyLowCpk: false,
  fullFilters: false,
  barWidthMax: 100,
  barOverlapPercent: 5,
})

const emit = defineEmits<{
  (e: 'update:chartConfig', val: string[]): void
  (e: 'update:rangeType', val: string): void
  (e: 'update:barWidthPercent', val: number): void
  (e: 'update:barOverlapPercent', val: number): void
  (e: 'update:ignoreNoLimit', val: boolean): void
  (e: 'update:customLow', val: number | null): void
  (e: 'update:customHigh', val: number | null): void
  (e: 'update:ignoreNoTestValue', val: boolean): void
  (e: 'update:dataOnlyBin1', val: boolean): void
  (e: 'update:onlyFailTestItem', val: boolean): void
  (e: 'update:onlyLowCpk', val: boolean): void
}>()

const showMore = ref(false)

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

function onBarOverlapChange(val: number) {
  emit('update:barOverlapPercent', val)
}

function onIgnoreNoLimitChange(val: boolean) {
  emit('update:ignoreNoLimit', val)
}

function onIgnoreNoTestValueChange(val: boolean) {
  emit('update:ignoreNoTestValue', val)
}

function onDataOnlyBin1Change(val: boolean) {
  emit('update:dataOnlyBin1', val)
}

function onOnlyFailTestItemChange(val: boolean) {
  emit('update:onlyFailTestItem', val)
}

function onOnlyLowCpkChange(val: boolean) {
  emit('update:onlyLowCpk', val)
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
  color: var(--text-primary);
}

.more-btn {
  font-size: 11px;
  color: var(--text-secondary);
}

.more-btn:hover {
  color: var(--color-primary, #409eff);
}

.config-section {
  margin-bottom: 10px;
}

.config-section:last-child {
  margin-bottom: 0;
}

.section-label {
  font-size: 11px;
  color: var(--text-secondary);
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
  color: var(--text-primary);
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
  background: var(--bg-tertiary, #f0f7ff);
  border-radius: 4px;
  padding: 8px;
  margin: -4px -4px 10px -4px;
}

.filter-checkboxes {
  display: flex;
  flex-wrap: wrap;
  gap: 0 12px;
}

.filter-checkboxes :deep(.el-checkbox) {
  margin-right: 0;
  height: 24px;
}

.filter-checkboxes :deep(.el-checkbox__label) {
  font-size: 12px;
  padding-left: 4px;
}

.custom-limit-inputs {
  display: flex;
  align-items: center;
  gap: 6px;
}

.limit-sep {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
}
</style>
