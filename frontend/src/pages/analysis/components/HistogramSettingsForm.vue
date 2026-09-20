<!-- frontend/src/pages/analysis/components/HistogramSettingsForm.vue
     直方图渲染设置（柱宽 / 柱体重合），放进标题栏齿轮弹层。
     从 ChartConfigPanel 的「更多」折叠区迁出（2026-09-13 工具栏齿轮化）。 -->
<template>
  <div class="hs-form">
    <div class="hs-item">
      <div class="hs-item__head">
        <span>柱宽</span>
        <span class="hs-item__value" data-hist-setting="bar-width">{{ displayBarWidth }}%</span>
      </div>
      <!-- 必须监听 update:modelValue：EP slider 的值更新走 update:modelValue，
           change 事件发出的是 props.modelValue（单向绑定下永远是旧值）。
           max 随系列数联动（barWidthMax）：多系列并排柱组必须 ≤ bin 宽，
           否则贴限柱体越过 USL 线（回归 limit-line-cross）。 -->
      <el-slider
        :model-value="displayBarWidth"
        :min="1"
        :max="barWidthMax"
        :step="1"
        size="small"
        @update:model-value="(v: number | [number, number]) => emit('update:barWidthPercent', Array.isArray(v) ? v[0] : v)"
      />
    </div>
    <div class="hs-item">
      <div class="hs-item__head">
        <span>柱体重合</span>
        <span class="hs-item__value" data-hist-setting="bar-overlap">{{ barOverlapPercent }}%</span>
      </div>
      <el-slider
        :model-value="barOverlapPercent"
        :min="0"
        :max="100"
        :step="5"
        size="small"
        @update:model-value="(v: number | [number, number]) => emit('update:barOverlapPercent', Array.isArray(v) ? v[0] : v)"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  barWidthPercent: number
  /** 柱宽 slider 上限（%）：随系列数联动（多系列并排柱组 ≤ bin 宽） */
  barWidthMax?: number
  /** 柱体重合度 0-100（barGap 负值）：重合越高柱组越窄、柱宽上限越高 */
  barOverlapPercent?: number
}>(), { barWidthMax: 100, barOverlapPercent: 5 })

const emit = defineEmits<{
  (e: 'update:barWidthPercent', v: number): void
  (e: 'update:barOverlapPercent', v: number): void
}>()

/** slider 显示值：柱宽被系列数上限 clamp（多系列并排柱组 ≤ bin 宽） */
const displayBarWidth = computed(() => Math.min(props.barWidthPercent, props.barWidthMax))
</script>

<style scoped>
.hs-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.hs-item__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--p-fs-micro);
  color: var(--text-2);
  margin-bottom: 2px;
}
.hs-item__value {
  color: var(--text);
  font-weight: 600;
}
</style>
