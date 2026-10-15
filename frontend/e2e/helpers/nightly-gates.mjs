// frontend/e2e/helpers/nightly-gates.mjs
// 夜间/收口全量轮的退化判据。**并行时代必须重标定**：争用会抬高单价同时压低墙钟，
// 拿串行时代「单价 >3.5s 判退化」过来必然误报（实测 N=4 干净轮单价 3.01~3.10s，
// 而被我并行敲 tsc 污染的那轮到 3.90s）。所以主信号换成墙钟 + 并行效率，单价退居次要并放宽。
// 阈值改这里，不留口头约定。

export const THRESHOLDS = {
  // 目标 10min 级 + 2min 余量；同时充当挂死探测（单 slot 有 --timeout-min 兜底）。
  wallMs: 12 * 60_000,
  // 实测 N=4 干净轮 3.01~3.10s/例，留 ~45% 余量给争用波动；几轮夜间数据出来后再收紧。
  perSpecMs: 4_500,
  specs: 450,             // 业务用例数上限（2026-10-15 实测 384；注意口径已剔除 setup）
  flakes: 5,              // = Playwright flaky + 复跑判为负载抖动的文件数
  efficiencyFloorFactor: 0.7,   // Σ通过时长/墙钟 ≥ 0.7×N，否则「并行在空转」
}

/** 崩池轮（服务失联导致成片红）什么都不判：它的指标全部不可信，结论是"重跑"。 */
export function isVoided(rep) {
  return !!rep && (rep.verdict === 'VOID (infra)' || rep.voidInfra === true)
}

/**
 * 拦门禁的"真红"数。有复跑判级时 = confirmed + unresolved（"没验成"保守算红，
 * 绝不因跑不出结论而放行）；没有复跑结果时退回原始 unexpected 计数。
 */
export function blockingReds(rep) {
  if (isVoided(rep)) return { count: null, voided: true, confirmed: 0, unresolved: 0 }
  const rc = rep?.recheck
  if (rc) {
    const confirmed = rc.confirmed?.length ?? 0
    const unresolved = rc.unresolved?.length ?? 0
    return { count: confirmed + unresolved, voided: false, confirmed, unresolved }
  }
  const unexpected = rep?.stats?.unexpected ?? 0
  return { count: unexpected, voided: false, confirmed: unexpected, unresolved: 0 }
}

/** flake 记账 = 重试后通过的用例 + 复跑转绿的负载抖动文件 */
export function flakeTotal(rep) {
  return (rep?.stats?.flaky ?? 0) + (rep?.recheck?.loadFlakes?.length ?? 0)
}

/** @param {number} slots 本轮实际并行度（N），效率下限按它算 */
export function evaluateGates(rep, slots) {
  if (isVoided(rep)) return []
  const b = []
  if (rep.wallMs > THRESHOLDS.wallMs) {
    b.push(`墙钟 ${(rep.wallMs / 60000).toFixed(1)}min > ${THRESHOLDS.wallMs / 60000}min（目标闸门兼挂死探测）`)
  }
  if (rep.perSpecMs > THRESHOLDS.perSpecMs) {
    b.push(`单价 ${(rep.perSpecMs / 1000).toFixed(2)}s/例 > ${THRESHOLDS.perSpecMs / 1000}s/例`)
  }
  if (rep.specs > THRESHOLDS.specs) b.push(`用例数 ${rep.specs} > ${THRESHOLDS.specs}`)
  const flakes = flakeTotal(rep)
  if (flakes > THRESHOLDS.flakes) b.push(`flake ${flakes} > ${THRESHOLDS.flakes}`)
  const floor = THRESHOLDS.efficiencyFloorFactor * slots
  // 效率字段缺失 = 这轮不是并行产物（旧的串行 results.json），缺字段不等于违规
  if (rep.efficiency != null && rep.efficiency < floor) {
    b.push(`效率 ${rep.efficiency.toFixed(2)} < ${floor.toFixed(1)}（0.7×${slots} slot）—— 并行在空转，查拖尾或争用`)
  }
  const red = blockingReds(rep)
  if (red.count > 0) {
    b.push(`真红 ${red.confirmed}${red.unresolved ? ` + 悬而未决 ${red.unresolved}` : ''}（负载抖动已判级不计入）`)
  }
  return b
}
