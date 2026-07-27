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

.outlier-hint-bar--clip {
  background-color: #fff3e0;
  color: #e65100;
  border: 1px solid #ffe0b2;
}

.outlier-hint-bar--exclude {
  background-color: #fce4ec;
  color: #c62828;
  border: 1px solid #f8bbd0;
}

.outlier-hint-bar--ok {
  background-color: #e8f5e9;
  color: #2e7d32;
  border: 1px solid #c8e6c9;
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
  font-family: monospace;
  font-size: 11px;
}

/* Dark theme */
:root[data-theme='night'] .outlier-hint-bar--clip {
  background-color: #3e2723;
  color: #ffab91;
  border: 1px solid #5d4037;
}

:root[data-theme='night'] .outlier-hint-bar--exclude {
  background-color: #3e1515;
  color: #ef9a9a;
  border: 1px solid #5d2020;
}

:root[data-theme='night'] .outlier-hint-bar--ok {
  background-color: #1b3a1b;
  color: #81c784;
  border: 1px solid #2e5a2e;
}
</style>
