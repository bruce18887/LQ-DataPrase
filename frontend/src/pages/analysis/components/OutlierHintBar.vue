<template>
  <div
    v-if="visible"
    class="outlier-hint-bar"
    :class="`outlier-hint-bar--${mode}`"
  >
    <el-tooltip
      v-if="outlierValues.length > 0"
      placement="top"
      :width="320"
    >
      <template #content>
        <div class="outlier-hint-bar__tooltip">
          <div class="outlier-hint-bar__tooltip-title">异常值列表</div>
          <div class="outlier-hint-bar__tooltip-values">
            {{ outlierValues.map(v => v.toFixed(4)).join(', ') }}
          </div>
        </div>
      </template>
      <span class="outlier-hint-bar__text">
        <el-icon class="outlier-hint-bar__icon"><Warning /></el-icon>
        {{ hintText }}
      </span>
    </el-tooltip>
    <span v-else class="outlier-hint-bar__text">
      <el-icon class="outlier-hint-bar__icon"><Warning /></el-icon>
      {{ hintText }}
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Warning } from '@element-plus/icons-vue'

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
  if (!props.outlierInfo) return false
  if (props.mode === 'off') return false
  return props.outlierInfo.has_outliers
})

const outlierValues = computed(() => {
  return props.outlierInfo?.outlier_values ?? []
})

const hintText = computed(() => {
  if (!props.outlierInfo) return ''
  const info = props.outlierInfo
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

.outlier-hint-bar__tooltip {
  max-width: 300px;
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
</style>
