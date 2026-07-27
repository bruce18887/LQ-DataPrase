/**
 * useChart — 统一 ECharts 生命周期 composable
 *
 * 解决 11+ 个图表组件逐字节重复的样板代码：
 * echarts.init / resize / dispose / 主题切换 / 零尺寸容器处理。
 *
 * 支持条件容器（v-if）：当 chartRef 首次变为非 null 时自动初始化。
 *
 * 用法：
 * ```ts
 * // chartRef 由 useTemplateRef('chartRef') 注册，模板里 <div ref="chartRef"> 自动绑定
 * // useTemplateRef 让 vue-tsc 知道该变量被模板使用，避免 TS6133 "declared but never read"
 * const { chartInstance } = useChart(
 *   () => ({ xAxis: { ... }, series: { ... } }),
 *   [() => props.data, () => props.config],
 * )
 * ```
 *
 * buildOption 使用泛型默认 EChartsOption，但允许传入宽松的对象字面量
 * （如 fontWeight: 'bold'），由渲染端在调用时统一断言为 EChartsOption。
 */
import { ref, watch, onMounted, onUnmounted, nextTick, useTemplateRef, type WatchSource, type Ref } from 'vue'
import type * as echarts from 'echarts'
import { useThemeStore } from '../stores/theme'
import { initEchartsWhenReady, type EchartsHandle } from '../utils/echarts-init'

export function useChart<T = echarts.EChartsOption>(
  buildOption: () => T,
  sources?: WatchSource[],
  refKey = 'chartRef',
) {
  const chartRef = useTemplateRef<HTMLElement>(refKey)
  const chartInstance: Ref<echarts.ECharts | null> = ref(null)

  const themeStore = useThemeStore()
  let handle: EchartsHandle | null = null
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let pollTimeout: ReturnType<typeof setTimeout> | null = null
  let disposed = false

  // Expose the ECharts instance on the container DOM for debugging/tests.
  watch(chartInstance, (instance) => {
    if (!chartRef.value) return
    if (instance) {
      ;(chartRef.value as any).__echartsInstance__ = instance
    } else {
      delete (chartRef.value as any).__echartsInstance__
    }
  })

  function renderOption() {
    if (disposed || !chartInstance.value) return
    try {
      const option = buildOption() as unknown as echarts.EChartsOption
      chartInstance.value.setOption(option, { notMerge: true, lazyUpdate: true })
    } catch (err) {
      // Swallow ECharts errors that originate from empty/invalid options during
      // mount/unmount cycles — they can otherwise bubble up through Vue's
      // component update chain and trigger "emitsOptions null" errors in dev.
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.warn('[useChart] setOption failed:', err)
      }
    }
  }

  function ensureInit(): boolean {
    if (disposed) return false
    if (chartInstance.value) {
      // The container may be recreated when a v-if/v-else toggle destroys and
      // remounts the <div ref="chartRef"> (e.g. QQPlotChart resets result=null
      // between loads). A cached instance bound to the old, now-detached node
      // would silently render to nothing — detect that and re-init on the live
      // container. For charts whose container never toggles, the bound DOM is
      // still the same element, so this is a no-op.
      const boundDom = chartInstance.value.getDom?.() as HTMLElement | undefined
      if (chartRef.value && boundDom === chartRef.value && boundDom.isConnected) {
        return true
      }
      try {
        handle?.dispose()
      } catch {
        // Ignore disposal errors during fast mount/unmount cycles
      }
      handle = null
      chartInstance.value = null
    }
    if (!chartRef.value) return false
    try {
      const option = buildOption() as unknown as echarts.EChartsOption
      handle = initEchartsWhenReady(chartRef.value, { option, reuse: true, timeout: 5_000 })
      chartInstance.value = handle.chart
    } catch (err) {
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.warn('[useChart] init failed:', err)
      }
      return false
    }
    // If chart inits asynchronously (zero-size container), poll for readiness
    if (!chartInstance.value) {
      clearPollTimers()
      pollTimer = setInterval(() => {
        if (disposed) { clearPollTimers(); return }
        if (handle?.chart) {
          chartInstance.value = handle.chart
          clearPollTimers()
        }
      }, 100)
      pollTimeout = setTimeout(() => clearPollTimers(), 5_500)
    }
    return true
  }

  function clearPollTimers() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
    if (pollTimeout) { clearTimeout(pollTimeout); pollTimeout = null }
  }

  function resize() {
    chartInstance.value?.resize()
  }

  // ── Data watchers ──
  const watcherSources = sources ?? []
  if (watcherSources.length > 0) {
    watch(watcherSources, () => {
      nextTick(() => {
        if (disposed) return
        if (ensureInit()) renderOption()
      })
    })
  }

  // ── Theme watcher ──
  watch(() => themeStore.currentTheme, () => {
    if (disposed || !chartRef.value?.isConnected) return
    renderOption()
  })

  // ── Lifecycle ──
  onMounted(() => {
    disposed = false
    if (chartRef.value) ensureInit()
    window.addEventListener('resize', resize)
  })

  onUnmounted(() => {
    disposed = true
    clearPollTimers()
    window.removeEventListener('resize', resize)
    handle?.dispose()
    handle = null
    chartInstance.value = null
  })

  return { chartRef, chartInstance }
}
