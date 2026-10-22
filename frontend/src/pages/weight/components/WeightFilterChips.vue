<script setup lang="ts">
import { groupColor, DASH_BY_WITHIN_GROUP, type WeightGroupDto } from '../weightChartOption'

const props = defineProps<{
  groups: WeightGroupDto[]
  visible: number[]
  colors: string[]
  /** 「组内曲线」那排的个数 = 该文件最长组的成员数（`slotCount(doc)`），不是一律四条。 */
  slotTotal: number
  visibleSlots: number[]
}>()
const emit = defineEmits<{
  (e: 'update:visible', value: number[]): void
  (e: 'update:visibleSlots', value: number[]): void
}>()

function isOn(index: number): boolean {
  return props.visible.includes(index)
}

function toggle(index: number) {
  const next = new Set(props.visible)
  next.has(index) ? next.delete(index) : next.add(index)
  emit('update:visible', [...next].sort((a, b) => a - b))
}

function selectAll() {
  emit('update:visible', props.groups.map((g) => g.index))
}

function clearAll() {
  emit('update:visible', [])
}

function isSlotOn(within: number): boolean {
  return props.visibleSlots.includes(within)
}

function toggleSlot(within: number) {
  const next = new Set(props.visibleSlots)
  next.has(within) ? next.delete(within) : next.add(within)
  emit('update:visibleSlots', [...next].sort((a, b) => a - b))
}

/** chip 里那条小线就是本槽在图上用的线型：只写数字的话，用户得自己去数第几条是虚线。
 *  ECharts 的 'dashed'/'dotted' 不是合法的 SVG dasharray，这里按本组件的画法各给一档。 */
function svgDash(within: number): string | undefined {
  const d = DASH_BY_WITHIN_GROUP[within % DASH_BY_WITHIN_GROUP.length]
  if (d === 'solid') return undefined
  if (d === 'dashed') return '5 3'
  if (d === 'dotted') return '1.5 2.5'
  return (d as number[]).join(' ')
}
</script>

<template>
  <section class="weight-filters">
    <div class="weight-filter-head">
      <h3>测试项</h3>
      <span class="count">已选 {{ visible.length }} / {{ groups.length }}</span>
      <span class="grow" />
      <button type="button" class="text-action" @click="selectAll">全选</button>
      <button type="button" class="text-action muted" @click="clearAll">清空</button>
    </div>

    <div class="weight-chips" role="group" aria-label="测试项开关">
      <label
        v-for="g in groups"
        :key="g.index"
        class="weight-chip weight-chip--group"
        :class="{ 'is-checked': isOn(g.index) }"
      >
        <input
          type="checkbox"
          class="weight-chip-input"
          :checked="isOn(g.index)"
          @change="toggle(g.index)"
        >
        <span
          class="chip-dot"
          :style="{ backgroundColor: groupColor(colors, g.index) }"
          aria-hidden="true"
        />
        <span class="chip-name" :title="g.name">{{ g.name }}</span>
      </label>
    </div>

    <div class="weight-slot-row">
      <h3>组内曲线</h3>
      <div class="weight-chips weight-chips--slots" role="group" aria-label="组内曲线开关">
        <label
          v-for="n in slotTotal"
          :key="n"
          class="weight-chip weight-chip--slot"
          :class="{ 'is-checked': isSlotOn(n - 1) }"
        >
          <input
            type="checkbox"
            class="weight-chip-input"
            :checked="isSlotOn(n - 1)"
            @change="toggleSlot(n - 1)"
          >
          <svg class="chip-line" viewBox="0 0 22 6" aria-hidden="true" focusable="false">
            <line x1="0" y1="3" x2="22" y2="3" stroke="currentColor" stroke-width="1.6" :stroke-dasharray="svgDash(n - 1)" />
          </svg>
          <span class="chip-name">{{ n }}</span>
        </label>
      </div>
      <span class="slots-hint">
        均值线为灰色细虚线 · 这里只关图表，明细表与导出的 xlsx 仍含全部曲线
      </span>
    </div>
  </section>
</template>

<style scoped>
.weight-filters {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

.weight-filter-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.weight-filter-head h3 {
  font-size: var(--p-fs-small);
  font-weight: 700;
  color: var(--text);
}

.weight-filter-head .count {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}

.weight-filter-head .grow {
  flex: 1;
}

/* 一排放得下：标题 + 四颗线型 chip + 说明。分两行会让工作区卡白涨 38px（1280 实测）。 */
.weight-slot-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 9px;
}

.weight-slot-row h3 {
  font-size: var(--p-fs-small);
  font-weight: 700;
  color: var(--text);
}

.slots-hint {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
}

.text-action {
  padding: 2px 4px;
  border: 0;
  border-radius: var(--p-radius-xs);
  background: transparent;
  color: var(--brand);
  font-size: var(--p-fs-micro);
  font-weight: 600;
  cursor: pointer;
}

.text-action.muted {
  color: var(--text-2);
}

.text-action:hover {
  background: color-mix(in srgb, var(--brand) 10%, transparent);
}

.weight-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  max-height: 120px;
  overflow-y: auto;
}

/* 槽位 chip 是单字符，一行放得下；不给它测试项那档 120px 的滚动高度 */
.weight-chips--slots {
  flex: 0 0 auto;
  max-height: none;
  overflow-y: visible;
}

.weight-chip {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  height: 27px;
  padding: 0 9px;
  border: 1px solid var(--border-2);
  border-radius: var(--p-radius-full);
  background: var(--card);
  color: var(--text-2);
  font-size: var(--p-fs-micro);
  font-weight: 600;
  cursor: pointer;
  user-select: none;
  transition: border-color 0.12s, color 0.12s, background 0.12s;
}

.weight-chip--slot {
  min-width: 44px;
  justify-content: center;
  font-variant-numeric: tabular-nums;
}

.weight-chip:hover {
  border-color: var(--brand);
  color: var(--text);
}

.weight-chip.is-checked {
  border-color: var(--brand);
  background: color-mix(in srgb, var(--brand) 8%, var(--card));
  color: var(--text);
}

.weight-chip:focus-within {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
}

.weight-chip-input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}

.chip-dot {
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  border-radius: 50%;
  opacity: 0.35;
  transition: opacity 0.12s;
}

.weight-chip.is-checked .chip-dot {
  opacity: 1;
}

.chip-line {
  width: 22px;
  height: 6px;
  flex: 0 0 22px;
  opacity: 0.45;
  transition: opacity 0.12s;
}

.weight-chip.is-checked .chip-line {
  opacity: 1;
}

.chip-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
