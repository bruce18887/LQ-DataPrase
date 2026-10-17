/**
 * 序列分布图 Y 轴范围（单 lane 一条），从 SerialChart.buildOption 里抽出成纯函数：
 * 判据是「入参点集 + 限值 + 档位 → 一对边界」，无 DOM 无网络，故由 T2（vitest）
 * 跑全组合，e2e 只留「轴真的按这个口径渲染」的接线证明。
 *
 * 两条不变量（改本文件前先读）：
 *  1. 结果 ⊇ 全部 anchor==0 的点值 —— 正常点永不被裁。数据自适应那半保证下界，
 *     限值入框只做并集扩张，所以两条来源不会互相削减。
 *  2. RDL/CL 档且两限齐备时，结果 ⊇ [LSL − m, USL + m] —— 两条规格限线同时可见，
 *     且外侧各留 m 余量，不会被钉在轴边上。
 *
 * anchor 语义仍由后端 `_anchor()` 按 `spec±10%` 打（见 serial_distribution.py），
 * 前端只负责把 anchor=2/3 的点贴边绘制。注意本函数**不再**保证「结果 ⊂ 后端
 * y_min/y_max」：2026-09-13 那版数据自适应靠这条性质成立，而不变量 2 要求轴
 * 反过来盖住限值窗，两者只能留其一（留 2，见 2026-10-17 需求）。
 */

/** 后端点格式 [serial, value|null, is_fail, anchor]；无 bin 列的文件退化为 [serial, value] */
export type SerialPoint = (number | string | null)[]

export interface SerialOutlierInfo {
  has_outliers?: boolean
  lower_bound?: number | null
  upper_bound?: number | null
}

export interface SerialYBoundsInput {
  /** 本 lane 的原始点集（未经 anchor 过滤） */
  points: SerialPoint[]
  /** 后端 y_min/y_max：本 lane 无可绘制点时的兜底边界（无规格限时为 null → 交给 ECharts 自动缩放） */
  fallback: [number, number]
  /** 当前档位的规格限（后端 resolve_limits 结果，即「规格限」markLine 画的那两条） */
  lowerLimit?: number | null
  upperLimit?: number | null
  /** 取值区间档位：RDL / DR / CL / S3 / S4 / S6 */
  rangeType?: string
  outlierInfo?: SerialOutlierInfo | null
  outlierHandling?: 'clip' | 'exclude' | 'off'
}

/** 数据带自身的外沿余量，比例取 anchor==0 值跨度 */
export const DATA_PAD = 0.08
/** 限值外侧余量，比例取限值窗宽度。直方图同轴实测 17.2%，但序列图的 Y 只有它 1/3 量级的
 *  像素高度，照搬会把数据带吃掉三分之一，故收紧到 10%（两限仍明确离边）。 */
export const LIMIT_PAD = 0.10
/** 只有「用户认作规格窗」的档位参与轴范围。DR 的数据本就等于该窗，σ 档的窗可达数据
 *  带宽的数十倍（截图里 6σ = [−1054, 1107]），把它们框进来等于交出一张空图。 */
export const LIMIT_FRAMED_RANGE_TYPES: readonly string[] = ['RDL', 'CL']

function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

/** anchor==0 值的 min/max ± DATA_PAD；单值/全等退化用 |v|·5%；无有效值回退后端范围 */
function dataAdaptiveRange(input: SerialYBoundsInput): [number, number] {
  let mn = Infinity
  let mx = -Infinity
  for (const p of input.points) {
    if ((p[3] ?? 0) !== 0) continue // 超界点锚到轴边，不参与范围（否则极值炸开）
    const v = p[1]
    if (!isFiniteNumber(v)) continue
    if (v < mn) mn = v
    if (v > mx) mx = v
  }
  if (mn === Infinity) return [input.fallback[0], input.fallback[1]]
  if (mx > mn) {
    const pad = (mx - mn) * DATA_PAD
    return [mn - pad, mx + pad]
  }
  const dlt = Math.max(Math.abs(mx) * 0.05, 1e-9)
  return [mn - dlt, mx + dlt]
}

/** 把限值窗并进范围并保证两限外侧余量；不满足参与条件时原样返回 */
function frameByLimits(
  range: [number, number],
  input: SerialYBoundsInput,
): [number, number] {
  const { lowerLimit: lo, upperLimit: hi, rangeType } = input
  if (!rangeType || !LIMIT_FRAMED_RANGE_TYPES.includes(rangeType)) return range
  if (!isFiniteNumber(lo) || !isFiniteNumber(hi) || hi <= lo) return range
  const m = (hi - lo) * LIMIT_PAD
  const [dLo, dHi] = range
  return [
    isFiniteNumber(dLo) ? Math.min(dLo, lo - m) : lo - m,
    isFiniteNumber(dHi) ? Math.max(dHi, hi + m) : hi + m,
  ]
}

/** 异常值处理档：沿用 IQR 栅栏 ±10% 的有意的裁剪口径，不做数据自适应、也不并入限值窗 */
function iqrFenceRange(input: SerialYBoundsInput): [number, number] | null {
  if (!input.outlierHandling || input.outlierHandling === 'off') return null
  const info = input.outlierInfo
  if (!info?.has_outliers) return null
  const lo = info.lower_bound
  const hi = info.upper_bound
  if (!isFiniteNumber(lo) || !isFiniteNumber(hi) || hi <= lo) return null
  const pad = (hi - lo) * 0.1
  return [lo - pad, hi + pad]
}

/**
 * 单 lane 的 Y 轴边界。优先级：IQR 裁剪档 > （数据自适应 ∪ 限值窗）。
 * 边界可能带 null（后端无规格限且本 lane 无可绘制点），此时 ECharts 自动缩放。
 */
export function resolveSerialYBounds(input: SerialYBoundsInput): [number, number] {
  return iqrFenceRange(input) ?? frameByLimits(dataAdaptiveRange(input), input)
}
