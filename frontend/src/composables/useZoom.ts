/**
 * useZoom — 全局 Ctrl+滚轮页面缩放
 *
 * 支持 Electron 与浏览器两种运行环境：
 * - Electron：调用主进程 webContents.setZoomFactor，缩放原生且与系统菜单一致
 * - 浏览器：通过 CSS zoom 属性缩放 <html> 元素
 *
 * 缩放范围 0.5 ~ 2.0，步进 0.1，持久化到 localStorage。
 * Ctrl+0 可快速恢复 100%。
 *
 * 缩放时通过 showIndicator 显示当前百分比气泡（停止缩放后自动隐藏），
 * 由 ZoomIndicator.vue 消费。zoom / showIndicator 为模块级单例状态，
 * 任意组件调用 useZoom() 均共享同一份状态。
 */
import { ref, onMounted, onUnmounted } from 'vue'
import { safeGetItem, safeSetItem } from '../utils/safeStorage'

const STORAGE_KEY = 'lqdp-zoom-factor'
const MIN_ZOOM = 0.5
const MAX_ZOOM = 2.0
const STEP = 0.1
/** 停止缩放后指示器自动隐藏的延迟（毫秒） */
const INDICATOR_HIDE_DELAY = 800

// 模块级单例状态：App.vue（绑定事件）与 ZoomIndicator.vue（消费状态）共享
const zoom = ref(1)
const showIndicator = ref(false)
let indicatorTimer: ReturnType<typeof setTimeout> | null = null
// 调用方引用计数：首个挂载者负责初始化/绑定全局监听，最后一个卸载者才解绑。
// 不能用布尔 initialized —— ZoomIndicator（v-if 随气泡显示短暂挂载）卸载时
// 会把仍挂载的 App.vue 的全局监听误删，导致缩放功能永久失效。
let refCount = 0

function clampZoom(value: number): number {
  return Math.min(Math.max(value, MIN_ZOOM), MAX_ZOOM)
}

function isElectron(): boolean {
  return typeof window !== 'undefined' && typeof window.electronAPI !== 'undefined'
}

export function useZoom() {
  async function applyZoomFactor(value: number, silent = false): Promise<void> {
    const clamped = clampZoom(value)
    zoom.value = Math.round(clamped * 100) / 100
    // 统一走 safeSetItem（此前同文件 setItem 有 try/catch 而 getItem 无——不一致）
    safeSetItem(STORAGE_KEY, String(zoom.value))

    if (isElectron()) {
      await window.electronAPI?.setZoomFactor(zoom.value)
    } else {
      document.documentElement.style.zoom = String(zoom.value)
    }

    // 用户缩放（非初始化静默应用）时显示百分比指示器，防抖后自动隐藏
    if (!silent) {
      showIndicator.value = true
      if (indicatorTimer) clearTimeout(indicatorTimer)
      indicatorTimer = setTimeout(() => {
        showIndicator.value = false
      }, INDICATOR_HIDE_DELAY)
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

    // 统一走 safeGetItem（此前裸调 localStorage.getItem 无 try/catch，
    // 而同文件 setItem 有——不一致，Electron 磁盘异常时此处会抛异常导致缩放初始化失败）
    const stored = safeGetItem(STORAGE_KEY)
    if (stored !== null) {
      const parsed = parseFloat(stored)
      if (!Number.isNaN(parsed)) {
        initial = parsed
      }
    }

    // 初始化静默应用，避免页面加载时闪烁指示器
    await applyZoomFactor(initial, true)
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
    // 仅首个挂载的调用者（App.vue）负责初始化与事件绑定，后续调用者
    // （ZoomIndicator 等）只消费单例状态，避免 wheel 监听重复导致一次
    // 滚动缩放两次
    if (refCount++ > 0) return
    initZoom()
    window.addEventListener('wheel', onWheel, { passive: false })
    window.addEventListener('keydown', onKeyDown)
  })

  onUnmounted(() => {
    // 引用计数归零（所有调用者都卸载）才解绑；App.vue 常驻，全局监听
    // 在其生命周期内始终有效
    if (--refCount > 0) return
    window.removeEventListener('wheel', onWheel)
    window.removeEventListener('keydown', onKeyDown)
  })

  return {
    zoom,
    showIndicator,
    zoomIn,
    zoomOut,
    resetZoom,
  }
}
