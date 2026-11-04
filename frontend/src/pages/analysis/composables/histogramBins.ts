/**
 * 直方图「哪些 bin 该出现」的唯一口径（纯函数，零依赖）
 * ────────────────────────────────────────────────
 * 从 HistogramChart.vue 的内联实现抽出：2D 与 3D 同屏时，一边裁了柱另一边没裁
 * 就是同界面口径矛盾（specs/2026-11-04 §8；本项目反复修过同类问题）。
 * 有意偏离旧内联实现的只有 finiteOr 这一道闸：非有限的 bound 一律按「那一侧不裁」
 * 处理。旧写法 `c >= clipMin` 在 clipMin=null 时被 JS 隐式当 0（R4②：后端
 * _helpers.py:126-129 clean_data 把 NaN/±Inf 序列化成 JSON null），会把全部负中心柱
 * 悄悄藏掉。线上只到得了 null 这一支（后端只会发数字或 null），NaN/±Inf/字符串是同一
 * 道闸顺带挡住，写在这里是因为共用函数不能把这坑带给 3D。
 * 本模块只管柱体显隐；轴范围是另一件事，2D 用**全量** binCenters 定 min/max
 * （HistogramChart.vue:84），序列图另有口径（serial-axis-range.ts）。
 */

export type OutlierMode = 'clip' | 'exclude' | 'off'

/**
 * 后端 `outlier_info` 里本口径要消费的部分（数值可能为 null，见上）。
 * 与 serial-axis-range.ts:21 `SerialOutlierInfo` 逐字同形——那份属于序列图模块，
 * 这里刻意不 import 过来复用（柱体显隐不该反向依赖轴范围）；代价是改异常值口径
 * 时两份字段声明要一起对。
 */
export interface OutlierBounds {
  has_outliers?: boolean
  lower_bound?: number | null
  upper_bound?: number | null
}

export interface BinClipSource {
  binCenters: number[]
  handlingMode: OutlierMode
  outlierInfo: OutlierBounds | null | undefined
  /** 档位取值 RDL / DR / CL / S3 / S4 / S6（ChartConfigPanel.vue:28-33 的 value）；只有 RDL 参与放宽 */
  rangeType: string
  lowerLimit?: number | null
  upperLimit?: number | null
}

function finiteOr(v: number | null | undefined, fallback: number): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback
}

/** 需要藏柱体的档位只有 clip；exclude 只换统计口径，不动柱体 */
function clipBounds(src: BinClipSource): [number, number] {
  const info = src.outlierInfo
  if (src.handlingMode !== 'clip' || !info?.has_outliers) return [-Infinity, Infinity]
  let lo = finiteOr(info.lower_bound, -Infinity)
  let hi = finiteOr(info.upper_bound, Infinity)
  // RDL 模式下原始 Limit 线内的数据不该被当异常值隐藏：边界并上规格限。
  // 在真实载荷上这一支是恒等：后端对**每个**档位都已用同一对 rdl 展过界
  // （outliers.py:78-83 由 histogram.py:126-128 无条件传入，展完的值就是响应里的
  // lower_limit/upper_limit，见 histogram.py:310-311），Math.min/max 拿回去不变。
  // 保留是为了让本口径不依赖那条后端不变量，也维持 2D 抽出前的逐字语义。
  if (src.rangeType === 'RDL' && src.lowerLimit != null && src.upperLimit != null) {
    lo = Math.min(lo, src.lowerLimit)
    hi = Math.max(hi, src.upperLimit)
  }
  return [lo, hi]
}

/** 应显示的 bin 下标（升序）；边界病态到一格不剩时回退全部，不画空图 */
export function activeBinIndices(src: BinClipSource): number[] {
  const { binCenters } = src
  if (binCenters.length === 0) return []
  const [lo, hi] = clipBounds(src)
  const kept = binCenters
    .map((c: number, i: number) => (c >= lo && c <= hi ? i : -1))
    .filter((i: number) => i >= 0)
  return kept.length > 0 ? kept : binCenters.map((_: number, i: number) => i)
}
