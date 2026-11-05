/**
 * 3D 视角的可持久化形状 + 从 gl 相机读取（specs/2026-11-05 §4）。
 *
 * 相机实时态**不在** getOption() 里：viewControl 只代表最后一次 setOption 的初值，
 * 交互只改 OrbitControl 内部状态（2026-11-05 真机实测：拖拽后 getOption 的 alpha 不变）。
 * 所以读取统一走 Grid3D 视图上的 `_control`（gl 私有字段，锁定的 2.1.0 实测；
 * 升级 gl 要重跑 site3dView.spec 与 e2e 的视角保留用例）。
 *
 * orthographicSize 存**模型值**：gl 的 setFromViewControlModel 把生效值算成
 * `model + baseOrthoSize`，而 Grid3DView 调用时 extraOpts=0 ⇒ baseOrthoSize=1
 * （echarts-gl.js:41467 与 :39002-39016）。读取减 1，写回由 gl 加 1。
 */
export interface Site3DView {
  alpha: number
  beta: number
  distance: number
  /** 模型值（生效值 = 本值 + 1，见文件头） */
  orthographicSize: number
  /** 中键平移后的观察中心 */
  center: [number, number, number]
}

/** Grid3DView 传给 setFromViewControlModel 的 baseOrthoSize（echarts-gl.js:41467） */
const ORTHO_BASE = 1

interface OrbitControlLike {
  getAlpha(): number
  getBeta(): number
  getDistance(): number
  getOrthographicSize(): number
  getCenter(): number[]
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

/** 账号记忆里的视角：五个量必须都是有限数，否则整份丢弃（半信一半会画出怪机位） */
export function sanitizeSite3DView(raw: unknown): Site3DView | null {
  if (!raw || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  const c = o.center
  if (!Array.isArray(c) || c.length !== 3) return null
  // 逐位检查而不是 c.every：every 会跳过稀疏数组的空洞（`[1, , 3]` 实测能过关）
  if (!isFiniteNumber(c[0]) || !isFiniteNumber(c[1]) || !isFiniteNumber(c[2])) return null
  if (
    !isFiniteNumber(o.alpha) ||
    !isFiniteNumber(o.beta) ||
    !isFiniteNumber(o.distance) ||
    !isFiniteNumber(o.orthographicSize)
  ) return null
  return {
    alpha: o.alpha,
    beta: o.beta,
    distance: o.distance,
    orthographicSize: o.orthographicSize,
    center: [c[0], c[1], c[2]],
  }
}

/** 相机读数的浮点容差：小于它的差异视为「没动过」（angles 单位是度，其余是 gl 世界单位） */
const VIEW_EPS = 0.01

/**
 * 两份机位是否等价。用途：`pointerup` 在单击/tooltip 时也会触发，不能把「没动镜头」
 * 当成用户决定（否则会挡住迟到加载，还会把未动过的默认机位写进账号）。
 */
export function isSameSite3DView(a: Site3DView, b: Site3DView): boolean {
  const close = (x: number, y: number) => Math.abs(x - y) <= VIEW_EPS
  return (
    close(a.alpha, b.alpha) &&
    close(a.beta, b.beta) &&
    close(a.distance, b.distance) &&
    close(a.orthographicSize, b.orthographicSize) &&
    close(a.center[0], b.center[0]) &&
    close(a.center[1], b.center[1]) &&
    close(a.center[2], b.center[2])
  )
}

/** 从已初始化的 echarts 实例读当前机位；实例/视图/字段缺失时返回 null */
export function readLiveView(chart: unknown): Site3DView | null {
  try {
    const inst = chart as any
    const model = inst?.getModel?.()?.getComponent?.('grid3D')
    if (!model) return null
    const view = inst?.getViewOfComponentModel?.(model)
    const control = view?._control as OrbitControlLike | undefined
    if (!control) return null
    return sanitizeSite3DView({
      alpha: control.getAlpha(),
      beta: control.getBeta(),
      distance: control.getDistance(),
      orthographicSize: control.getOrthographicSize() - ORTHO_BASE,
      // 原样交给 sanitize 校验：坏 center 让整份视角作废，别用 0 兜底冒充「居中」
      center: control.getCenter(),
    })
  } catch (err) {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.warn('[site3dView] readLiveView failed:', err)
    }
    return null
  }
}
