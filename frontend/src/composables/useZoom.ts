/**
 * useZoom — 全局 Ctrl+滚轮页面缩放
 *
 * 支持 Electron 与浏览器两种运行环境：
 * - Electron：调用主进程 webContents.setZoomFactor，缩放原生且与系统菜单一致
 * - 浏览器：通过 CSS zoom 属性缩放 <html> 元素
 *
 * 缩放范围 0.5 ~ 2.0，步进 0.1，持久化到 localStorage。
 * Ctrl+0 可快速恢复 100%。
 */
import { ref, onMounted, onUnmounted } from 'vue'

const STORAGE_KEY = 'lqdp-zoom-factor'
const MIN_ZOOM = 0.5
const MAX_ZOOM = 2.0
const STEP = 0.1

function clampZoom(value: number): number {
  return Math.min(Math.max(value, MIN_ZOOM), MAX_ZOOM)
}

function isElectron(): boolean {
  return typeof window !== 'undefined' && typeof window.electronAPI !== 'undefined'
}

export function useZoom() {
  const zoom = ref(1)

  async function applyZoomFactor(value: number): Promise<void> {
    const clamped = clampZoom(value)
    zoom.value = Math.round(clamped * 100) / 100
    try {
      localStorage.setItem(STORAGE_KEY, String(zoom.value))
    } catch {
      // localStorage 不可用时不影响功能
    }

    if (isElectron()) {
      await window.electronAPI?.setZoomFactor(zoom.value)
    } else {
      document.documentElement.style.zoom = String(zoom.value)
    }
  }

  function zoomIn(): void {
    applyZoomFactor(zoom.value + STEP)
  }

  function zoomOut(): void {
    applyZoomFactor(zoom.value - STEP)
  }

  function resetZoom(): void {
    applyZoomFactor(1)
  }

  async function initZoom(): Promise<void> {
    let initial = 1
    if (isElectron()) {
      try {
        initial = (await window.electronAPI?.getZoomFactor()) ?? 1
      } catch {
        initial = 1
      }
    }

    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored !== null) {
      const parsed = parseFloat(stored)
      if (!Number.isNaN(parsed)) {
        initial = parsed
      }
    }

    await applyZoomFactor(initial)
  }

  function onWheel(event: WheelEvent): void {
    if (!event.ctrlKey) return

    // 避免浏览器默认缩放行为与自定义逻辑冲突
    event.preventDefault()

    if (event.deltaY < 0) {
      zoomIn()
    } else if (event.deltaY > 0) {
      zoomOut()
    }
  }

  function onKeyDown(event: KeyboardEvent): void {
    if (event.ctrlKey && event.key === '0') {
      event.preventDefault()
      resetZoom()
    }
  }

  onMounted(() => {
    initZoom()
    window.addEventListener('wheel', onWheel, { passive: false })
    window.addEventListener('keydown', onKeyDown)
  })

  onUnmounted(() => {
    window.removeEventListener('wheel', onWheel)
    window.removeEventListener('keydown', onKeyDown)
  })

  return {
    zoom,
    zoomIn,
    zoomOut,
    resetZoom,
  }
}
