<!-- frontend/src/pages/analysis/components/ChartDock.vue
     可停靠拼格图表区：外层 el-splitter(vertical) 分行、行内 >1 图再套 el-splitter(horizontal) 分列。
     - 分隔条拖拽改高/宽（Element Plus 内置 el-splitter，零新依赖）
     - 每张图标题栏手柄 ⠿ 触发指针拖拽，拖到别图的 上/下/左/右/中 分别：新行 / 新列 / 交换
     - 「重置布局」+ 标题栏「×关闭 / ⤢最大化」
     模型与持久化在 useChartDock.ts；本组件只管渲染 + 指针命中。
     内容通过按 key 命名的 slot 注入：hist/serial/qq/box（图体）与 controls-box（箱线控件）。 -->
<template>
  <div class="chart-dock" :class="{ 'is-dragging': !!drag }">
    <div class="chart-dock__bar">
      <span class="chart-dock__hint">拖 ⠿ 手柄重排图表 · 拖分隔条改高宽</span>
      <span class="chart-dock__spacer" />
      <el-button size="small" text bg @click="onReset">重置布局</el-button>
    </div>

    <div class="chart-dock__body">
      <el-splitter layout="vertical" :lazy="true" @resize-end="onRowResize">
        <el-splitter-panel
          v-for="(row, ri) in displayRows"
          :key="'r:' + row.join('|')"
          :min="'120px'"
          :size="rowPctStr(ri)"
          :resizable="displayRows.length > 1"
        >
          <!-- 单图：直接铺 -->
          <ChartPanel
            v-if="row.length === 1"
            :chart-key="row[0]"
            :title="titleOf(row[0])"
            :variant="row[0] === 'hist' ? 'top' : 'bottom'"
            :closable="row[0] !== 'hist'"
            :maximized="maxKey === row[0]"
            :dragging="drag?.key === row[0]"
            :drop-side="dropSideOf(row[0])"
            :data-key="row[0]"
            @dragstart="onDragStart"
            @close="emit('close', row[0])"
            @maximize="toggleMax(row[0])"
            @restore="toggleMax(null)"
          >
            <slot :name="row[0]" />
            <template v-if="$slots['controls-' + row[0]]" #controls>
              <slot :name="'controls-' + row[0]" />
            </template>
          </ChartPanel>

          <!-- 多图：横向 splitter 分列 -->
          <el-splitter v-else layout="horizontal" :lazy="true" @resize-end="(_i: number, px: number[]) => onColResize(ri, px)">
            <el-splitter-panel
              v-for="(key, ci) in row"
              :key="key"
              :min="'150px'"
              :size="colPctStr(ri, ci)"
            >
              <ChartPanel
                :chart-key="key"
                :title="titleOf(key)"
                :variant="key === 'hist' ? 'top' : 'bottom'"
                :closable="key !== 'hist'"
                :maximized="maxKey === key"
                :dragging="drag?.key === key"
                :drop-side="dropSideOf(key)"
                :data-key="key"
                @dragstart="onDragStart"
                @close="emit('close', key)"
                @maximize="toggleMax(key)"
                @restore="toggleMax(null)"
              >
                <slot :name="key" />
                <template v-if="$slots['controls-' + key]" #controls>
                  <slot :name="'controls-' + key" />
                </template>
              </ChartPanel>
            </el-splitter-panel>
          </el-splitter>
        </el-splitter-panel>
      </el-splitter>
    </div>

    <!-- 拖拽跟随的幽灵标签 -->
    <div v-if="drag" class="chart-dock__ghost" :style="{ left: drag.x + 'px', top: drag.y + 'px' }">
      {{ titleOf(drag.key) }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import ChartPanel from './ChartPanel.vue'
import { useChartDock, pctFromPx, type ChartKey } from '../composables/useChartDock'

const props = defineProps<{ activeKeys: ChartKey[] }>()
const emit = defineEmits<{ (e: 'close', key: ChartKey): void }>()

const dock = useChartDock(() => props.activeKeys)
const { rows, rowPcts, colPcts } = dock

const TITLES: Record<ChartKey, string> = {
  hist: '直方图', serial: '序列分布', qq: 'QQ 图', box: '箱线图',
}
const titleOf = (k: ChartKey) => TITLES[k] ?? k

// activeKeys 变化 → 补/去面板（保留既有相对顺序与尺寸）
watch(() => props.activeKeys.join(','), () => dock.reconcile(props.activeKeys), { immediate: true })

// 最大化：临时只显示某一张（视图态，不持久化）
const maxKey = ref<ChartKey | null>(null)
function toggleMax(k: ChartKey | null) {
  maxKey.value = k
}

const visibleRows = computed(() => rows.value.filter((r) => r.length > 0))
const displayRows = computed<ChartKey[][]>(() => {
  if (maxKey.value && visibleRows.value.some((r) => r.includes(maxKey.value!))) return [[maxKey.value]]
  return visibleRows.value
})

const rowPctStr = (ri: number) => (Number.isFinite(rowPcts.value[ri]) ? `${rowPcts.value[ri]}%` : undefined)
const colPctStr = (ri: number, ci: number) => {
  const c = colPcts.value[ri]?.[ci]
  return Number.isFinite(c) ? `${c}%` : undefined
}

function onRowResize(_i: number, pxSizes: number[]) {
  if (maxKey.value) return // 最大化态是临时视图（单格 100%），不回写真实行尺寸
  dock.setRowPcts(pctFromPx(pxSizes))
}
function onColResize(ri: number, pxSizes: number[]) {
  if (maxKey.value) return // 同上：避免把 [100] 之类临时尺寸持久化
  dock.setColPcts(ri, pctFromPx(pxSizes))
}
function onReset() {
  maxKey.value = null
  dock.reset(props.activeKeys)
}

/* ── 拖拽换布局 ───────────────────────────────── */
const drag = ref<{ key: ChartKey; x: number; y: number } | null>(null)
const dropTarget = ref<{ key: ChartKey; dir: DropDir } | null>(null)
type DropDir = 'left' | 'right' | 'above' | 'below' | 'swap'

const dropSideOf = (key: ChartKey): DropDir | null =>
  dropTarget.value && dropTarget.value.key === key && drag.value && drag.value.key !== key
    ? dropTarget.value.dir
    : null

function onDragStart(key: ChartKey, ev: PointerEvent) {
  drag.value = { key, x: ev.clientX, y: ev.clientY }
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
  window.addEventListener('pointercancel', onPointerUp)
}

function onPointerMove(ev: PointerEvent) {
  if (!drag.value) return
  drag.value = { ...drag.value, x: ev.clientX, y: ev.clientY }
  const hit = hitTest(ev.clientX, ev.clientY)
  dropTarget.value = hit && hit.key !== drag.value.key ? hit : null
}

/** 命中指针下的面板，按象限给出放置方向 */
function hitTest(x: number, y: number): { key: ChartKey; dir: DropDir } | null {
  const el = document.elementFromPoint(x, y)?.closest('[data-key]') as HTMLElement | null
  if (!el) return null
  const key = el.dataset.key as ChartKey
  if (!key || key === drag.value?.key) return null
  const r = el.getBoundingClientRect()
  const rx = (x - r.left) / r.width
  const ry = (y - r.top) / r.height
  let dir: DropDir
  if (ry < 0.28) dir = 'above'
  else if (ry > 0.72) dir = 'below'
  else if (rx < 0.3) dir = 'left'
  else if (rx > 0.7) dir = 'right'
  else dir = 'swap'
  return { key, dir }
}

function onPointerUp() {
  const d = drag.value
  const t = dropTarget.value
  if (d && t && d.key !== t.key) dock.moveTo(d.key, t.key, t.dir)
  cleanupDrag()
}

function cleanupDrag() {
  drag.value = null
  dropTarget.value = null
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  window.removeEventListener('pointercancel', onPointerUp)
}
onBeforeUnmount(cleanupDrag)
</script>

<style scoped>
.chart-dock {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.chart-dock__bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 0 0 auto;
}
.chart-dock__hint {
  font-size: 11px;
  color: var(--text-3);
}
.chart-dock__spacer { flex: 1; }
.chart-dock__body {
  flex: 1;
  min-height: 660px;
  /* 桌面式可停靠区：占满右栏剩余高度，最小 660 保证直方图默认明显比上轮 320 高 */
  height: 100%;
}
.chart-dock.is-dragging { user-select: none; }
.chart-dock.is-dragging :deep(.chart-b) { pointer-events: none; }

.chart-dock__ghost {
  position: fixed;
  z-index: 3000;
  transform: translate(12px, 12px);
  pointer-events: none;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 600;
  color: var(--on-brand, #fff);
  background: var(--brand, #2563eb);
  border-radius: 4px;
  box-shadow: var(--shadow-sm, 0 2px 8px rgba(0, 0, 0, 0.15));
  white-space: nowrap;
}
/* el-splitter 在 flex 容器里需撑满 */
.chart-dock__body :deep(.el-splitter) { height: 100%; }
.chart-dock__body :deep(.el-splitter-panel) { overflow: hidden; }
</style>
