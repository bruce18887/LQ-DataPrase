<template>
  <Teleport to="body">
    <div
      v-if="visible"
      ref="menuEl"
      class="header-context-menu"
      role="menu"
      tabindex="-1"
      :style="{ left: `${pos.x}px`, top: `${pos.y}px` }"
      @keydown="onKeydown"
    >
      <div class="header-context-menu__header" :title="colName">{{ colName }}</div>
      <div
        ref="copyEl"
        class="header-context-menu__item"
        role="menuitem"
        tabindex="0"
        @click="emit('copy')"
      >
        <el-icon :size="14"><DocumentCopy /></el-icon>
        {{ copyLabel }}
      </div>
      <div
        ref="histEl"
        class="header-context-menu__item"
        :class="{ 'is-disabled': !isNumeric }"
        role="menuitem"
        :tabindex="isNumeric ? 0 : -1"
        :aria-disabled="!isNumeric"
        @click="onShowHistogram"
      >
        <el-icon :size="14"><TrendCharts /></el-icon>
        展示分布图
        <span v-if="!isNumeric" class="header-context-menu__hint">非数值列</span>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { DocumentCopy, TrendCharts } from '@element-plus/icons-vue'
import { headerMenuCopyLabel } from './browserColumns'

const props = defineProps<{
  visible: boolean
  x: number
  y: number
  colName: string
  isSystem: boolean
  isNumeric: boolean
}>()

const emit = defineEmits<{ close: []; copy: []; 'show-histogram': [] }>()

const copyLabel = computed(() => headerMenuCopyLabel(props.isSystem))

const pos = ref({ x: props.x, y: props.y })
const menuEl = ref<HTMLElement | null>(null)
const copyEl = ref<HTMLElement | null>(null)
const histEl = ref<HTMLElement | null>(null)

const onClose = () => emit('close')
const onDocMouseDown = (e: MouseEvent) => {
  if (!menuEl.value?.contains(e.target as Node)) onClose()
}
const onKeydownGlobal = (e: KeyboardEvent) => {
  if (e.key === 'Escape') onClose()
}
const onWheelGlobal = () => onClose()
const onResizeGlobal = () => onClose()

function cleanup() {
  document.removeEventListener('mousedown', onDocMouseDown, true)
  document.removeEventListener('keydown', onKeydownGlobal)
  document.removeEventListener('wheel', onWheelGlobal, { capture: true, passive: true } as any)
  window.removeEventListener('resize', onResizeGlobal)
}

/**
 * 按当前 props.x/y 定位并在视口内夹紧。
 * 菜单开着时换列右键：visible 仍是 true，必须靠 x/y watcher 重新定位。
 */
function positionMenu(focusItem = false) {
  pos.value = { x: props.x, y: props.y }
  nextTick(() => {
    const el = menuEl.value
    if (!el) return
    const rect = el.getBoundingClientRect()
    pos.value = {
      x: Math.max(8, Math.min(props.x, window.innerWidth - rect.width - 8)),
      y: Math.max(8, Math.min(props.y, window.innerHeight - rect.height - 8)),
    }
    if (focusItem) copyEl.value?.focus()
  })
}

watch(
  () => props.visible,
  (v) => {
    if (v) {
      positionMenu(true)
      document.addEventListener('mousedown', onDocMouseDown, true)
      document.addEventListener('keydown', onKeydownGlobal)
      document.addEventListener('wheel', onWheelGlobal, { capture: true, passive: true })
      window.addEventListener('resize', onResizeGlobal)
    } else {
      cleanup()
    }
  },
)

watch(
  () => [props.x, props.y],
  () => {
    if (props.visible) positionMenu(false)
  },
)

onUnmounted(cleanup)

function onShowHistogram() {
  if (props.isNumeric) emit('show-histogram')
}

function focusableItems(): HTMLElement[] {
  return [copyEl.value, histEl.value].filter(Boolean) as HTMLElement[]
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault()
    const items = focusableItems()
    if (!items.length) return
    const idx = items.indexOf(document.activeElement as HTMLElement)
    const dir = e.key === 'ArrowDown' ? 1 : -1
    const next = (idx + dir + items.length) % items.length
    items[next]?.focus()
  } else if (e.key === 'Enter' || e.key === ' ') {
    if (document.activeElement === copyEl.value) {
      e.preventDefault()
      emit('copy')
    } else if (document.activeElement === histEl.value && props.isNumeric) {
      e.preventDefault()
      emit('show-histogram')
    }
  } else if (e.key === 'Escape') {
    onClose()
  }
}
</script>

<style scoped>
.header-context-menu {
  position: fixed;
  z-index: 3000; /* 高于 el-dialog(~2000)：菜单可叠加在对话框之上 */
  min-width: 200px;
  max-width: 320px;
  padding: 4px;
  border-radius: 6px;
  border: 1px solid var(--border-2);
  background: var(--bg);
  box-shadow: var(--shadow-lg);
  font-size: var(--p-fs-small);
  color: var(--text);
}

.header-context-menu__header {
  padding: 6px 10px;
  font-size: var(--p-fs-dense);
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-context-menu__item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
  color: var(--text);
}

.header-context-menu__item:hover,
.header-context-menu__item:focus {
  background: var(--bg-3);
  outline: none;
}

.header-context-menu__item.is-disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}

.header-context-menu__item.is-disabled:hover {
  background: transparent;
}

.header-context-menu__hint {
  margin-left: auto;
  padding-left: 12px;
  font-size: var(--p-fs-micro);
  color: var(--text-3);
}
</style>
