<template>
  <Teleport to="body">
    <div
      v-if="visible"
      ref="menuEl"
      class="row-highlight-menu"
      role="menu"
      tabindex="-1"
      :style="{ left: `${pos.x}px`, top: `${pos.y}px` }"
      @keydown="onKeydown"
    >
      <div class="row-highlight-menu__header">
        第 {{ rowIndex + 1 }} 行
        <template v-if="serialValue"> · {{ serialValue }}</template>
      </div>
      <div
        ref="itemEl"
        class="row-highlight-menu__item"
        role="menuitem"
        tabindex="0"
        @click="emit('toggle')"
      >
        <el-icon :size="14">
          <StarFilled v-if="highlighted" />
          <Star v-else />
        </el-icon>
        {{ highlighted ? '取消高亮' : '高亮此行' }}
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { nextTick, onUnmounted, ref, watch } from 'vue'
import { Star, StarFilled } from '@element-plus/icons-vue'

const props = defineProps<{
  visible: boolean
  x: number
  y: number
  rowIndex: number
  serialValue: string
  highlighted: boolean
}>()

const emit = defineEmits<{ close: []; toggle: [] }>()

const pos = ref({ x: props.x, y: props.y })
const menuEl = ref<HTMLElement | null>(null)
const itemEl = ref<HTMLElement | null>(null)

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

watch(
  () => props.visible,
  (v) => {
    if (v) {
      pos.value = { x: props.x, y: props.y }
      nextTick(() => {
        const el = menuEl.value
        if (!el) return
        const rect = el.getBoundingClientRect()
        pos.value = {
          x: Math.max(8, Math.min(props.x, window.innerWidth - rect.width - 8)),
          y: Math.max(8, Math.min(props.y, window.innerHeight - rect.height - 8)),
        }
        itemEl.value?.focus()
      })
      document.addEventListener('mousedown', onDocMouseDown, true)
      document.addEventListener('keydown', onKeydownGlobal)
      document.addEventListener('wheel', onWheelGlobal, { capture: true, passive: true })
      window.addEventListener('resize', onResizeGlobal)
    } else {
      cleanup()
    }
  },
)

onUnmounted(cleanup)

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    emit('toggle')
  } else if (e.key === 'Escape') {
    onClose()
  }
}
</script>

<style scoped>
.row-highlight-menu {
  position: fixed;
  z-index: 3000;
  min-width: 180px;
  padding: 4px;
  border-radius: 6px;
  border: 1px solid var(--border-2);
  background: var(--bg);
  box-shadow: var(--shadow-lg);
  font-size: var(--p-fs-small);
  color: var(--text);
}

.row-highlight-menu__header {
  padding: 6px 10px;
  font-size: var(--p-fs-dense);
  color: var(--text-2);
  white-space: nowrap;
}

.row-highlight-menu__item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
  color: var(--text);
}

.row-highlight-menu__item:hover,
.row-highlight-menu__item:focus {
  background: var(--bg-3);
  outline: none;
}
</style>
