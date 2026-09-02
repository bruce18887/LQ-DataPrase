<template>
  <div
    v-if="visible"
    class="outlier-hint-bar"
    :class="hintClass"
  >
    <el-tooltip
      v-if="outlierValues.length > 0"
      placement="top"
      :width="360"
    >
      <template #content>
        <div class="outlier-hint-bar__tooltip">
          <div class="outlier-hint-bar__tooltip-title">
            异常值列表（共 {{ outlierValues.length }} 个）
          </div>
          <div class="outlier-hint-bar__tooltip-values">
            {{ displayedValues }}
          </div>
        </div>
      </template>
      <span class="outlier-hint-bar__text">
        <el-icon class="outlier-hint-bar__icon"><Warning /></el-icon>
        {{ hintText }}
        <span class="outlier-hint-bar__action">悬停查看列表</span>
      </span>
    </el-tooltip>
    <span v-else class="outlier-hint-bar__text">
      <el-icon class="outlier-hint-bar__icon"><component :is="iconComponent" /></el-icon>
      {{ hintText }}
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Warning, CircleCheck } from '@element-plus/icons-vue'

export interface OutlierInfo {
  has_outliers: boolean
  outlier_count: number
  lower_bound: number
  upper_bound: number
  outlier_values?: number[]
  normal_count: number
}

const props = defineProps<{
  mode: 'clip' | 'exclude' | 'off'
  outlierInfo: OutlierInfo | null
}>()

const visible = computed(() => {
  if (props.mode === 'off') return false
  if (!props.outlierInfo) return false
  return true
})

const hasOutliers = computed(() => props.outlierInfo?.has_outliers === true)

const hintClass = computed(() => {
  if (!hasOutliers.value) return 'outlier-hint-bar--ok'
  return `outlier-hint-bar--${props.mode}`
})

const iconComponent = computed(() => hasOutliers.value ? Warning : CircleCheck)

const outlierValues = computed(() => {
  return props.outlierInfo?.outlier_values ?? []
})

const MAX_TOOLTIP_VALUES = 30

const displayedValues = computed(() => {
  const values = outlierValues.value
  if (values.length === 0) return ''
  const formatted = values.slice(0, MAX_TOOLTIP_VALUES).map(v => v.toFixed(4))
  if (values.length > MAX_TOOLTIP_VALUES) {
    formatted.push(`…等 ${values.length - MAX_TOOLTIP_VALUES} 个`)
  }
  return formatted.join(', ')
})

const hintText = computed(() => {
  if (!props.outlierInfo) return ''
  const info = props.outlierInfo
  if (!info.has_outliers) {
    return `异常值检测: 未发现异常值（IQR 范围: ${info.lower_bound.toFixed(4)} ~ ${info.upper_bound.toFixed(4)}）`
  }
  const modeText = props.mode === 'clip' ? '已裁剪' : '已排除'
  const bounds = `（正常范围: ${info.lower_bound.toFixed(4)} ~ ${info.upper_bound.toFixed(4)}）`
  return `${modeText} ${info.outlier_count} 个异常值 ${bounds}`
})
</script>

<style scoped>
.outlier-hint-bar {
  display: flex;
  align-items: center;
  padding: 6px 12px;
  border-radius: 4px;
  margin-top: 4px;
  font-size: 12px;
}

/* 三态只认主题语义 token：底色/描边由 --warn|--error|--success 派生，
   light 与 night 各自取该主题下的 token 值（R7，不再各写一份夜块） */
.outlier-hint-bar--clip {
  background-color: color-mix(in srgb, var(--warn) 12%, transparent);
  color: var(--warn);
  border: 1px solid color-mix(in srgb, var(--warn) 30%, transparent);
}

.outlier-hint-bar--exclude {
  background-color: color-mix(in srgb, var(--error) 12%, transparent);
  color: var(--error);
  border: 1px solid color-mix(in srgb, var(--error) 30%, transparent);
}

.outlier-hint-bar--ok {
  background-color: color-mix(in srgb, var(--success) 12%, transparent);
  color: var(--success);
  border: 1px solid color-mix(in srgb, var(--success) 30%, transparent);
}

.outlier-hint-bar__text {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: default;
}

.outlier-hint-bar__icon {
  font-size: 14px;
  flex-shrink: 0;
}

.outlier-hint-bar__action {
  margin-left: 4px;
  font-size: 11px;
  opacity: 0.85;
  text-decoration: underline;
  cursor: help;
}

.outlier-hint-bar__tooltip {
  max-width: 340px;
}

.outlier-hint-bar__tooltip-title {
  font-weight: bold;
  margin-bottom: 4px;
}

.outlier-hint-bar__tooltip-values {
  word-break: break-all;
  font-family: var(--font-mono);
  font-size: 11px;
}
</style>
