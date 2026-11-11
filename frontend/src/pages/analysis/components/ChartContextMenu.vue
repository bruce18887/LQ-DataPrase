<template>
  <Teleport to="body">
    <div
      v-if="menu.visible"
      class="chart-ctx-menu"
      :style="{ left: menu.x + 'px', top: menu.y + 'px' }"
      data-chart-context-menu
      role="menu"
      @contextmenu.prevent
    >
      <button type="button" role="menuitem" data-menu-create-subset @click="emit('create')">新建子集直方图</button>
      <button type="button" role="menuitem" data-menu-clear-selection @click="emit('clear')">清除选择</button>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { watch, onBeforeUnmount } from 'vue'
import type { BrushMenu } from '../composables/useChartBrushSelect'

const props = defineProps<{ menu: BrushMenu }>()
const emit = defineEmits<{ create: []; clear: []; close: [] }>()

function onWindowDown(ev: MouseEvent) {
  const inside = (ev.target as HTMLElement)?.closest?.('[data-chart-context-menu]')
  if (!inside) emit('close')
}
function onKey(ev: KeyboardEvent) { if (ev.key === 'Escape') emit('close') }

watch(() => props.menu.visible, (visible) => {
  if (visible) {
    window.addEventListener('mousedown', onWindowDown, true)
    window.addEventListener('keydown', onKey)
  } else {
    window.removeEventListener('mousedown', onWindowDown, true)
    window.removeEventListener('keydown', onKey)
  }
})
onBeforeUnmount(() => {
  window.removeEventListener('mousedown', onWindowDown, true)
  window.removeEventListener('keydown', onKey)
})
</script>

<style scoped>
.chart-ctx-menu {
  position: fixed;
  z-index: 3000;
  min-width: 160px;
  padding: 4px;
  background: var(--bg-2, #fff);
  border: 1px solid var(--border-2, #e4e7ed);
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
}
.chart-ctx-menu button {
  display: block;
  width: 100%;
  border: 0;
  background: transparent;
  text-align: left;
  padding: 6px 10px;
  border-radius: 4px;
  font-size: var(--p-fs-dense);
  color: var(--text);
  cursor: pointer;
}
.chart-ctx-menu button:hover {
  background: color-mix(in srgb, var(--brand) 12%, transparent);
  color: var(--brand);
}
</style>