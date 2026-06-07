/**
 * ECharts 安全初始化工具
 *
 * 解决「lazy 容器 + 异步数据」场景下 ECharts 初始化容器尺寸为 0 的问题：
 * - `el-tabs` 懒挂载、`v-if` 翻转、`<keep-alive>` 激活后首次显示
 * - 父 `el-row/el-col` 布局尚未完成，容器 clientWidth/Height 仍为 0
 * - 直接 `echarts.init(0-size 容器)` 会产生 "Can't get DOM width or height"
 *   警告并保持空白
 *
 * 使用 initEchartsWhenReady 在容器真正具备非零尺寸后再初始化 ECharts。
 */

import * as echarts from 'echarts'
import { getChartInitOpts } from './echarts-theme'

export interface InitWhenReadyOptions {
  /** ECharts 配置项（与原 setOption 一致） */
  option: echarts.EChartsOption
  /** 已存在的实例则直接 setOption（notMerge: true），避免重复 init */
  reuse?: boolean
  /** ResizeObserver/轮询最长等待时间（毫秒） */
  timeout?: number
  /** 轮询检测尺寸间隔（毫秒） */
  pollInterval?: number
}

export interface EchartsHandle {
  /** 已就绪的 ECharts 实例（可能为 null：超时未拿到尺寸） */
  chart: echarts.ECharts | null
  /** 主动释放（dispose 实例 + 清理 ResizeObserver + 取消轮询） */
  dispose: () => void
}

const DEFAULT_TIMEOUT = 5_000
const DEFAULT_POLL = 100

function hasSize(el: HTMLElement | null | undefined): boolean {
  if (!el) return false
  // isConnected 防止元素已被卸载后继续等待
  if (!el.isConnected) return false
  return el.clientWidth > 0 && el.clientHeight > 0
}

/**
 * 在容器具备非零尺寸后初始化（或复用）ECharts 实例并 setOption。
 *
 * 等待策略：优先 ResizeObserver（瞬时变化）→ 兜底 rAF + setInterval 轮询
 * 防止父布局分多帧完成、ResizeObserver 未触发的情况。
 */
export function initEchartsWhenReady(
  container: HTMLElement | null | undefined,
  opts: InitWhenReadyOptions,
): EchartsHandle {
  const { option, reuse = true, timeout = DEFAULT_TIMEOUT, pollInterval = DEFAULT_POLL } = opts

  let chart: echarts.ECharts | null = null
  let disposed = false
  let timer: ReturnType<typeof setInterval> | null = null
  let raf: number | null = null
  let observer: ResizeObserver | null = null
  const cleanup: Array<() => void> = []

  const tryInit = (): boolean => {
    if (disposed) return true
    if (!hasSize(container)) return false
    if (chart) {
      chart.setOption(option, { notMerge: true, lazyUpdate: true })
      return true
    }
    if (reuse) {
      // 先尝试 getInstanceByDom 复用（避免同 DOM 上 init 多次导致 ECharts 警告）
      chart = echarts.getInstanceByDom(container as HTMLElement) || null
    }
    if (!chart) {
      try {
        chart = echarts.init(container as HTMLElement, undefined, getChartInitOpts())
      } catch {
        return false
      }
    }
    chart.setOption(option, { notMerge: true, lazyUpdate: true })
    return true
  }

  const onReady = () => {
    if (tryInit()) {
      // 一旦就绪即停掉 ResizeObserver + 轮询
      observer?.disconnect()
      observer = null
      if (timer) { clearInterval(timer); timer = null }
      if (raf != null) { cancelAnimationFrame(raf); raf = null }
    }
  }

  // 1) 立即尝试一次（容器可能已经就绪）
  if (tryInit()) {
    return {
      chart,
      dispose: () => {
        disposed = true
        observer?.disconnect()
        if (timer) clearInterval(timer)
        if (raf != null) cancelAnimationFrame(raf)
        chart?.dispose()
        chart = null
        cleanup.length = 0
      },
    }
  }

  // 2) ResizeObserver 监听容器尺寸变化
  if (typeof ResizeObserver !== 'undefined' && container) {
    observer = new ResizeObserver(() => onReady())
    observer.observe(container)
    cleanup.push(() => observer?.disconnect())
  }

  // 3) rAF + setInterval 兜底轮询：父布局分多帧完成时 ResizeObserver 可能错过
  raf = requestAnimationFrame(() => {
    raf = null
    onReady()
  })
  timer = setInterval(onReady, pollInterval)
  cleanup.push(() => {
    if (timer) clearInterval(timer)
    if (raf != null) cancelAnimationFrame(raf)
  })

  // 4) 超时兜底：超时后不再尝试 init，但保留 chart 句柄
  const timeoutId = setTimeout(() => {
    observer?.disconnect()
    observer = null
    if (timer) { clearInterval(timer); timer = null }
    if (raf != null) { cancelAnimationFrame(raf); raf = null }
    // 不 throw，调用方可选择重试或忽略
  }, timeout)
  cleanup.push(() => clearTimeout(timeoutId))

  return {
    chart,
    dispose: () => {
      disposed = true
      observer?.disconnect()
      if (timer) clearInterval(timer)
      if (raf != null) cancelAnimationFrame(raf)
      clearTimeout(timeoutId)
      chart?.dispose()
      chart = null
      cleanup.length = 0
    },
  }
}
