/**
 * 「一个后端句柄」的形状。
 *
 * 单独成模块的理由是硬的：这个类型原先住在 backend.ts 里，而 backend.ts 运行期
 * import 了 'electron'。前端侧只要 `import type { BackendInfo }`，`vue-tsc -b` 就会把
 * backend.ts 拉进 program —— frontend 的 tsconfig 没有 electron 的 paths 映射，于是
 * `npm run build` 当场红（TS2307 Cannot find module 'electron'）。2026-10-28 由
 * `test:e2e:affected` 的构建步抓到。类型放这里，纯模块才敢被测试与前端引用。
 */

import type { ChildProcess } from 'child_process'

export interface BackendInfo {
  port: number
  pid: number | null
  process: ChildProcess | null
  /** Whether this process was spawned by Electron and should be stopped on quit. */
  managed: boolean
  /**
   * Per-launch token for POST /api/v1/system/shutdown/. Null for an unmanaged
   * backend (the dev server on :8000), which Electron must not stop anyway.
   */
  shutdownToken: string | null
}
