/**
 * 图表区可停靠拼格布局模型（单文件分析 Tab 右侧）
 * ────────────────────────────────────────────────
 * 交互模型：rows: ChartKey[][] —— 行上下堆叠，行内元素左右并排。
 *   1 图 [[hist]] 铺满；2 图上下 [[a],[b]]；2 图左右 [[a,b]]；
 *   4 图 2×2 [[a,b],[c,d]]；任意组合由此表达。
 * 尺寸：rowPcts / colPcts 为百分比（0-100，同层相加≈100），仅在结构变化时重置为
 *   均分、在 splitter resize-end 时按最终像素折算回写并持久化。
 * 持久化：safeStorage（Electron 下防 DOMException），键 lqdp-analysis-chart-layout。
 * 单例：module 级 ref（仿 useZoom.ts 的 refCount 模式），避免面板 v-if/重排丢态。
 * 纯模型 + 变换 + 存储，不碰 DOM —— 拖拽指针逻辑在 ChartDock.vue。
 */
import { ref, type Ref } from 'vue'
import { safeGetItem, safeSetItem, safeRemoveItem } from '../../../utils/safeStorage'

export type ChartKey = 'hist' | 'serial' | 'qq' | 'box'
const ALL_KEYS: ChartKey[] = ['hist', 'serial', 'qq', 'box']
export const DOCK_LAYOUT_STORAGE_KEY = 'lqdp-analysis-chart-layout'
const VERSION = 1

/** hist 首行占比、辅助行均分剩余（首屏默认，直方图明显更高） */
const HIST_FIRST_PCT = 58

export interface DockLayout {
  rows: ChartKey[][]
  rowPcts: number[]
  colPcts: number[][]
}

function equalPct(n: number): number[] {
  if (n <= 0) return []
  const base = 100 / n
  return Array.from({ length: n }, () => base)
}

function chunk<T>(arr: T[], size: number): T[][] {
  const out: T[][] = []
  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size))
  return out
}

/** 由当前可见 key 生成默认布局：hist 独立首行，其余按每行 2 张分块 */
export function defaultLayout(active: ChartKey[]): DockLayout {
  const rows: ChartKey[][] = []
  if (active.includes('hist')) rows.push(['hist'])
  const aux = active.filter((k) => k !== 'hist')
  rows.push(...chunk(aux, 2))
  if (rows.length === 0) rows.push([])
  return {
    rows,
    rowPcts: rows.length === 1 ? [100] : defaultRowPcts(rows.length),
    colPcts: rows.map((r) => equalPct(r.length)),
  }
}

function defaultRowPcts(n: number): number[] {
  // 首行 hist 更高，其余均分剩余
  if (n === 1) return [100]
  const rest = 100 - HIST_FIRST_PCT
  const out = [HIST_FIRST_PCT]
  for (let i = 1; i < n; i++) out.push(rest / (n - 1))
  return out
}

export function isValidLayout(parsed: unknown): parsed is DockLayout {
  if (!parsed || typeof parsed !== 'object') return false
  const p = parsed as Record<string, unknown>
  if (p.v !== VERSION) return false
  if (!Array.isArray(p.rows)) return false
  const seen = new Set<ChartKey>()
  for (const row of p.rows as unknown[]) {
    if (!Array.isArray(row)) return false
    for (const k of row as unknown[]) {
      if (typeof k !== 'string' || !ALL_KEYS.includes(k as ChartKey) || seen.has(k as ChartKey)) return false
      seen.add(k as ChartKey)
    }
  }
  return true
}

function loadLayout(): DockLayout | null {
  const raw = safeGetItem(DOCK_LAYOUT_STORAGE_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    if (!isValidLayout(parsed)) return null
    const l = parsed as unknown as DockLayout & { v: number }
    return { rows: l.rows, rowPcts: l.rowPcts ?? [], colPcts: l.colPcts ?? [] }
  } catch {
    return null
  }
}

function saveLayout(l: DockLayout) {
  safeSetItem(DOCK_LAYOUT_STORAGE_KEY, JSON.stringify({ v: VERSION, ...l }))
}

export interface ChartDockApi {
  rows: Ref<ChartKey[][]>
  rowPcts: Ref<number[]>
  colPcts: Ref<number[][]>
  /** 让 rows 覆盖到 active 集合：补新、去旧，保留既有相对顺序 */
  reconcile: (active: ChartKey[]) => void
  moveTo: (from: ChartKey, to: ChartKey, dir: 'left' | 'right' | 'above' | 'below' | 'swap') => void
  reset: (active: ChartKey[]) => void
  /** 行内列 resize-end 折回百分比 */
  setRowPcts: (pcts: number[]) => void
  setColPcts: (rowIndex: number, pcts: number[]) => void
  findPos: (key: ChartKey) => { ri: number; ci: number } | null
}

let singleton: ChartDockApi | null = null
let refCount = 0

/**
 * @param getActive 返回当前可见 key（由 SingleParamTab 依 toggles 计算）
 */
export function useChartDock(getActive: () => ChartKey[]): ChartDockApi {
  if (!singleton) {
    const stored = loadLayout()
    const init = stored ?? defaultLayout(getActive())
    const rows = ref<ChartKey[][]>(init.rows.map((r) => [...r]))
    const rowPcts = ref<number[]>([...init.rowPcts])
    const colPcts = ref<number[][]>(init.colPcts.map((c) => [...c]))

    const normalizeSizes = () => {
      if (rowPcts.value.length !== rows.value.length || rowPcts.value.some((n) => !Number.isFinite(n))) {
        rowPcts.value = defaultRowPcts(rows.value.length)
      } else if (rows.value.length > 0) {
        // 删行路径（moveTo 删空源行 / 旧版本持久化残留）只把该项占比从数组移除、
        // 长度不变，剩余占比之和会 ≠100 → 末行下方留出等量空白（底部横条贴不到
        // 图表）。按比例归一补齐，保留用户已调好的行间比例。
        const sum = rowPcts.value.reduce((a, b) => a + b, 0)
        if (Number.isFinite(sum) && sum > 0 && Math.abs(sum - 100) > 0.5) {
          rowPcts.value = rowPcts.value.map((p) => (p / sum) * 100)
        }
      }
      colPcts.value = rows.value.map((r, i) => {
        const prev = colPcts.value[i]
        return prev && prev.length === r.length ? prev : equalPct(r.length)
      })
    }

    const persist = () => saveLayout({ rows: rows.value, rowPcts: rowPcts.value, colPcts: colPcts.value })

    const findPos = (key: ChartKey) => {
      for (let ri = 0; ri < rows.value.length; ri++) {
        const ci = rows.value[ri].indexOf(key)
        if (ci >= 0) return { ri, ci }
      }
      return null
    }

    const reconcile = (active: ChartKey[]) => {
      const activeSet = new Set(active)
      // 去掉不再可见的
      let next = rows.value.map((r) => r.filter((k) => activeSet.has(k))).filter((r) => r.length)
      // 补新勾选的：追加到底部（与已存在的同新 key 一起每行 2 张分块）
      const placed = new Set(next.flat())
      const missing = active.filter((k) => !placed.has(k))
      if (missing.length) next = [...next, ...chunk(missing, 2)]
      // 空态兜底
      if (next.length === 0) next = [[]]
      rows.value = next
      // 结构变了 → 重算尺寸长度（尽量保留）
      normalizeSizes()
      persist()
    }

    const moveTo: ChartDockApi['moveTo'] = (from, to, dir) => {
      if (from === to) return
      const f = findPos(from)
      const t = findPos(to)
      if (!f || !t) return
      const rowsCopy = rows.value.map((r) => [...r])
      if (dir === 'swap') {
        ;[rowsCopy[f.ri][f.ci], rowsCopy[t.ri][t.ci]] = [rowsCopy[t.ri][t.ci], rowsCopy[f.ri][f.ci]]
        rows.value = rowsCopy
        normalizeSizes()
        persist()
        return
      }
      // 先从源位移除
      rowsCopy[f.ri].splice(f.ci, 1)
      // 源行空则删行（同时删对应尺寸，交给 normalizeSizes 重建）
      if (rowsCopy[f.ri].length === 0) {
        rowsCopy.splice(f.ri, 1)
        rowPcts.value = rowPcts.value.filter((_, i) => i !== f.ri)
        colPcts.value = colPcts.value.filter((_, i) => i !== f.ri)
      }
      // 重新定位目标（索引可能因删除而变）
      let ti = -1
      let tj = -1
      for (let ri = 0; ri < rowsCopy.length; ri++) {
        const ci = rowsCopy[ri].indexOf(to)
        if (ci >= 0) { ti = ri; tj = ci; break }
      }
      if (ti < 0) { rowsCopy.push([from]); rows.value = rowsCopy; normalizeSizes(); persist(); return }
      if (dir === 'left') rowsCopy[ti].splice(tj, 0, from)
      else if (dir === 'right') rowsCopy[ti].splice(tj + 1, 0, from)
      else if (dir === 'above') rowsCopy.splice(ti, 0, [from])
      else rowsCopy.splice(ti + 1, 0, [from]) // below
      rows.value = rowsCopy
      normalizeSizes()
      persist()
    }

    const reset = (active: ChartKey[]) => {
      safeRemoveItem(DOCK_LAYOUT_STORAGE_KEY)
      const d = defaultLayout(active)
      rows.value = d.rows
      rowPcts.value = d.rowPcts
      colPcts.value = d.colPcts
      persist()
    }

    const setRowPcts = (pcts: number[]) => { rowPcts.value = pcts; persist() }
    const setColPcts = (rowIndex: number, pcts: number[]) => {
      const c = [...colPcts.value]
      c[rowIndex] = pcts
      colPcts.value = c
      persist()
    }

    singleton = { rows, rowPcts, colPcts, reconcile, moveTo, reset, setRowPcts, setColPcts, findPos }
  }
  refCount++
  const api = singleton
  return api
}

/** 供组件卸载时调用（当前单例常驻，保留布局；预留钩子） */
export function releaseChartDock() {
  refCount = Math.max(0, refCount - 1)
}

/** resize-end 的像素数组折回百分比（0-100，相加≈100），用于持久化与 :size 回填 */
export function pctFromPx(pxSizes: number[]): number[] {
  const total = pxSizes.reduce((a, b) => a + (Number.isFinite(b) ? b : 0), 0)
  if (total <= 0) return equalPct(pxSizes.length)
  return pxSizes.map((s) => ((Number.isFinite(s) ? s : 0) / total) * 100)
}
