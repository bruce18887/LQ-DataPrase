// frontend/e2e/helpers/nightly-gates.d.mts
// nightly-gates.mjs 的类型面（纯 JS 实现 + 这里的声明，vitest 直接跑、vue-tsc 也能查）。
export interface GateReportStats {
  unexpected?: number
  flaky?: number
  skipped?: number
  expected?: number
}

export interface GateRecheck {
  confirmed: string[]
  loadFlakes: string[]
  unresolved: string[]
  countsBlock: boolean
}

/** 判据需要的产物形状：池的 merged.json，或旧串行 results.json 折算出的等价对象 */
export interface GateReport {
  specs?: number
  wallMs?: number
  perSpecMs?: number
  efficiency?: number
  stats?: GateReportStats
  verdict?: string
  voidInfra?: boolean
  infraSlots?: number[]
  passCount?: number
  recheck?: GateRecheck | null
}

export interface Thresholds {
  wallMs: number
  perSpecMs: number
  specs: number
  flakes: number
  efficiencyFloorFactor: number
}

export declare const THRESHOLDS: Thresholds
export declare function isVoided(rep?: GateReport): boolean
export declare function blockingReds(rep?: GateReport): {
  count: number | null
  voided: boolean
  confirmed: number
  unresolved: number
}
export declare function flakeTotal(rep?: GateReport): number
export declare function evaluateGates(rep: GateReport, slots?: number): string[]
