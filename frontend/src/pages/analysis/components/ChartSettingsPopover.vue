<!-- frontend/src/pages/analysis/components/ChartSettingsPopover.vue
     图表标题栏右上角的「齿轮」设置弹出层（通用壳）。
     - 参照 pages/data/components/ColumnHeaderFilter.vue 的 el-popover 范式。
     - popper 固定加前缀类 chart-settings-popper（共享样式挂全局块，teleport 到 body
       scoped 打不到），调用方再用实例唯一类（如 dp-hist-settings-popper）供 e2e 定位
       —— 多张图同屏时两个 popover 都在 body，必须用实例类区分（lessons 2026-09-05）。 -->
<template>
  <el-popover
    trigger="click"
    placement="bottom-end"
    :width="width"
    :popper-class="`chart-settings-popper ${popperClass}`"
  >
    <template #reference>
      <button
        class="chart-settings-btn"
        type="button"
        :title="title"
        :aria-label="title"
        :data-testid="testid"
        :disabled="disabled"
      >
        <el-icon :size="14"><Setting /></el-icon>
      </button>
    </template>
    <div class="chart-settings-body">
      <div class="chart-settings-title">{{ title }}</div>
      <slot />
    </div>
  </el-popover>
</template>

<script setup lang="ts">
import { Setting } from '@element-plus/icons-vue'

withDefaults(defineProps<{
  /** 实例级 popper class（e2e 定位用；组件会再拼上前缀 chart-settings-popper） */
  popperClass: string
  title?: string
  width?: number
  /** reference 按钮 testid */
  testid?: string
  disabled?: boolean
}>(), {
  title: '图表设置',
  width: 260,
  testid: undefined,
  disabled: false,
})
</script>

<style scoped>
.chart-settings-btn {
  border: 0;
  background: transparent;
  cursor: pointer;
  color: var(--text-3, #9ca3af);
  font-size: 14px;
  line-height: 1;
  padding: 2px 6px;
  border-radius: 3px;
  display: inline-flex;
  align-items: center;
}
.chart-settings-btn:hover:not(:disabled) {
  color: var(--brand);
  background: color-mix(in srgb, var(--brand) 10%, transparent);
}
.chart-settings-btn:disabled { cursor: default; opacity: 0.5; }
.chart-settings-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.chart-settings-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}
</style>

<style>
/* popper 渲染在 body，scoped 打不到；只放通用盒模型，颜色由 EP 主题接管 */
.chart-settings-popper .el-slider {
  width: 100%;
}
</style>
