/**
 * 单文件分析的图表勾选（5 张）+ 账号级记忆接线
 * ────────────────────────────────────────────────
 * 从 SingleParamTab.vue 抽出：加第 5 张图时那个文件会越过 600 行硬约束，而这块状态
 * 本身是内聚的一层（5 个 ref + 「勾选集 → dock key 列表」+ 记忆读写互斥）。
 * 套用与上报互斥照原实现：套用期间 watcher 不回写，否则把「恢复」当「用户改动」再存一遍。
 *
 * 两条纯逻辑单独导出，由 test/unit/chartToggles.spec.ts 钉住：
 * - `closeChartIn`：面板「×」关闭某图 = 只清它自己的勾选，其余四个不动；
 * - `activeChartKeysOf`：勾选集 → ChartDock 的 active keys，顺序即 reconcile 依据。
 * 这两条此前散在 SingleParamTab.vue 的 `onDockClose` / `computed` 里，没有任何 T2 承重
 * （组件层行为只能靠 T3 才量得到）。
 */
import { computed, nextTick, ref, watch, type Ref } from 'vue'
import { loadChartMemory, saveChartState, type ChartToggles } from '../../../composables/useChartMemory'
import type { ChartKey } from './useChartDock'

/** dock 里五张图的固定出现顺序；`activeChartKeysOf` 只按它过滤，不按勾选先后追加。 */
export const TOGGLE_KEYS: readonly ChartKey[] = ['hist', 'serial', 'qq', 'box', 'site3d']

/**
 * 默认勾选：直方图开（2026-09-13 由常驻改为可关闭），其余关。
 * 3D 默认不勾：勾上会把 dock 从 4 格挤成 5 格，且首次要下载 gl 分包。
 */
export function defaultToggles(): ChartToggles {
  return { hist: true, serial: false, qq: false, box: false, site3d: false }
}

/** 勾选集 → ChartDock 的 activeChartKeys（顺序即初始布局的分块依据）。 */
export function activeChartKeysOf(t: ChartToggles): ChartKey[] {
  return TOGGLE_KEYS.filter((k) => t[k])
}

/** 面板「×」关闭 → 只把该图勾选置 false，其余四个原样（返回新对象，不改入参）。 */
export function closeChartIn(t: ChartToggles, key: ChartKey): ChartToggles {
  const next: ChartToggles = { ...t }
  next[key] = false
  return next
}

export function useChartToggles() {
  const initial = defaultToggles()
  const showHistogram = ref(initial.hist)
  const showSerial = ref(initial.serial)
  const showQQPlot = ref(initial.qq)
  const showBoxPlot = ref(initial.box)
  const showSite3D = ref(initial.site3d)

  const refs: Record<ChartKey, Ref<boolean>> = {
    hist: showHistogram,
    serial: showSerial,
    qq: showQQPlot,
    box: showBoxPlot,
    site3d: showSite3D,
  }

  function snapshot(): ChartToggles {
    return {
      hist: showHistogram.value,
      serial: showSerial.value,
      qq: showQQPlot.value,
      box: showBoxPlot.value,
      site3d: showSite3D.value,
    }
  }
  function applyState(next: ChartToggles) {
    for (const key of TOGGLE_KEYS) refs[key].value = next[key]
  }

  // 顺序即 ChartDock 的 reconcile 依据（新增图追加、取消勾选移除，保留其余相对顺序）
  const activeChartKeys = computed<ChartKey[]>(() => activeChartKeysOf(snapshot()))
  const anyChartVisible = computed(() => activeChartKeys.value.length > 0)

  /** 面板「×」关闭 → 复位对应勾选（与顶部五个勾选同源） */
  function closeChart(key: ChartKey) {
    applyState(closeChartIn(snapshot(), key))
  }

  // 套用与上报互斥：套用期间 watcher 不回写（避免把「恢复」当「用户改动」再存一遍）
  let applying = false
  let touched = false
  watch([showHistogram, showSerial, showQQPlot, showBoxPlot, showSite3D], () => {
    if (applying) return
    touched = true
    saveChartState({ toggles: snapshot() })
  })
  void loadChartMemory().then(({ memoryEnabled, state }) => {
    // 开关关/未加载（null）一律不套用：记忆功能只在明确开启时生效
    if (memoryEnabled !== true || !state.toggles || touched) return
    applying = true
    applyState(state.toggles)
    nextTick(() => { applying = false })
  })

  return {
    showHistogram,
    showSerial,
    showQQPlot,
    showBoxPlot,
    showSite3D,
    activeChartKeys,
    anyChartVisible,
    closeChart,
  }
}
