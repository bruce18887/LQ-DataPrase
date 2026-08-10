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
import { ref, watch, onMounted, onUnmounted, onActivated, nextTick, useTemplateRef, type WatchSource, type Ref } from 'vue'
import type * as echarts from 'echarts'
import { useThemeStore } from '../stores/theme'
import { initEchartsWhenReady, type EchartsHandle } from '../utils/echarts-init'
import { getChartInitOpts } from '../utils/echarts-theme'

export function useChart<T = echarts.EChartsOption>(
  buildOption: () => T,
  sources?: WatchSource[],
  refKey = 'chartRef',
  /** 渲染器 getter：返回当前期望的渲染器（跟随数据量/用户设置变化）；
   * 缺省跟随全局设置。实例渲染器与期望不一致时自动 dispose 重建。 */
  renderer?: () => 'svg' | 'canvas',
) {
  const chartRef = useTemplateRef<HTMLElement>(refKey)
  const chartInstance: Ref<echarts.ECharts | null> = ref(null)

  const themeStore = useThemeStore()
  let handle: EchartsHandle | null = null
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let pollTimeout: ReturnType<typeof setTimeout> | null = null
  let resizeObserver: ResizeObserver | null = null
  let resizeRaf: ReturnType<typeof requestAnimationFrame> | null = null
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

  function desiredRenderer(): 'svg' | 'canvas' {
    return renderer ? renderer() : getChartInitOpts().renderer
  }

  /**
   * 期望渲染器与实际不一致（如大数据量数据到达后要求 canvas）时，dispose 旧实例
   * 并在相同 DOM 重建。echarts.init 对已绑定实例的 DOM 会返回旧实例，必须先 dispose。
   * 返回 true 表示无需重建/已重建完毕可直接 setOption。
   */
  function ensureRenderer(): boolean {
    const chart = chartInstance.value
    if (!chart) return true
    const painter = (chart.getZr?.() as { painter?: { type?: string } } | undefined)?.painter
    if (painter?.type && painter.type !== desiredRenderer()) {
      // 走 handle.dispose() 而非 chart.dispose()：完整清理实例 + ResizeObserver +
      // 轮询定时器，避免旧 handle 残留 observer 对同一容器继续 tryInit
      try { handle?.dispose() } catch { /* ignore */ }
      chartInstance.value = null
      handle = null
      return false
    }
    return true
  }

  function renderOption() {
    if (disposed || !chartInstance.value) return
    if (!ensureRenderer()) {
      // 渲染器切换：init 内部会 setOption（同步就绪时），异步路径由轮询补渲染
      ensureInit()
      return
    }
    try {
      const option = buildOption() as unknown as echarts.EChartsOption
      // notMerge 全量替换会清掉用户点击图例的交互状态（legend.selected）——
      // 从旧 option 读「用户隐藏的 series 名」，按仍存在于新 legend.data 的名字回填
      // selected（只注入 false 项，缺省即显示；名字消失/新增自动按名字匹配，语义与
      // ECharts merge 一致）。无图例或用户未交互时 prevSelected 为空，行为零变化。
      const prevLegend = chartInstance.value.getOption()?.legend
      const prevSelected = (Array.isArray(prevLegend) ? prevLegend[0] : prevLegend)?.selected
      const legend = option.legend as { data?: unknown[]; selected?: Record<string, boolean> } | undefined
      if (prevSelected && legend && Array.isArray(legend.data)) {
        const names = new Set(
          legend.data.map((d: any) => (typeof d === 'string' ? d : d?.name)).filter(Boolean),
        )
        const hidden = Object.entries(prevSelected as Record<string, boolean>)
          .filter(([name, v]) => v === false && names.has(name))
          .map(([name]) => name)
        if (hidden.length) legend.selected = Object.fromEntries(hidden.map((n) => [n, false]))
      }
      // 同步 setOption（不用 lazyUpdate）：lazyUpdate 会把旧 series 元素的移除推迟到下一帧，
      // 该窗口内鼠标事件命中陈旧散点（其 seriesIndex 已不在新模型，如晶圆图站点模式→按结果
      // 切换）会触发 ECharts "[ECharts] model or view can not be found by params" 警告。
      // 批量语义不受影响：ResizeObserver 回调已按帧 coalesce（resizeRaf），Vue watcher 按 tick 批处理。
      chartInstance.value.setOption(option, { notMerge: true })
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
    // 避免 initEchartsWhenReady 的异步等待期间被重复调用，产生多余的 observer/轮询。
    if (handle) {
      if (handle.chart) return true
      // 僵尸 handle：上一次 init 在容器隐藏期间（如 el-tabs 未激活的
      // tab-pane）等待超时——initEchartsWhenReady 5s 后永久断开内部
      // ResizeObserver/轮询，handle.chart 永远为 null。若放任不管，
      // 容器稍后可见时 ensureInit 被此 handle 短路、renderOption 因
      // chartInstance 为空静默空转，图表永久空白。dispose 后走下方
      // 全新 init，容器已可见时同步初始化并渲染最新数据。
      try { handle.dispose() } catch { /* ignore */ }
      handle = null
    }
    try {
      const option = buildOption() as unknown as echarts.EChartsOption
      handle = initEchartsWhenReady(chartRef.value, {
        option, reuse: true, timeout: 5_000, renderer: desiredRenderer(),
      })
      chartInstance.value = handle.chart
    } catch (err) {
      if (import.meta.env.DEV) {
        // eslint-disable-next-line no-console
        console.warn('[useChart] init failed:', err)
      }
      return false
    }
    // If chart inits asynchronously (zero-size container), poll for readiness.
    // Once the instance is available we must re-render with the latest option,
    // because the watcher that triggered ensureInit already fired while the
    // instance was still null and will not fire again until the sources change.
    if (!chartInstance.value) {
      clearPollTimers()
      pollTimer = setInterval(() => {
        if (disposed) { clearPollTimers(); return }
        if (handle?.chart) {
          chartInstance.value = handle.chart
          clearPollTimers()
          renderOption()
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

  function clearResizeRaf() {
    if (resizeRaf != null) {
      cancelAnimationFrame(resizeRaf)
      resizeRaf = null
    }
  }

  function resize() {
    chartInstance.value?.resize()
  }

  /**
   * 持续监听容器尺寸变化。解决 el-tabs/keep-alive/路由缓存 等场景下：
   * - 容器从 display:none /  detached 恢复为可见时，ECharts 实例需要 resize() 才能重绘；
   * - 容器首次获得尺寸时，若异步 init 尚未完成则触发 ensureInit()；
   * - 容器被替换（v-if 切换）后，在新 DOM 上重建 observer。
   */
  function setupResizeObserver() {
    if (typeof ResizeObserver === 'undefined' || !chartRef.value) return
    resizeObserver?.disconnect()
    resizeObserver = new ResizeObserver(() => {
      if (disposed || !chartRef.value?.isConnected) return
      const rect = chartRef.value.getBoundingClientRect()
      if (rect.width === 0 || rect.height === 0) return
      clearResizeRaf()
      resizeRaf = requestAnimationFrame(() => {
        if (disposed || !chartRef.value?.isConnected) return
        if (chartInstance.value) {
          const boundDom = chartInstance.value.getDom?.() as HTMLElement | undefined
          if (boundDom === chartRef.value) {
            resize()
            // 容器刚从隐藏恢复时，lazyUpdate 可能未实际绘制，用当前 option 重新渲染
            renderOption()
          } else {
            ensureInit()
          }
        } else {
          if (ensureInit()) renderOption()
        }
      })
    })
    resizeObserver.observe(chartRef.value)
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
    setupResizeObserver()
    window.addEventListener('resize', resize)
  })

  // keep-alive 重新激活时：DOM 可能从 detached 恢复，实例需要重新校验/resize
  onActivated(() => {
    disposed = false
    if (ensureInit()) {
      resize()
      renderOption()
    }
    setupResizeObserver()
  })

  onUnmounted(() => {
    disposed = true
    clearPollTimers()
    clearResizeRaf()
    resizeObserver?.disconnect()
    resizeObserver = null
    window.removeEventListener('resize', resize)
    handle?.dispose()
    handle = null
    chartInstance.value = null
  })

  return { chartRef, chartInstance }
}
