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
    clearOverlays()
    selection.value = null
    rectLanes = []
    drag = { start: { x: e.offsetX, y: e.offsetY }, cur: { x: e.offsetX, y: e.offsetY } }
    window.addEventListener('mousemove', onWinMove)
    window.addEventListener('mouseup', onWinUp)
  }

  function onWinMove(ev: MouseEvent) {
    if (!drag) return
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
    drawOverlays()
  }

  function onRendered() { if (selection.value) drawOverlays() }

  function onContextMenu(ev: MouseEvent) {
    if (!opts.enabled() || !selection.value) return
    ev.preventDefault()
    menu.value = { visible: true, x: ev.clientX, y: ev.clientY }
  }

  function bind(chart: echarts.ECharts) {
    const el = opts.container.value
    if (el) {
      el.style.position = 'relative'
      el.addEventListener('contextmenu', onContextMenu)
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
    menu.value.visible = false
  }

  watch(opts.chartInstance, (chart) => {
    unbind()
    clearSelection()
    if (chart) bind(chart)
  }, { immediate: true })

  onBeforeUnmount(() => { unbind(); clearSelection() })

  return { menu, selection, clearSelection, closeMenu, createAndClose }
}
