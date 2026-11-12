/**
 * 图表框选（zrender 指针事件 + DOM 高亮浮层，spec §5.3）。
 * 不用 ECharts brush 组件：useChart 每次 setOption(notMerge) 会清掉 brush areas
 * 与光标态；自有选区状态 + DOM 浮层可在重渲染后按数据坐标重定位，large 模式确定。
 *
 * value-range 模式（直方图）：只取 X 分量，浮层占满 grid 全高，D6 兜底柱无界。
 * rect 模式（散点）：逐 lane 与 grid 矩形求交 → convertFromPixel → 点集命中取 serial。
 */
import { ref, watch, onBeforeUnmount, type Ref } from 'vue'
import type * as echarts from 'echarts'
import {
  normalizeRect, intersectRects, normalizeRange, pickSerials, mergeSerials,
  valueRangeWithOverflow, type PxRect, type DataPoint, type ChartSelection,
} from './selectionGeometry'

export type { ChartSelection } from './selectionGeometry'

export interface BrushMenu { visible: boolean; x: number; y: number }
interface GridRect { x: number; y: number; width: number; height: number }
interface RectLane { lane: number; xRange: [number, number]; yRange: [number, number] }

const MIN_DRAG_PX = 3

export function useChartBrushSelect(opts: {
  mode: 'value-range' | 'rect'
  chartInstance: Ref<echarts.ECharts | null>
  container: Ref<HTMLElement | null>
  enabled: () => boolean
  getLanes?: () => { points: DataPoint[] }[]
  getBinCenters?: () => number[]
  serialCol?: () => string | undefined
  onCreate: (sel: ChartSelection) => void
  /** rect 模式：mouseup 算出选区后立即消费（onCreate + clearSelection），不等右键菜单；
   *  value-range 模式忽略此项（直方图仍走「框选 → 右键 → 新建子集」）。 */
  immediate?: boolean
  /** 右键菜单开门的附加条件：无选区但它返回 true 也允许开门（如高亮激活时右键「清除高亮」）。 */
  canMenu?: () => boolean
}) {
  const menu = ref<BrushMenu>({ visible: false, x: 0, y: 0 })
  const selection = ref<ChartSelection | null>(null)
  let rectLanes: RectLane[] = []
  let overlays: HTMLDivElement[] = []
  let drag: { start: { x: number; y: number }; cur: { x: number; y: number } } | null = null
  let bound: echarts.ECharts | null = null

  function gridRects(chart: echarts.ECharts): GridRect[] {
    const out: GridRect[] = []
    // getModel 在 echarts 类型里是 private（运行时公开），取 grid 坐标系矩形只能走它
    const model = (chart as any).getModel()
    for (let i = 0; ; i++) {
      const g = model.getComponent('grid', i)
      if (!g) break
      const cs = g.coordinateSystem
      if (cs?.getRect) out.push(cs.getRect() as GridRect)
    }
    return out
  }

  function clearOverlays() {
    for (const el of overlays) el.remove()
    overlays = []
  }

  function makeOverlay(rect: PxRect) {
    const el = opts.container.value
    if (!el) return
    const div = document.createElement('div')
    div.className = 'chart-brush-overlay'
    div.style.cssText = `position:absolute;pointer-events:none;z-index:5;`
      + `left:${rect.x0}px;top:${rect.y0}px;width:${rect.x1 - rect.x0}px;height:${rect.y1 - rect.y0}px;`
      + `background:color-mix(in srgb, var(--brand) 15%, transparent);`
      + `border:1px solid color-mix(in srgb, var(--brand) 60%, transparent);`
    el.appendChild(div)
    overlays.push(div)
  }

  /** 按当前数据坐标重画浮层（重渲染/resize 后调用）。 */
  function drawOverlays() {
    clearOverlays()
    const chart = opts.chartInstance.value
    const sel = selection.value
    if (!chart || !sel) return
    const grids = gridRects(chart)
    if (sel.kind === 'value_range') {
      const g = grids[0]
      if (!g) return
      const x0 = sel.lo != null ? (chart.convertToPixel({ xAxisIndex: 0 }, sel.lo) as number) : g.x
      const x1 = sel.hi != null ? (chart.convertToPixel({ xAxisIndex: 0 }, sel.hi) as number) : g.x + g.width
      const inter = intersectRects(
        { x0: Math.min(x0, x1), y0: g.y, x1: Math.max(x0, x1), y1: g.y + g.height },
        { x0: g.x, y0: g.y, x1: g.x + g.width, y1: g.y + g.height })
      if (inter) makeOverlay(inter)
      return
    }
    for (const rl of rectLanes) {
      const g = grids[rl.lane]
      if (!g) continue
      const px0 = chart.convertToPixel({ xAxisIndex: rl.lane }, rl.xRange[0]) as number
      const px1 = chart.convertToPixel({ xAxisIndex: rl.lane }, rl.xRange[1]) as number
      const py0 = chart.convertToPixel({ yAxisIndex: rl.lane }, rl.yRange[1]) as number
      const py1 = chart.convertToPixel({ yAxisIndex: rl.lane }, rl.yRange[0]) as number
      const inter = intersectRects(normalizeRect({ x: px0, y: py0 }, { x: px1, y: py1 }),
        { x0: g.x, y0: g.y, x1: g.x + g.width, y1: g.y + g.height })
      if (inter) makeOverlay(inter)
    }
  }

  function localPoint(ev: MouseEvent): { x: number; y: number } | null {
    const el = opts.container.value
    if (!el) return null
    const r = el.getBoundingClientRect()
    return { x: ev.clientX - r.left, y: ev.clientY - r.top }
  }

  function onZrMouseDown(e: any) {
    const ev = e.event as MouseEvent
    if (ev.button !== 0 || !opts.enabled()) return
    if (!opts.chartInstance.value || !opts.container.value) return
    // 光标 bug：按下非可选画布时，浏览器把折叠 caret 塞进当前焦点可编辑节点
    // （实测落在参数选择器 el-select 的隐藏 input）。该放置发生在事件派发前的
    // 输入处理阶段，pointerdown/mousedown 的 preventDefault 都拦不住（e2e 实测）；
    // 且拖拽移动期间浏览器会反复往焦点编辑框重放 caret——故按下/移动/抬起三处
    // 都清文档选区，保证拖拽全程与结束后选区为空。
    window.getSelection()?.removeAllRanges()
    clearOverlays()
    selection.value = null
    rectLanes = []
    drag = { start: { x: e.offsetX, y: e.offsetY }, cur: { x: e.offsetX, y: e.offsetY } }
    window.addEventListener('mousemove', onWinMove)
    window.addEventListener('mouseup', onWinUp)
  }

  /**
   * 阻断原生文本选择（光标 bug 双保险之一）。
   * 注意不能在 zrender 的 e.event 上 preventDefault——zrender 6 收到的是 pointerdown，
   * 按 Pointer Events 规范取消它会连带抑制 compat mouseup，框选依赖的 window mouseup
   * 收不到事件 → 选区永远建不起来。改在 compat mousedown 的 capture 阶段拦左键默认
   * 动作：文本选择被阻断，mousemove/mouseup 链与右键 contextmenu 不受影响（e2e 实测）。
   * 折叠插入光标不走默认动作链，由 onZrMouseDown 的 removeAllRanges 负责清除。
   */
  function onNativeMouseDown(ev: MouseEvent) {
    if (ev.button === 0 && opts.enabled()) ev.preventDefault()
  }

  function onWinMove(ev: MouseEvent) {
    if (!drag) return
    // 拖拽移动会把折叠 caret 反复重放进焦点编辑框（见 onZrMouseDown 注释），随移随清
    window.getSelection()?.removeAllRanges()
    if (!(ev.buttons & 1)) {
      window.removeEventListener('mousemove', onWinMove)
      window.removeEventListener('mouseup', onWinUp)
      drag = null
      clearOverlays()
      return
    }
    const p = localPoint(ev)
    if (!p) return
    drag.cur = p
    const chart = opts.chartInstance.value
    if (!chart) return
    clearOverlays()
    const r = normalizeRect(drag.start, drag.cur)
    if (opts.mode === 'value-range') {
      const g = gridRects(chart)[0]
      if (g) makeOverlay({ x0: r.x0, y0: g.y, x1: r.x1, y1: g.y + g.height })
    } else {
      makeOverlay(r)
    }
  }

  function onWinUp(ev: MouseEvent) {
    window.removeEventListener('mousemove', onWinMove)
    window.removeEventListener('mouseup', onWinUp)
    // 抬起同样可能重放 caret：拖拽结束再清一次，钉死「拖拽后选区为空」判据
    window.getSelection()?.removeAllRanges()
    if (!drag) return
    const p = localPoint(ev)
    if (!p) { drag = null; clearOverlays(); return }
    drag.cur = p
    const r = normalizeRect(drag.start, drag.cur)
    drag = null
    if (r.x1 - r.x0 < MIN_DRAG_PX && r.y1 - r.y0 < MIN_DRAG_PX) { clearOverlays(); return }
    const chart = opts.chartInstance.value
    if (!chart) { clearOverlays(); return }
    const grids = gridRects(chart)
    if (opts.mode === 'value-range') {
      const g = grids[0]
      if (!g) { clearOverlays(); return }
      const cx0 = Math.max(r.x0, g.x)
      const cx1 = Math.min(r.x1, g.x + g.width)
      if (cx1 <= cx0) { clearOverlays(); return }
      const v0 = chart.convertFromPixel({ xAxisIndex: 0 }, cx0) as number
      const v1 = chart.convertFromPixel({ xAxisIndex: 0 }, cx1) as number
      const [lo, hi] = normalizeRange(v0, v1)
      const bounded = valueRangeWithOverflow(lo, hi, opts.getBinCenters?.() ?? [])
      if (bounded.lo == null && bounded.hi == null) { clearOverlays(); return }
      selection.value = { kind: 'value_range', lo: bounded.lo, hi: bounded.hi }
      drawOverlays()
      return
    }
    const lanes = opts.getLanes?.() ?? []
    const groups: (number | string)[][] = []
    rectLanes = []
    grids.forEach((g, i) => {
      const inter = intersectRects(r, { x0: g.x, y0: g.y, x1: g.x + g.width, y1: g.y + g.height })
      if (!inter || !lanes[i]) return
      const xRange = normalizeRange(
        chart.convertFromPixel({ xAxisIndex: i }, inter.x0) as number,
        chart.convertFromPixel({ xAxisIndex: i }, inter.x1) as number)
      const yRange = normalizeRange(
        chart.convertFromPixel({ yAxisIndex: i }, inter.y0) as number,
        chart.convertFromPixel({ yAxisIndex: i }, inter.y1) as number)
      const picked = pickSerials(lanes[i].points, xRange, yRange)
      if (picked.length) {
        rectLanes.push({ lane: i, xRange, yRange })
        groups.push(picked)
      }
    })
    const serials = mergeSerials(groups)
    if (!serials.length) { clearOverlays(); rectLanes = []; return }
    selection.value = { kind: 'serials', serials, serial_col: opts.serialCol?.() }
    if (opts.immediate) {
      // rect 立即消费（Task 4）：高亮接管，浮层只在拖拽期间闪一次，mouseup 即清，
      // 不等右键菜单。等价于 createAndClose，但触发点在 mouseup（选区一次性消费）。
      opts.onCreate(selection.value)
      clearSelection()
      return
    }
    drawOverlays()
  }

  function onRendered() { if (selection.value) drawOverlays() }

  function onContextMenu(ev: MouseEvent) {
    // 无选区但 canMenu() 为真也开门（高亮激活时右键「清除高亮」）；两者皆无才不开。
    if (!opts.enabled() || !(selection.value || opts.canMenu?.())) return
    ev.preventDefault()
    menu.value = { visible: true, x: ev.clientX, y: ev.clientY }
  }

  function bind(chart: echarts.ECharts) {
    const el = opts.container.value
    if (el) {
      el.style.position = 'relative'
      el.addEventListener('contextmenu', onContextMenu)
      el.addEventListener('mousedown', onNativeMouseDown, true)
    }
    chart.getZr().on('mousedown', onZrMouseDown)
    chart.on('rendered', onRendered)
    bound = chart
  }

  function unbind() {
    if (bound) {
      if (!bound.isDisposed()) {
        bound.getZr().off('mousedown', onZrMouseDown)
        bound.off('rendered', onRendered)
      }
      bound = null
    }
    opts.container.value?.removeEventListener('contextmenu', onContextMenu)
    opts.container.value?.removeEventListener('mousedown', onNativeMouseDown, true)
    window.removeEventListener('mousemove', onWinMove)
    window.removeEventListener('mouseup', onWinUp)
    drag = null
    clearOverlays()
  }

  function clearSelection() {
    selection.value = null
    rectLanes = []
    clearOverlays()
    menu.value.visible = false
  }
  function closeMenu() { menu.value.visible = false }
  function createAndClose() {
    if (selection.value) opts.onCreate(selection.value)
    // 选区在创建时刻被消费（只展示一次）：clearSelection 已含关菜单 + 清浮层 + 清 rectLanes。
    clearSelection()
  }

  watch(opts.chartInstance, (chart) => {
    unbind()
    clearSelection()
    if (chart) bind(chart)
  }, { immediate: true })

  onBeforeUnmount(() => { unbind(); clearSelection() })

  return { menu, selection, clearSelection, closeMenu, createAndClose }
}
