/**
 * 框选选区的纯几何/payload 函数（T2 承载，无 DOM 无网络）。
 * 图表 glue（convertFromPixel/grid 矩形/zrender 事件）在 useChartBrushSelect.ts。
 */

export interface PxRect { x0: number; y0: number; x1: number; y1: number }
/** x = 轴下标（category 映射后）；y = 绘制值（含 jitter/锚定，D5 WYSIWYG） */
export interface DataPoint { x: number; y: number; serial: number | string }

export type ChartSelection =
  | { kind: 'value_range'; lo: number | null; hi: number | null }
  | { kind: 'serials'; serials: (number | string)[]; serial_col?: string }

export function normalizeRect(a: { x: number; y: number }, b: { x: number; y: number }): PxRect {
  return {
    x0: Math.min(a.x, b.x), y0: Math.min(a.y, b.y),
    x1: Math.max(a.x, b.x), y1: Math.max(a.y, b.y),
  }
}

export function intersectRects(a: PxRect, b: PxRect): PxRect | null {
  const x0 = Math.max(a.x0, b.x0)
  const y0 = Math.max(a.y0, b.y0)
  const x1 = Math.min(a.x1, b.x1)
  const y1 = Math.min(a.y1, b.y1)
  return x1 > x0 && y1 > y0 ? { x0, y0, x1, y1 } : null
}

export function normalizeRange(a: number, b: number): [number, number] {
  return a <= b ? [a, b] : [b, a]
}

export function pickSerials(
  points: DataPoint[], xRange: [number, number], yRange: [number, number],
): (number | string)[] {
  const out: (number | string)[] = []
  for (const p of points) {
    if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) continue
    if (p.x >= xRange[0] && p.x <= xRange[1] && p.y >= yRange[0] && p.y <= yRange[1]) {
      out.push(p.serial)
    }
  }
  return out
}

export function mergeSerials(groups: (number | string)[][]): (number | string)[] {
  const seen = new Set<number | string>()
  const out: (number | string)[] = []
  for (const g of groups) {
    for (const s of g) {
      if (!seen.has(s)) { seen.add(s); out.push(s) }
    }
  }
  return out
}

/** D6：框选触达 underflow/overflow 兜底柱中心 → 该侧无界（null）。 */
export function valueRangeWithOverflow(
  lo: number, hi: number, binCenters: number[],
): { lo: number | null; hi: number | null } {
  let L: number | null = lo
  let H: number | null = hi
  if (binCenters.length >= 2) {
    if (lo <= binCenters[0]) L = null
    if (hi >= binCenters[binCenters.length - 1]) H = null
  }
  return { lo: L, hi: H }
}

/** 仅用于标题展示：6 位有效数字，消除 convertFromPixel 浮点噪声（不改请求体数值）。 */
function fmtBound(v: number): string {
  return String(Number(v.toPrecision(6)))
}

export function subsetPanelTitle(param: string, sel: ChartSelection, n: number | null): string {
  const base = n != null ? `${param} 子集 · n=${n}` : `${param} 子集`
  if (sel.kind === 'value_range') {
    const lo = sel.lo != null ? fmtBound(sel.lo) : '-∞'
    const hi = sel.hi != null ? fmtBound(sel.hi) : '+∞'
    return `${base} · [${lo}, ${hi}]`
  }
  return `${base} · ${sel.serials.length} 颗序列`
}

export interface SubsetRequestCtx {
  fileId: number
  ignoreNoLimit: boolean
  ignoreNoTestValue: boolean
  dataOnlyBin1: boolean
  onlyFailTestItem: boolean
  onlyLowCpk: boolean
  iqrMultiplier: number
  chartConfig: string[]
}

/** 子集请求体：强制 DR 分箱（D1）、custom 限置空、KDE 跟随图表配置（与 useHistogram 同口径）。 */
export function buildSubsetRequest(ctx: SubsetRequestCtx, param: string, selection: ChartSelection) {
  const showKde = ctx.chartConfig.includes('kde')
  return {
    file_id: ctx.fileId,
    params: [param],
    ignore_no_limit: ctx.ignoreNoLimit,
    range_type: 'DR' as const,
    custom_low: null,
    custom_high: null,
    iqr_multiplier: ctx.iqrMultiplier,
    ignore_no_test_value: ctx.ignoreNoTestValue,
    data_only_bin1: ctx.dataOnlyBin1,
    only_fail_test_item: ctx.onlyFailTestItem,
    only_low_cpk: ctx.onlyLowCpk,
    include_kde: showKde,
    kde_variant: showKde ? (ctx.chartConfig.includes('kde_full') ? 'all' : 'filtered') : null,
    selection,
  }
}