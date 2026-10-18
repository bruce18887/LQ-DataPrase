import { computed, onMounted, onUnmounted, ref } from 'vue'

/**
 * 表格高度随视口自适应：口径是「表格下缘恒为 1023px」，
 * 顶部带增减一律由表格吸收，页面总高不变。
 */
export function useGridHeight(topOffset: number, minHeight = 320) {
  const tableHeight = ref(Math.max(minHeight, window.innerHeight - topOffset))

  function onResize() {
    tableHeight.value = Math.max(minHeight, window.innerHeight - topOffset)
  }

  onMounted(() => window.addEventListener('resize', onResize))
  onUnmounted(() => window.removeEventListener('resize', onResize))

  const gridWrapperStyle = computed(() => ({
    containIntrinsicSize: `auto ${tableHeight.value}px`,
  }))

  return { tableHeight, gridWrapperStyle }
}
