// frontend/e2e/helpers/pool-core.d.mts
// pool-core.mjs 的类型面。**SlotManifest 的字段就是 slot.json 的形状** ——
// TS 侧（e2e/helpers/slot.ts）从这里 import type，契约只有一份声明。
export interface SlotPortPair {
  backend: number
  frontend: number
}

export interface SlotManifest {
  index: number
  backendPort: number
  frontendPort: number
  dataDir: string
  tempDir: string
  dbPath: string
  mediaDir: string
  systemConfigFile: string
  slotFile: string
  authDir: string
  downloadsDir: string
  blobDir: string
  jsonOut: string
  logFile: string
  templateDbPath: string
  templateMediaDir: string
  redisDb: number
  secretKey: string
}

export interface SlotStats {
  expected?: number
  unexpected?: number
  flaky?: number
  skipped?: number
}

/** 单个 slot 的 JSON reporter 统计（由编排器从 results.json 折算而来） */
export interface SlotReport {
  specs?: number
  passCount?: number
  passMs?: number
  wallMs?: number
  stats?: SlotStats
}

export interface MergedStats {
  specs: number
  passCount: number
  passMs: number
  /** 并发 ⇒ 最长 slot 的跨度，不是求和 */
  wallMs: number
  stats: Required<SlotStats>
  /** 只计通过用例；秒失败的 duration≈0，计入分母会让崩池轮算出更好看的数字 */
  perSpecMs: number
  /** Σ通过时长 / 墙钟 ≈ 实际达到的并行度 */
  efficiency: number
  slots: number
}

export declare const SLOT_BACKEND_BASE: number
export declare const SLOT_FRONTEND_BASE: number
export declare const DEFAULT_SLOTS: number
export declare const MAX_SLOTS: number
export declare const SLOT_TARGET_MS: number
/** 2026-10-14 串行全量实测单价（只计通过用例），用作 autoSlots 的等价参照 */
export declare const SERIAL_REF_PER_SPEC_MS: number

/** 把并发轮测出的总时长折回串行等价量；单价缺失/为 0 时原样返回 */
export declare function normalizeTotalMs(rawTotalMs: number, perSpecMs?: number, refPerSpecMs?: number): number

export declare function autoSlots(totalMs: number, cap?: number): number

export declare function allocatePortBlock(
  n: number,
  isTaken: (port: number) => boolean,
  baseBackend?: number,
  baseFrontend?: number,
): SlotPortPair[]

export declare function partitionFiles(
  files: string[],
  durationsMs: Record<string, number>,
  n: number,
): string[][]

export declare function assertSafeRelPath(p: string): string

export interface ParsedArgs {
  /** `--` 之后的原始参数（文件路径等） */
  files: string[]
  /** 未在 defaults 里声明过的 token：调用方应当拒绝而不是忽略 */
  unknown: string[]
  [key: string]: string | boolean | undefined | string[] | unknown
}

export declare function parseArgs(argv: string[], defaults?: Record<string, unknown>): ParsedArgs

export declare function buildSlotManifest(args: {
  index: number
  ports: SlotPortPair
  slotRoot: string
  templateRoot: string
  redisDb: number
  secretKey: string
  /** 共享 blob 目录：`merge-reports` 只接受一个目录参数 */
  blobRoot?: string
  /** run.log / results.json 的落脚处：必须**在 slot 目录之外**，否则收尾清理会把证据一起删掉 */
  evidenceRoot?: string
}): SlotManifest

export declare function slotEnv(
  manifest: SlotManifest,
  baseEnv?: Record<string, string | undefined>,
): Record<string, string | undefined>

export declare function mergeRunStats(reports: SlotReport[]): MergedStats
