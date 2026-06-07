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
 * const { chartRef, chartInstance } = useChart(
 *   () => ({ xAxis: { ... }, series: { ... } }),
 *   [() => props.data, () => props.config],
 * )
 * ```
 */
import { ref, watch, onMounted, onUnmounted, nextTick, type WatchSource, type Ref } from 'vue'
import type * as echarts from 'echarts'
import { useThemeStore } from '../stores/theme'
import { initEchartsWhenReady, type EchartsHandle } from '../utils/echarts-init'

export function useChart(
  buildOption: () => echarts.EChartsOption,
  sources?: WatchSource[],
) {
  const chartRef = ref<HTMLElement>()
  const chartInstance: Ref<echarts.ECharts | null> = ref(null)

  const themeStore = useThemeStore()
  let handle: EchartsHandle | null = null

  function renderOption() {
    if (!chartInstance.value) return
    const option = buildOption()
    chartInstance.value.setOption(option, { notMerge: true, lazyUpdate: true })
  }

  function ensureInit(): boolean {
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
      handle?.dispose()
      handle = null
      chartInstance.value = null
    }
    if (!chartRef.value) return false
    const option = buildOption()
    handle = initEchartsWhenReady(chartRef.value, { option, reuse: true, timeout: 5_000 })
    chartInstance.value = handle.chart
    // If chart inits asynchronously (zero-size container), poll for readiness
    if (!chartInstance.value) {
      const poll = setInterval(() => {
        if (handle?.chart) {
          chartInstance.value = handle.chart
          clearInterval(poll)
        }
      }, 100)
      setTimeout(() => clearInterval(poll), 5_500)
    }
    return true
  }

  function resize() {
    chartInstance.value?.resize()
  }

  // ── Data watchers ──
  const watcherSources = sources ?? []
  if (watcherSources.length > 0) {
    watch(watcherSources, () => {
      nextTick(() => {
        if (ensureInit()) renderOption()
      })
    })
  }

  // ── Theme watcher ──
  watch(() => themeStore.currentTheme, () => {
    if (!chartRef.value?.isConnected) return
    renderOption()
  })

  // ── Lifecycle ──
  onMounted(() => {
    if (chartRef.value) ensureInit()
    window.addEventListener('resize', resize)
  })

  onUnmounted(() => {
    window.removeEventListener('resize', resize)
    handle?.dispose()
    handle = null
    chartInstance.value = null
  })

  return { chartRef, chartInstance }
}
