/**
 * 图表区可停靠拼格布局模型（单文件分析 Tab 右侧）
 * ────────────────────────────────────────────────
 * 交互模型：rows: ChartKey[][] —— 行上下堆叠，行内元素左右并排。
 *   1 图 [[hist]] 铺满；2 图上下 [[a],[b]]；2 图左右 [[a,b]]；
 *   4 图 2×2 [[a,b],[c,d]]；任意组合由此表达。
 * 尺寸：rowPcts / colPcts 为百分比（0-100，同层相加≈100），在 splitter resize-end 时
 *   按最终像素折算回写并持久化。**默认值由 dockGeometry.ts 的行高像素目标反推**，
 *   增删勾选时按「未手调→跟随目标 / 手调过→保留比值」重算，不再整表抹回模板。
 *   bodyH 为底部横条拖出的整体高度覆盖（px，null=按行数自动），同链路持久化；
 *   渲染期还会被 dockGeometry 的每行最低高度兜底抬高（只作用于渲染，不回写 bodyH）。
 * 持久化：safeStorage（Electron 下防 DOMException），键 lqdp-analysis-chart-layout。
 * 单例：module 级 ref（仿 useZoom.ts 的 refCount 模式），避免面板 v-if/重排丢态。
 * 纯模型 + 变换 + 存储，不碰 DOM —— 拖拽指针逻辑在 ChartDock.vue。
 */
import { nextTick, ref, type Ref } from 'vue'
import { safeGetItem, safeSetItem, safeRemoveItem } from '../../../utils/safeStorage'
import { loadChartMemory, saveChartState, isMemoryEnabled } from '../../../composables/useChartMemory'
import { MAX_BODY_H, defaultRowPcts, reconcileRowPcts, reconcileRows } from './dockGeometry'

export type ChartKey = 'hist' | 'serial' | 'qq' | 'box' | 'site3d'
const ALL_KEYS: ChartKey[] = ['hist', 'serial', 'qq', 'box', 'site3d']
/** 会话级子集面板作为 dock「guest」：与主图同排拖拽，但绝不进持久化（R5/D4）。 */
export type GuestKey = `subset:${number}`
export type DockKey = ChartKey | GuestKey
export const isGuestKey = (k: string): k is GuestKey => k.startsWith('subset:')
export const guestKeyOf = (id: number): GuestKey => `subset:${id}`
export const guestIdOf = (k: GuestKey): number => Number(k.slice('subset:'.length))
export const DOCK_LAYOUT_STORAGE_KEY = 'lqdp-analysis-chart-layout'
// 存档版本：加一个 ChartKey 是**向后兼容**的变换（isValidLayout 只要求 key ∈ ALL_KEYS），
// 所以不升档。升档会让 `p.v !== VERSION` 命中，把每个用户存过的布局（本机 localStorage
// 与账号记忆两条路）整表丢弃——2026-11-04 的 spec 初稿把这条因果写反了，已勘误。
const VERSION = 1

/** 底部横条拖拽的整体高度上下限（px）——持久化回填时同限夹取 */
export const DOCK_BODY_MIN_H = 480
export const DOCK_BODY_MAX_H = MAX_BODY_H

export interface DockLayout {
  rows: ChartKey[][]
  rowPcts: number[]
  colPcts: number[][]
  /** 底部横条拖出的整体高度覆盖（px）；null = 按行数自动 */
  bodyH: number | null
}

/** 持久化 bodyH 容错：缺失/非法/超限 → null（不牵连整个布局作废） */
export function sanitizeBodyH(v: unknown): number | null {
  if (v === null || v === undefined) return null
  if (typeof v !== 'number' || !Number.isFinite(v)) return null
  return Math.round(Math.max(DOCK_BODY_MIN_H, Math.min(DOCK_BODY_MAX_H, v)))
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
  rows.push(...chunk(active.filter((k) => k !== 'hist'), 2))
  if (rows.length === 0) rows.push([])
  return {
    rows,
    // 占比由 dockGeometry 的像素目标反推：hist 所在行更高，无 hist 时自然均分。
    //（旧实现把 58% 写死在第 0 行，hist 被拖到非首行时它会白占一格）
    rowPcts: defaultRowPcts(rows),
    colPcts: rows.map((r) => equalPct(r.length)),
    bodyH: null,
  }
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

/**
 * 读本机 localStorage 里的布局存档（导出供 test/unit/chartLayout.spec.ts 做「旧 v:1
 * 四图存档回读后字段逐字不丢」的真回读；`isValidLayout` 只回答合法与否，答不了保留性）。
 */
export function loadLayout(): DockLayout | null {
  const raw = safeGetItem(DOCK_LAYOUT_STORAGE_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    if (!isValidLayout(parsed)) return null
    const l = parsed as unknown as DockLayout & { v: number }
    return {
      rows: l.rows,
      rowPcts: l.rowPcts ?? [],
      colPcts: l.colPcts ?? [],
      bodyH: sanitizeBodyH(l.bodyH),
    }
  } catch {
    return null
  }
}

/**
 * 持久化前的 guest 剥离（纯函数，T2 承载）：子集面板是会话级，绝不进 localStorage/账号。
 * 无 guest 时**原样返回**（不重排、不归一），保证既有存档逐字不变（chart-memory 契约）。
 * 有 guest 时：剔除 guest 列/空行，保留主图相对顺序，占比按存活项归一。
 */
export function guestFreeSnapshot(
  rows: DockKey[][], rowPcts: number[], colPcts: number[][], bodyH: number | null,
): DockLayout {
  if (!rows.some((r) => r.some(isGuestKey))) {
    return { rows: rows as ChartKey[][], rowPcts, colPcts, bodyH }
  }
  const outRows: ChartKey[][] = []
  const outRowPcts: number[] = []
  const outColPcts: number[][] = []
  rows.forEach((r, i) => {
    const keptIdx: number[] = []
    const kept: ChartKey[] = []
    r.forEach((k, ci) => { if (!isGuestKey(k)) { kept.push(k); keptIdx.push(ci) } })
    if (kept.length === 0) return
    outRows.push(kept)
    outRowPcts.push(Number.isFinite(rowPcts[i]) ? rowPcts[i] : 0)
    const prevCol = colPcts[i] ?? []
    const keptCol = keptIdx.map((ci) => (Number.isFinite(prevCol[ci]) ? prevCol[ci] : 0))
    const colSum = keptCol.reduce((a, b) => a + b, 0)
    outColPcts.push(colSum > 0 ? keptCol.map((v) => (v / colSum) * 100) : kept.map(() => 100 / kept.length))
  })
  const rowSum = outRowPcts.reduce((a, b) => a + b, 0)
  return {
    rows: outRows,
    rowPcts: rowSum > 0 ? outRowPcts.map((v) => (v / rowSum) * 100) : outRows.map(() => 100 / outRows.length),
    colPcts: outColPcts,
    bodyH,
  }
}

export interface ChartDockApi {
  rows: Ref<DockKey[][]>
  rowPcts: Ref<number[]>
  colPcts: Ref<number[][]>
  /** 整体高度覆盖（px，null=自动）；拖拽中直接写、松手调 setBodyH 落盘 */
  bodyH: Ref<number | null>
  /**
   * 让 rows 覆盖到 active 集合：补新、去旧，保留既有相对顺序。
   * 会话级 guest（子集面板）不在 active 里但会被保留，不被勾选 reconcile 裁掉。
   * { persist: false } 只改内存不落盘——挂载首次对齐（勾选可能尚未从账号
   * 记忆恢复，此时落盘会把已存布局裁剪降级）与恢复后的权威对齐区分开。
   */
  reconcile: (active: ChartKey[], opts?: { persist?: boolean }) => void
  moveTo: (from: DockKey, to: DockKey, dir: 'left' | 'right' | 'above' | 'below' | 'swap') => void
  reset: (active: ChartKey[]) => void
  /** 行内列 resize-end 折回百分比 */
  setRowPcts: (pcts: number[]) => void
  setColPcts: (rowIndex: number, pcts: number[]) => void
  /** 底部横条松手/双击复原时落盘整体高度 */
  setBodyH: (h: number | null) => void
  findPos: (key: DockKey) => { ri: number; ci: number } | null
  /** 子集面板进 dock：追加一行 [guest]，只改内存不落盘（guest 会话级） */
  addGuest: (key: GuestKey) => void
  /** 子集面板离 dock：移除 guest，只改内存不落盘 */
  removeGuest: (key: GuestKey) => void
}

let singleton: ChartDockApi | null = null
let refCount = 0

// 账号记忆的会话态：登出/登入由 resetChartDockMemoryState() 复位（stores/auth.ts
// 调用）。否则一次性接线 + 粘性脏标记会让 SPA 换账号后：新账号布局永不套用、
// 旧账号基底的布局被写进新账号。
let userTouched = false
let memoryWired = false
let wireMemory: (() => void) | null = null

/**
 * @param getActive 返回当前可见 key（由 SingleParamTab 依 toggles 计算）
 */
export function useChartDock(getActive: () => ChartKey[]): ChartDockApi {
  if (!singleton) {
    const stored = loadLayout()
    const init = stored ?? defaultLayout(getActive())
    const rows = ref<DockKey[][]>(init.rows.map((r) => [...r]))
    const rowPcts = ref<number[]>([...init.rowPcts])
    const colPcts = ref<number[][]>(init.colPcts.map((c) => [...c]))
    const bodyH = ref<number | null>(init.bodyH ?? null)

    const normalizeSizes = () => {
      if (rowPcts.value.length !== rows.value.length || rowPcts.value.some((n) => !Number.isFinite(n))) {
        rowPcts.value = defaultRowPcts(rows.value)
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

    const persist = () => {
      // guest（子集面板）会话级，剥离后再落盘；无 guest 时逐字不变（存档契约）
      const free = guestFreeSnapshot(rows.value, rowPcts.value, colPcts.value, bodyH.value)
      const payload = {
        v: VERSION,
        rows: free.rows,
        rowPcts: free.rowPcts,
        colPcts: free.colPcts,
        bodyH: free.bodyH,
      }
      if (isMemoryEnabled() !== false) safeSetItem(DOCK_LAYOUT_STORAGE_KEY, JSON.stringify(payload))
      saveChartState({ layout: payload })
    }

    const findPos = (key: DockKey) => {
      for (let ri = 0; ri < rows.value.length; ri++) {
        const ci = rows.value[ri].indexOf(key)
        if (ci >= 0) return { ri, ci }
      }
      return null
    }

    const reconcile: ChartDockApi['reconcile'] = (active, opts) => {
      const prevRows = rows.value.map((r) => [...r])
      const prevPcts = [...rowPcts.value]
      // guest 不在勾选 active 里，但必须随 reconcile 保留（否则一切换勾选子集就消失）
      const guests = prevRows.flat().filter(isGuestKey)
      const { rows: next, srcIdx } = reconcileRows(prevRows, [...active, ...guests])
      rows.value = next
      // 增删勾选不得把 rowPcts 整表抹回模板：未手调时跟随像素目标（新行正好拿到
      // 辅助行目标高度、已有行一格不掉），手调过则保留存活行之间的比值。
      rowPcts.value = reconcileRowPcts(prevRows, prevPcts, next, srcIdx)
      normalizeSizes()
      if (opts?.persist !== false) persist()
    }

    const addGuest: ChartDockApi['addGuest'] = (key) => {
      if (findPos(key)) return
      const prevRows = rows.value.map((r) => [...r])
      const prevPcts = [...rowPcts.value]
      const next = [...prevRows, [key]]
      rows.value = next
      rowPcts.value = reconcileRowPcts(prevRows, prevPcts, next, [...prevRows.map((_, i) => i), -1])
      normalizeSizes()
      // 只改内存：guest 会话级，主图存档不被 guest 的加入改写
    }

    const removeGuest: ChartDockApi['removeGuest'] = (key) => {
      const pos = findPos(key)
      if (!pos) return
      const next = rows.value.map((r) => [...r])
      next[pos.ri].splice(pos.ci, 1)
      if (next[pos.ri].length === 0) {
        next.splice(pos.ri, 1)
        rowPcts.value = rowPcts.value.filter((_, i) => i !== pos.ri)
        colPcts.value = colPcts.value.filter((_, i) => i !== pos.ri)
      }
      rows.value = next
      normalizeSizes()
      // 只改内存：同 addGuest
    }

    const moveTo: ChartDockApi['moveTo'] = (from, to, dir) => {
      userTouched = true
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
      userTouched = true
      safeRemoveItem(DOCK_LAYOUT_STORAGE_KEY)
      const guests = rows.value.flat().filter(isGuestKey)
      const d = defaultLayout(active)
      // 重置只复位主图；会话级子集面板保留，追加在默认布局之后
      const nextRows: DockKey[][] = [...d.rows, ...guests.map((g) => [g])]
      rows.value = nextRows
      rowPcts.value = defaultRowPcts(nextRows)
      colPcts.value = nextRows.map((r) => equalPct(r.length))
      bodyH.value = null
      persist()
    }

    const setRowPcts = (pcts: number[]) => { userTouched = true; rowPcts.value = pcts; persist() }
    const setColPcts = (rowIndex: number, pcts: number[]) => {
      userTouched = true
      const c = [...colPcts.value]
      c[rowIndex] = pcts
      colPcts.value = c
      persist()
    }
    const setBodyH = (h: number | null) => {
      userTouched = true
      bodyH.value = sanitizeBodyH(h)
      persist()
    }

    // 账号级记忆接线：可重臂——auth 复位后由 useChartDock() 重新挂接，
    // SPA 换账号后新账号的布局才能套用（memoryWired 防重复挂接）
    wireMemory = () => {
      if (memoryWired) return
      memoryWired = true
      void loadChartMemory()
        .then(({ memoryEnabled, state }) => {
          if (userTouched) return
          if (memoryEnabled === true && state.layout) {
            // 「关=不读」：memory=false + state 非空的异常服务端态（清空 PUT 失败/
            // in-flight 竞态）不得套用旧布局，落到下方 ===false 复位分支。
            // 必须等 nextTick（父组件重渲染）后再套用：勾选恢复回调（同一 promise
            // FIFO 先行）只改了 ref，本组件的 activeKeys prop 要等渲染刷新才更新——
            // 立即 reconcile 会拿旧 prop 把已存布局裁剪降级、占比回默认。
            void nextTick(() => {
              if (userTouched) return
              rows.value = state.layout!.rows.map((r) => [...r])
              rowPcts.value = [...(state.layout!.rowPcts ?? [])]
              colPcts.value = (state.layout!.colPcts ?? []).map((c) => [...c])
              bodyH.value = sanitizeBodyH(state.layout!.bodyH)
              reconcile(getActive())
            })
          } else if (memoryEnabled === true) {
            // 账号空：把本机布局推上账号（第二台设备获得第一台的布局）。
            // 挂载 reconcile 只为渲染裁剪、不落盘，推 localStorage 原始布局
            //（可能含暂未勾选的图——下次进入由 layout 反推勾选恢复）
            const stored = loadLayout()
            if (stored) {
              const payload = {
                v: VERSION,
                rows: stored.rows,
                rowPcts: stored.rowPcts,
                colPcts: stored.colPcts,
                bodyH: stored.bodyH,
              }
              saveChartState({ layout: payload })
            } else {
              persist()
            }
          } else if (memoryEnabled === false) {
            // 开关关 = 完全不记忆：回默认布局并清本机残留（不打断已发生的用户操作）
            const d = defaultLayout(getActive())
            rows.value = d.rows
            rowPcts.value = d.rowPcts
            colPcts.value = d.colPcts
            bodyH.value = null
            safeRemoveItem(DOCK_LAYOUT_STORAGE_KEY)
          }
          // memoryEnabled === null（未返回/拉取失败）：什么都不做、也不落盘
          // 挂载裁剪的结果——本机布局保留（一次网络抖动不得清掉本机数据）
        })
        .catch(() => {})
    }
    wireMemory()

    singleton = {
      rows, rowPcts, colPcts, bodyH,
      reconcile, moveTo, reset, setRowPcts, setColPcts, setBodyH, findPos,
      addGuest, removeGuest,
    }
  }
  refCount++
  wireMemory?.() // 已接线则 no-op；auth 复位后此处重新挂接新账号布局
  const api = singleton
  return api
}

/** 供组件卸载时调用（当前单例常驻，保留布局；预留钩子） */
export function releaseChartDock() {
  refCount = Math.max(0, refCount - 1)
}

/** 登出/登入（stores/auth.ts）调用：复位脏标记与接线臂，新账号重新套用其布局 */
export function resetChartDockMemoryState() {
  userTouched = false
  memoryWired = false
}

/** resize-end 的像素数组折回百分比（0-100，相加≈100），用于持久化与 :size 回填 */
export function pctFromPx(pxSizes: number[]): number[] {
  const total = pxSizes.reduce((a, b) => a + (Number.isFinite(b) ? b : 0), 0)
  if (total <= 0) return equalPct(pxSizes.length)
  return pxSizes.map((s) => ((Number.isFinite(s) ? s : 0) / total) * 100)
}
