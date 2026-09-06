<!-- frontend/src/pages/analysis/components/ChartPanel.vue
     单张图的容器外壳：标题栏（图名 + 拖拽手柄 + 可选控件槽 + 最大化/关闭）+ 图体。
     对齐参考原型 .chart-h / .chart-b 的两段结构；标题栏手柄承担 dock 拖拽起点，
     画布本身不响应拖拽（避免与 ECharts 的 dataZoom/tooltip 抢鼠标）。
     根节点携带 chart-wrapper 类名以保持既有 e2e 选择器（--top 直方图 / --bottom 其余）。 -->
<template>
  <div
    class="chart-panel chart-wrapper"
    :class="[variantClass, { 'chart-panel--dragging': dragging, 'is-drop-left': dropSide === 'left', 'is-drop-right': dropSide === 'right', 'is-drop-above': dropSide === 'above', 'is-drop-below': dropSide === 'below', 'is-drop-swap': dropSide === 'swap' }]"
    :data-chart-key="chartKey"
  >
    <div class="chart-h">
      <span
        class="chart-h__grip"
        role="button"
        tabindex="0"
        aria-label="拖拽以重新排列图表"
        title="按住拖拽以重新排列图表"
        @pointerdown="onGripDown"
        @keydown="onGripKey"
      >⠿</span>
      <span class="chart-h__title">{{ title }}</span>
      <span class="chart-h__controls"><slot name="controls" /></span>
      <span class="chart-h__grow" />
      <button
        v-if="maximizable"
        class="chart-h__btn"
        type="button"
        :title="maximized ? '恢复布局' : '最大化'"
        @click="maximized ? emit('restore') : emit('maximize')"
      >{{ maximized ? '⤓' : '⤢' }}</button>
      <button
        v-if="closable"
        class="chart-h__btn"
        type="button"
        title="关闭"
        aria-label="关闭图表"
        @click="emit('close')"
      >×</button>
    </div>
    <div class="chart-b"><slot /></div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ChartKey } from '../composables/useChartDock'

const props = withDefaults(defineProps<{
  chartKey: ChartKey
  title: string
  /** 直方图用 --top、其余用 --bottom，兼容 e2e `.chart-wrapper--top/--bottom svg` */
  variant?: 'top' | 'bottom'
  /** 拖拽中：半透明化（本图正在被拖） */
  dragging?: boolean
  /** 该图当前作为放置目标命中的方向；ChartDock 计算后传入 */
  dropSide?: 'left' | 'right' | 'above' | 'below' | 'swap' | null
  closable?: boolean
  maximizable?: boolean
  maximized?: boolean
}>(), {
  variant: 'bottom',
  dragging: false,
  dropSide: null,
  closable: false,
  maximizable: true,
  maximized: false,
})

const emit = defineEmits<{
  (e: 'dragstart', key: ChartKey, ev: PointerEvent): void
  (e: 'close'): void
  (e: 'maximize'): void
  (e: 'restore'): void
}>()

const variantClass = computed(() => (props.variant === 'top' ? 'chart-wrapper--top' : 'chart-wrapper--bottom'))

function onGripDown(ev: PointerEvent) {
  // 只响应主键；不 preventDefault，让 CSS 光标反馈接管
  if (ev.button !== 0) return
  emit('dragstart', props.chartKey, ev)
}

// 键盘可达：Enter/Space 起不到拖拽效果（拖拽本身要指针），此处仅提示，不做操作
function onGripKey(ev: KeyboardEvent) {
  if (ev.key === 'Enter' || ev.key === ' ') ev.preventDefault()
}
</script>

<style scoped>
.chart-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  width: 100%;
  height: 100%;
  background: var(--bg-2, #fff);
  border: 1px solid var(--border-2, #e4e7ed);
  border-radius: 6px;
  overflow: hidden;
  transition: box-shadow 120ms ease, opacity 120ms ease;
}
.chart-h {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 28px;
  padding: 0 8px;
  background: var(--bg-3, #f8f9fa);
  border-bottom: 1px solid var(--border-2, #e4e7ed);
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  user-select: none;
  flex: 0 0 auto;
}
.chart-h__grip {
  cursor: grab;
  color: var(--text-3, #9ca3af);
  padding: 0 4px;
  font-size: 14px;
  line-height: 1;
  border-radius: 3px;
}
.chart-h__grip:hover { color: var(--brand); background: color-mix(in srgb, var(--brand) 10%, transparent); }
.chart-h__grip:active { cursor: grabbing; }
.chart-h__title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chart-h__controls { display: inline-flex; align-items: center; gap: 8px; margin-left: 4px; }
.chart-h__grow { flex: 1; }
.chart-h__btn {
  border: 0; background: transparent; cursor: pointer; color: var(--text-3, #9ca3af);
  font-size: 14px; line-height: 1; padding: 2px 6px; border-radius: 3px;
}
.chart-h__btn:hover { color: var(--brand); background: color-mix(in srgb, var(--brand) 10%, transparent); }
.chart-b {
  flex: 1;
  min-height: 0;
  /* 1×1 网格：slot 注入的图组件天然铺满单元格（子项默认 stretch），
     规避 scoped CSS 选不到 slot 子节点的问题，也无需子组件自带 flex 规则 */
  display: grid;
  grid-template-columns: 1fr;
  grid-template-rows: 1fr;
  overflow: hidden;
}

.chart-panel--dragging { opacity: 0.4; }
/* 放置目标高亮：用 inset box-shadow 描边（避免影响面板几何） */
.chart-panel.is-drop-swap  { box-shadow: inset 0 0 0 2px var(--brand); }
.chart-panel.is-drop-left  { box-shadow: inset 6px 0 0 0 var(--brand); }
.chart-panel.is-drop-right { box-shadow: inset -6px 0 0 0 var(--brand); }
.chart-panel.is-drop-above { box-shadow: inset 0 6px 0 0 var(--brand); }
.chart-panel.is-drop-below { box-shadow: inset 0 -6px 0 0 var(--brand); }
</style>
