<template>
  <el-card shadow="hover" :body-style="{ padding: '12px' }">
    <div class="filter-section">
      <div class="section-label">数据筛选</div>
      <div class="filter-checkboxes">
        <el-checkbox
          :model-value="ignoreNoLimit"
          size="small"
          data-filter="ignore-no-limit"
          @change="emit('update:ignoreNoLimit', $event)"
        >
          忽略无Limit
        </el-checkbox>
        <el-checkbox
          :model-value="ignoreNoTestValue"
          size="small"
          data-filter="ignore-no-test-value"
          @change="emit('update:ignoreNoTestValue', $event)"
        >
          忽略无测试值
        </el-checkbox>
        <el-checkbox
          :model-value="dataOnlyBin1"
          size="small"
          data-filter="data-only-bin1"
          @change="emit('update:dataOnlyBin1', $event)"
        >
          仅用Pass数据(Bin1)
        </el-checkbox>
        <el-checkbox
          :model-value="onlyFailTestItem"
          size="small"
          data-filter="only-fail-test-item"
          @change="emit('update:onlyFailTestItem', $event)"
        >
          仅显示Fail测试项
        </el-checkbox>
        <el-checkbox
          :model-value="onlyLowCpk"
          size="small"
          data-filter="only-low-cpk"
          @change="emit('update:onlyLowCpk', $event)"
        >
          仅显示低CPK项
        </el-checkbox>
      </div>

      <!-- 异常值处理：只在前端确实消费裁剪口径的 tab 显示（多文件不消费） -->
      <div v-if="showOutlier" class="control-line">
        <span class="section-label control-label">异常值处理</span>
        <el-select
          :model-value="outlierHandling"
          size="small"
          aria-label="异常值处理"
          data-filter="outlier-handling"
          :popper-class="`dp-outlier-popper-${scope}`"
          class="control-select"
          @change="emit('update:outlierHandling', $event)"
        >
          <el-option label="裁剪范围" value="clip" />
          <el-option label="不处理" value="off" />
        </el-select>
      </div>

      <!-- 敏感度：既是裁剪栅栏的倍数，也是「仅显示低CPK项」的判定阈值，
           所以任一在用就必须可见（旧页头只在非 off 时显示，勾了低CPK却调不了阈值） -->
      <div v-if="showSensitivity && sensitivityVisible" class="control-line">
        <span class="section-label control-label">敏感度</span>
        <el-select
          :model-value="iqrMultiplier"
          size="small"
          aria-label="敏感度"
          data-filter="iqr-multiplier"
          :popper-class="`dp-iqr-popper-${scope}`"
          class="control-select control-select--wide"
          @change="emit('update:iqrMultiplier', $event)"
        >
          <el-option label="严格 (1.5x IQR)" :value="1.5" />
          <el-option label="宽松 (3.0x IQR)" :value="3.0" />
        </el-select>
        <span class="sensitivity-hint">{{ sensitivityHint }}</span>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
/**
 * 数据筛选 + 异常值处理（每个 tab 一份，绑该 tab 自己的 store）。
 *
 * 原先异常值处理与敏感度挂在页头、和 tab 内的 5 个开关分属两处，用户在页头
 * 改的档位实际影响的是别的 tab 的数据源。收拢到一个组件后，控件与它作用的那
 * 份状态同屏同归属（docs/specs/2026-09-05-analysis-per-tab-file-selection-design.md）。
 *
 * 本组件不持有任何状态，也不做「本地快照 + 双向 watch」（lessons R5）。
 */
import { computed } from 'vue'
import type { OutlierMode } from '../../../stores/analysisTabs'

const props = withDefaults(defineProps<{
  ignoreNoLimit: boolean
  ignoreNoTestValue: boolean
  dataOnlyBin1: boolean
  onlyFailTestItem: boolean
  onlyLowCpk: boolean
  outlierHandling?: OutlierMode
  iqrMultiplier?: number
  /** 前端裁剪口径是否在本 tab 生效（多文件图表不消费 → false） */
  showOutlier?: boolean
  /** 敏感度档位是否可暴露（晶圆图整块不显示筛选） */
  showSensitivity?: boolean
  /**
   * 所属 tab（single|correlation|multi）：决定两个下拉的 popper class。
   * popper 被 teleport 到 body，不随隐藏 pane 一起消失，测试必须按它收窄定位。
   */
  scope?: string
}>(), {
  outlierHandling: 'off',
  iqrMultiplier: 1.5,
  showOutlier: true,
  showSensitivity: true,
  scope: 'single',
})

const emit = defineEmits<{
  (e: 'update:ignoreNoLimit', val: boolean): void
  (e: 'update:ignoreNoTestValue', val: boolean): void
  (e: 'update:dataOnlyBin1', val: boolean): void
  (e: 'update:onlyFailTestItem', val: boolean): void
  (e: 'update:onlyLowCpk', val: boolean): void
  (e: 'update:outlierHandling', val: OutlierMode): void
  (e: 'update:iqrMultiplier', val: number): void
}>()

const sensitivityVisible = computed(
  () => props.outlierHandling !== 'off' || props.onlyLowCpk,
)

const sensitivityHint = computed(() => {
  if (!props.showOutlier) return '低 CPK 判定阈值'
  return props.iqrMultiplier === 1.5 ? '标记轻微异常值' : '仅标记极端异常值'
})
</script>

<style scoped>
.filter-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.section-label {
  font-size: 11px;
  color: var(--text-2);
  font-weight: 500;
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

.control-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.control-label {
  flex: 0 0 auto;
}

.control-select {
  width: 110px;
  /* 窄屏/窄左栏时随容器收缩，不撑出横向滚动条 */
  max-width: 100%;
}

.control-select--wide {
  width: 132px;
}

.sensitivity-hint {
  font-size: 12px;
  /* 不用 --text-3：浅色主题它是 #9ca3af，落在白底卡片上仅 2.54:1（e2e
     对比度扫描实测），12px 提示文字读不动；--text-2 两套主题均 ≥ 3 */
  color: var(--text-2);
}
</style>
