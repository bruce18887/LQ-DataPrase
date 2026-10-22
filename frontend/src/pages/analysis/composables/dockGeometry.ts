/**
 * 分析页 dock 的行高几何（纯函数，零依赖）
 * ────────────────────────────────────────────────
 * 模型：行上下堆叠，行内图左右并排。每行有一个**像素目标高度**，容器高度由目标
 *   之和反推，占比只是像素目标在容器里的表达（`rowPcts` 仍是被持久化、被行间隔条
 *   改写的量）。
 * 为什么要改成像素目标：旧实现是「容器 = max(640, min(行数×460, 1400))，行 = 占比 ×
 *   容器」，占比模板 [58, 42/(n−1)] 让辅助行随图数增多被 42% 持续摊薄（3 行 286px、
 *   4 行 192px —— 已经低于自家 200px 拖拽下限），且用户拖过一次底部横条后
 *   `bodyH` 固定，再加图只是重新切分同一坨像素。改成像素目标后「新增一行 = 已有
 *   辅助行一样高」是构造保证，不再依赖占比模板。
 * 兜底：`floorBodyH` 反解「最低行恰好 = MIN_ROW_H」所需的容器高度，只在渲染期取
 *   max，**不回写 bodyH** —— 用户拖出的整体高度不能被兜底悄悄改掉。
 * 纯算术，不碰 DOM、不碰存储；持久化与指针拖拽各在 useChartDock.ts / ChartDock.vue。
 */

export type DockRow = 'hist' | 'serial' | 'qq' | 'box'

/** 直方图行目标高度：沿用旧默认布局下它的实测渲染高（1380×58% − 11.6 ≈ 789）取整 */
export const HIST_ROW_PX = 780
/** 辅助行（序列分布 / QQ / 箱线）目标高度：旧 autoH 每行 460 的既有意图 */
export const AUX_ROW_PX = 460
/** 单行最低高度：旧实现只写在行间隔条拖拽路径里，默认布局能绕过它 */
export const MIN_ROW_H = 200
/** 行间隔条占位。改它必须同步改 ChartDock.vue 里 `.chart-dock__rowbar` 的 height */
export const ROWBAR_H = 10
/** 单行独占整个 dock 时的下限（旧 max(640, …) 的那 640） */
const MIN_BODY_H = 640
/** 容器高度上限，与 useChartDock 的 DOCK_BODY_MAX_H 同值：兜底不得把页面吹长 */
export const MAX_BODY_H = 2600

/** 行间隔条总占位：n 行之间有 n−1 条 */
export function rowBars(rowCount: number): number {
  return Math.max(0, rowCount - 1) * ROWBAR_H
}

/** 占比 → 渲染像素。行 CSS 是 calc(pct% − bars×pct/100)，等价于 pct/100 × (body − bars) */
export function rowHeightPx(pct: number, bodyH: number, bars: number): number {
  return (pct / 100) * (bodyH - bars)
}

/** 每行的目标高度：含 hist 的行更高；单行独占时至少占满整屏下限 */
export function rowTargetsPx(rows: DockRow[][]): number[] {
  const t: number[] = rows.map((r) => (r.includes('hist') ? HIST_ROW_PX : AUX_ROW_PX))
  if (t.length === 1) t[0] = Math.max(t[0], MIN_BODY_H)
  return t
}

/** 像素 → 占比（和为 100）；全零/空入参返回空数组 */
function sharesFromPx(px: number[]): number[] {
  const sum = px.reduce((a, b) => a + b, 0)
  if (!(sum > 0)) return []
  return px.map((v) => (v / sum) * 100)
}

/** 按行数自动定出的容器高度（正好装下每行目标 + 行间隔条） */
export function autoBodyH(rows: DockRow[][]): number {
  return rowTargetsPx(rows).reduce((a, b) => a + b, 0) + rowBars(rows.length)
}

/** 默认占比：由像素目标反推，所以 hist 的高份额跟着 hist 所在的行，不写死第 0 行 */
export function defaultRowPcts(rows: DockRow[][]): number[] {
  return sharesFromPx(rowTargetsPx(rows))
}

/**
 * 「最低行恰好 = MIN_ROW_H」所需的容器高度（rowHeightPx 的反解）。
 * 单行没有「最低行」问题；占比数组残缺/非正一律返回 0 = 不兜底，
 * 免得一处坏持久化数据把容器顶到上限。
 */
export function floorBodyH(rowPcts: number[], bars: number): number {
  if (rowPcts.length < 2) return 0
  if (rowPcts.some((p) => !Number.isFinite(p) || p <= 0)) return 0
  const minPct = Math.min(...rowPcts)
  return (MIN_ROW_H * 100) / minPct + bars
}

/** 渲染期容器高度：bodyH 覆盖自动值，但两条下限与一条上限仍然生效 */
export function effBodyH(bodyH: number | null, rows: DockRow[][], rowPcts: number[]): number {
  const floor = Math.min(floorBodyH(rowPcts, rowBars(rows.length)), MAX_BODY_H)
  return Math.max(bodyH ?? autoBodyH(rows), floor)
}

/**
 * 勾选集变化 → 新 rows + 每行的来源索引（−1 = 新增行）。
 * 存活行保持原有相对顺序与成员顺序；新增行按每行 2 张分块追加在底部。
 * `srcIdx` 指向**旧 rows 的下标**而不是新的渲染序位——中间某行被清空会让后面的行
 * 序位前移，用序位去取旧占比就会张冠李戴（拿错行高）。
 * `active` 里重复的 key 只算一张，摊平后的 rows 与 active 集合恒等。
 */
export function reconcileRows(
  prevRows: DockRow[][],
  active: DockRow[],
): { rows: DockRow[][]; srcIdx: number[] } {
  const activeSet = new Set(active)
  const rows: DockRow[][] = []
  const srcIdx: number[] = []
  prevRows.forEach((r, i) => {
    const kept = r.filter((k) => activeSet.has(k))
    if (kept.length > 0) {
      rows.push(kept)
      srcIdx.push(i)
    }
  })
  const placed = new Set<DockRow>(rows.flat())
  const missing: DockRow[] = []
  for (const k of active) {
    if (placed.has(k)) continue
    placed.add(k)
    missing.push(k)
  }
  for (let i = 0; i < missing.length; i += 2) {
    rows.push(missing.slice(i, i + 2))
    srcIdx.push(-1)
  }
  if (rows.length === 0) {
    rows.push([])
    srcIdx.push(-1)
  }
  return { rows, srcIdx }
}

/** 这组占比是否就是 rows 对应的默认占比（容差 0.5%）——「用户没手调过」的判据 */
export function isDefaultPcts(pcts: number[], rows: DockRow[][]): boolean {
  const def = defaultRowPcts(rows)
  if (pcts.length !== def.length) return false
  return def.every((d, i) => Number.isFinite(pcts[i]) && Math.abs(pcts[i] - d) < 0.5)
}

function normalizeTo100(pcts: number[]): number[] {
  return sharesFromPx(pcts)
}

/**
 * 增删勾选后重算占比（规则 2）。
 * `srcIdx[i]` = 新第 i 行来自旧第几行，−1 表示新增行。
 * - 旧布局是默认占比（用户没手调过）→ 直接跟随新的像素目标，新行正好拿到
 *   `AUX_ROW_PX`，已有行一格不掉；
 * - 用户手调过 → 保留存活行之间的比值，新增行取「最后一个存活行」的占比
 *   （= 需求里的「和上一个已存在的图表一样高」），再整体归一。
 * 需要的旧占比取不到（长度不符 / NaN / 非正）时退回像素目标，不产出 NaN。
 */
export function reconcileRowPcts(
  prevRows: DockRow[][],
  prevPcts: number[],
  nextRows: DockRow[][],
  srcIdx: number[],
): number[] {
  if (nextRows.length === 0) return []
  if (isDefaultPcts(prevPcts, prevRows)) return defaultRowPcts(nextRows)

  const surviving = srcIdx.filter((i) => i >= 0).map((i) => prevPcts[i])
  if (surviving.length === 0 || surviving.some((v) => !Number.isFinite(v) || v <= 0)) {
    return defaultRowPcts(nextRows)
  }
  const lastSrc = [...srcIdx].reverse().find((i) => i >= 0)
  const refPct = lastSrc === undefined ? 100 : prevPcts[lastSrc]
  return normalizeTo100(srcIdx.map((i) => (i >= 0 ? prevPcts[i] : refPct)))
}
