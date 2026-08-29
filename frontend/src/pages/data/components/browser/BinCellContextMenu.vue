<template>
  <Teleport to="body">
    <div
      v-if="visible"
      ref="menuEl"
      class="bin-cell-menu"
      role="menu"
      tabindex="-1"
      :style="{ left: `${pos.x}px`, top: `${pos.y}px` }"
      @keydown="onKeydown"
    >
      <div class="bin-cell-menu__header">
        第 {{ rowIndex + 1 }} 行 · Bin = <span class="bin-cell-menu__bin">{{ binValue }}</span>
        <template v-if="failCols.length > 1"> · {{ failCols.length }} 个 Fail</template>
      </div>
      <div
        ref="itemEl"
        class="bin-cell-menu__item"
        role="menuitem"
        tabindex="0"
        @click="onGotoFail"
      >
        <el-icon :size="14"><WarningFilled /></el-icon>
        定位到 Fail 单元格
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onUnmounted } from 'vue'
import { WarningFilled } from '@element-plus/icons-vue'

const props = defineProps<{
  visible: boolean
  x: number
  y: number
  rowIndex: number
  binValue: string | number | null
  failCols: string[]
}>()

const emit = defineEmits<{ close: []; 'goto-fail': [rowIndex: number] }>()

// 夹紧后的位置（右键点可能贴近视口边缘，测出菜单尺寸后向内收）
const pos = ref({ x: props.x, y: props.y })
const menuEl = ref<HTMLElement | null>(null)
const itemEl = ref<HTMLElement | null>(null)

// 仅菜单可见时挂全局监听；onUnmounted 兜底清理（keep-alive 下 v-if 卸载路径）
const onClose = () => emit('close')
const onDocMouseDown = (e: MouseEvent) => {
  if (!menuEl.value?.contains(e.target as Node)) onClose()
}
const onKeydownGlobal = (e: KeyboardEvent) => {
  if (e.key === 'Escape') onClose()
}
const onWheelGlobal = () => onClose() // 菜单开着滚表格 → 关闭
const onResizeGlobal = () => onClose()

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
        // 键盘可达：打开时聚焦菜单项，Enter/Space 触发
        itemEl.value?.focus()
      })
      document.addEventListener('mousedown', onDocMouseDown, true)
      document.addEventListener('keydown', onKeydownGlobal)
      document.addEventListener('wheel', onWheelGlobal, { capture: true, passive: true })
      window.addEventListener('resize', onResizeGlobal)
    } else {
      document.removeEventListener('mousedown', onDocMouseDown, true)
      document.removeEventListener('keydown', onKeydownGlobal)
      document.removeEventListener('wheel', onWheelGlobal, { capture: true })
      window.removeEventListener('resize', onResizeGlobal)
    }
  },
)

onUnmounted(() => {
  document.removeEventListener('mousedown', onDocMouseDown, true)
  document.removeEventListener('keydown', onKeydownGlobal)
  document.removeEventListener('wheel', onWheelGlobal, { capture: true })
  window.removeEventListener('resize', onResizeGlobal)
})

function onGotoFail() {
  emit('goto-fail', props.rowIndex)
}

// 菜单项键盘操作：Enter/Space 触发，ArrowUp/Down 轮转（当前单一项，结构预留）
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    onGotoFail()
  } else if (e.key === 'Escape') {
    onClose()
  }
}
</script>

<style scoped>
.bin-cell-menu {
  position: fixed;
  z-index: 3000; /* 高于 el-dialog(~2000)：菜单可叠加在对话框之上 */
  min-width: 200px;
  padding: 4px;
  border-radius: 6px;
  border: 1px solid var(--border-2);
  background: var(--bg);
  box-shadow: var(--shadow-lg);
  font-size: 13px;
  color: var(--text);
}

.bin-cell-menu__header {
  padding: 6px 10px;
  font-size: 12px;
  color: var(--text-2);
  white-space: nowrap;
}

.bin-cell-menu__bin {
  color: var(--error);
  font-weight: bold;
}

.bin-cell-menu__item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
  color: var(--error);
}

.bin-cell-menu__item:hover,
.bin-cell-menu__item:focus {
  background: var(--bg-3);
  outline: none;
}
</style>
