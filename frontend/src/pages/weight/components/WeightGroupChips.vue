<script setup lang="ts">
import { groupColor, type WeightGroupDto } from '../weightChartOption'

const props = defineProps<{ groups: WeightGroupDto[]; visible: number[]; colors: string[] }>()
const emit = defineEmits<{ (e: 'update:visible', value: number[]): void }>()

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
</script>

<template>
  <section class="weight-groups">
    <div class="weight-groups-head">
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
        class="weight-chip"
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

    <p class="weight-groups-hint">
      同组四条按 <b>线型</b> 区分（实线 / 虚线 / 点线 / 点划线）· 均值线为灰色细虚线
    </p>
  </section>
</template>

<style scoped>
.weight-groups {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

.weight-groups-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.weight-groups-head h3 {
  font-size: var(--p-fs-small);
  font-weight: 700;
  color: var(--text);
}

.weight-groups-head .count {
  font-size: var(--p-fs-micro);
  color: var(--text-2);
  font-variant-numeric: tabular-nums;
}

.weight-groups-head .grow {
  flex: 1;
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

.chip-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.weight-groups-hint {
  margin-top: 7px;
  font-size: var(--p-fs-micro);
  color: var(--text-2);
}

.weight-groups-hint b {
  color: var(--text);
  font-weight: 600;
}
</style>
