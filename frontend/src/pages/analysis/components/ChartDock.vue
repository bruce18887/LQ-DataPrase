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
      <span class="chart-dock__hint">拖 ⠿ 手柄重排图表 · 拖分隔条改单图高宽 · 拖底部横条改整体高度（双击复原）</span>
      <span class="chart-dock__spacer" />
      <el-button size="small" text bg @click="onReset">重置布局</el-button>
    </div>

    <div class="chart-dock__body" :style="{ height: effH + 'px' }">
      <!-- 行：普通 flex 列 + 百分比高度（容器变高时天然等比缩放；el-splitter 会把行
           尺寸锁成 px、不随容器重算，故行不用它）。行间用自定义拖拽条改占比。 -->
      <template v-for="(row, ri) in displayRows" :key="'r:' + row.join('|')">
        <div class="chart-dock__row" :style="{ height: rowHeightCss(ri) }">
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

          <!-- 多图：横向 splitter 分列（宽度不受底部条影响，el-splitter 足够） -->
          <el-splitter v-else layout="horizontal" :lazy="true" @resize-end="(_i: number, px: number[]) => onColResize(ri, px)">
            <el-splitter-panel
              v-for="(key, ci) in row"
              :key="key"
              :min="'240px'"
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
        </div>

        <!-- 行间自定义水平拖拽条：改上下两行占比（仅多行时） -->
        <div
          v-if="ri < displayRows.length - 1"
          class="chart-dock__rowbar"
          :class="{ 'is-active': rowResize }"
          role="separator"
          aria-orientation="horizontal"
          title="上下拖动调整两行高度"
          @pointerdown="onRowDown(ri, $event)"
        >
          <span class="chart-dock__rowbar-grip" />
        </div>
      </template>
    </div>

    <!-- 底部横条：按住上下拖改整个图表区高度；双击回到按行数自动高度 -->
    <div
      class="chart-dock__resize"
      :class="{ 'is-active': heightResize }"
      role="separator"
      aria-orientation="horizontal"
      title="上下拖动调整图表区整体高度（双击复原自动）"
      @pointerdown="onHeightDown"
      @dblclick="resetHeight"
    >
      <span class="chart-dock__resize-grip" />
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

// 最大化：临时只显示某一张（视图态，不持久化）
const maxKey = ref<ChartKey | null>(null)
function toggleMax(k: ChartKey | null) {
  maxKey.value = k
}

// activeKeys 变化 → 补/去面板（保留既有相对顺序与尺寸）。
// 勾选集一变就退出最大化：maxKey 若残留，最大化期间勾选的图不显示、
// 关掉的图重新勾上会突然独占全屏，用户怎么点都回不去（只能刷新）。
// 挂载首拍（immediate）只对齐渲染不落盘：此刻勾选可能尚未从账号记忆恢复
// （active 暂为 ['hist']），落盘会把已存布局裁剪降级；记忆 settle 后由
// wireMemory 以最终 active 做唯一权威 reconcile+落盘。
let dockMounted = false
watch(() => props.activeKeys.join(','), () => {
  maxKey.value = null
  dock.reconcile(props.activeKeys, { persist: dockMounted })
  dockMounted = true
}, { immediate: true })

const visibleRows = computed(() => rows.value.filter((r) => r.length > 0))
const displayRows = computed<ChartKey[][]>(() => {
  if (maxKey.value && visibleRows.value.some((r) => r.includes(maxKey.value!))) return [[maxKey.value]]
  return visibleRows.value
})

/* ── 整体高度：按行数自适应，底部横条可覆盖 ───────────────── */
// 行数越多默认越高（2 行→920、4 图 2×2 每行 ~460，Y 轴初始不被挤没）；null=自动
const bodyH = ref<number | null>(null)
const MIN_H = 480
const MAX_H = 2600
// 每行默认 460px（序列图/QQ/箱线的 Y 轴初始不被挤没），单行下限 640、总上限 1400
const autoH = computed(() => Math.max(640, Math.min(displayRows.value.length * 460, 1400)))
const effH = computed(() => bodyH.value ?? autoH.value)

const heightResize = ref(false)
function onHeightDown(ev: PointerEvent) {
  if (ev.button !== 0) return
  ev.preventDefault()
  const startY = ev.clientY
  const startH = effH.value
  heightResize.value = true
  document.body.style.userSelect = 'none'
  const onMove = (e: PointerEvent) => {
    const next = Math.max(MIN_H, Math.min(MAX_H, startH + (e.clientY - startY)))
    bodyH.value = next
  }
  const onUp = () => {
    heightResize.value = false
    document.body.style.userSelect = ''
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
    window.removeEventListener('pointercancel', onUp)
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
  window.addEventListener('pointercancel', onUp)
}
function resetHeight() {
  bodyH.value = null
}

// 行高：占比% 减去「行间拖拽条」占位（rowbar 10px × (行数-1)），使各行 + 分隔条
// 正好铺满 dock body、且随 body 变高按占比等比缩放。flex-grow 置 0 以免被均分覆盖。
const ROWBAR_H = 10
const rowHeightCss = (ri: number) => {
  const pct = Number.isFinite(rowPcts.value[ri]) ? rowPcts.value[ri] : 100 / displayRows.value.length
  const bars = Math.max(0, displayRows.value.length - 1) * ROWBAR_H
  return `calc(${pct}% - ${(bars * pct) / 100}px)`
}

const colPctStr = (ri: number, ci: number) => {
  const c = colPcts.value[ri]?.[ci]
  return Number.isFinite(c) ? `${c}%` : undefined
}

// 行间自定义拖拽条：按住上下拖，把两行的高度占比此消彼长（受单行最小 200px 约束）
const rowResize = ref(false)
function onRowDown(ri: number, ev: PointerEvent) {
  if (ev.button !== 0 || maxKey.value) return
  ev.preventDefault()
  const startY = ev.clientY
  const a0 = rowPcts.value[ri] ?? 50
  const b0 = rowPcts.value[ri + 1] ?? 50
  const bodyPx = effH.value
  const minPct = (200 / bodyPx) * 100
  rowResize.value = true
  document.body.style.userSelect = 'none'
  const onMove = (e: PointerEvent) => {
    const dPct = ((e.clientY - startY) / bodyPx) * 100
    let a = a0 + dPct
    let b = b0 - dPct
    if (a < minPct) { a = minPct; b = a0 + b0 - minPct }
    if (b < minPct) { b = minPct; a = a0 + b0 - minPct }
    const next = [...rowPcts.value]
    next[ri] = a
    next[ri + 1] = b
    dock.setRowPcts(next)
  }
  const onUp = () => {
    rowResize.value = false
    document.body.style.userSelect = ''
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
    window.removeEventListener('pointercancel', onUp)
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
  window.addEventListener('pointercancel', onUp)
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
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
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
  position: relative;
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  gap: 0;
}
/* 行：高度由 inline calc(占比% − rowbar 占位) 精确决定，flex 不 grow/shrink
   （否则被均分覆盖占比）。随 dock body 变高按占比等比缩放。 */
.chart-dock__row {
  flex: 0 0 auto;
  min-height: 0;
  display: flex;
}
.chart-dock__row > * { flex: 1; min-width: 0; min-height: 0; }
/* 行间自定义水平拖拽条 */
.chart-dock__rowbar {
  flex: 0 0 auto;
  height: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: row-resize;
  border-radius: 5px;
  background: var(--bg-3, #f0f1f3);
  touch-action: none;
}
.chart-dock__rowbar:hover { background: color-mix(in srgb, var(--brand) 14%, var(--bg-3)); }
.chart-dock__rowbar.is-active { background: color-mix(in srgb, var(--brand) 24%, var(--bg-3)); }
.chart-dock__rowbar-grip {
  width: 36px;
  height: 3px;
  border-radius: 2px;
  background: var(--text-3, #9ca3af);
}
/* 底部整体高度拖拽横条 */
.chart-dock__resize {
  flex: 0 0 auto;
  height: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: row-resize;
  border-radius: 6px;
  background: var(--bg-3, #f0f1f3);
  border: 1px solid var(--border-2, #e4e7ed);
  touch-action: none;
}
.chart-dock__resize:hover { background: color-mix(in srgb, var(--brand) 12%, var(--bg-3)); }
.chart-dock__resize.is-active { background: color-mix(in srgb, var(--brand) 22%, var(--bg-3)); }
.chart-dock__resize-grip {
  width: 36px;
  height: 3px;
  border-radius: 2px;
  background: var(--text-3, #9ca3af);
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
/* el-splitter 撑满 body（body 高度由内联 style 决定） */
.chart-dock__body :deep(.el-splitter) { height: 100%; }
.chart-dock__body :deep(.el-splitter-panel) { overflow: hidden; }
</style>
