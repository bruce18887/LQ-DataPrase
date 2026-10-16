// frontend/e2e/helpers/slot.ts
// 编排器与 harness 之间唯一的桥：读一份 slot.json，四类路径全部经这里。
// 无 slot 时逐字等于 e2e/fixtures/test-data.ts 历史上的写法 —— 本文件不得改变非 slot 行为面。
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// SlotManifest 只有一份声明（在 pool-core.d.mts）：它就是编排器写的 slot.json 的形状，
// 两侧共用才能防止契约漂移。
import type { SlotManifest } from './pool-core.mjs'

export type { SlotManifest }

export interface SlotPaths {
  systemConfigFile: string
  authDir: string
  adminState: string
  userState: string
  downloadDir: string
  dataDir: string
  backendPort: number
  frontendPort: number
  frontendOrigin: string
}

/** 纯函数：给定清单（或 null）算出全部路径。单测直接两个分支都断言。 */
export function slotPaths(manifest: SlotManifest | null): SlotPaths {
  if (manifest) {
    for (const key of ['systemConfigFile', 'authDir', 'downloadsDir', 'dataDir'] as const) {
      // 明确给了清单却缺字段 ⇒ 编排器与 harness 版本不匹配，必须硬失败而不是回落共享目录
      if (!manifest[key]) throw new Error(`slot.json 缺字段 ${key}: ${manifest.slotFile}`)
    }
    return {
      systemConfigFile: manifest.systemConfigFile,
      authDir: manifest.authDir,
      adminState: path.join(manifest.authDir, 'admin.json'),
      userState: path.join(manifest.authDir, 'user.json'),
      downloadDir: manifest.downloadsDir,
      dataDir: manifest.dataDir,
      backendPort: manifest.backendPort,
      frontendPort: manifest.frontendPort,
      frontendOrigin: `http://localhost:${manifest.frontendPort}`,
    }
  }
  const authDir = path.join(__dirname, '..', '.auth')
  return {
    systemConfigFile: path.join(os.tmpdir(), 'lqdp-e2e-system-config.json'),
    authDir,
    adminState: path.join(authDir, 'admin.json'),
    userState: path.join(authDir, 'user.json'),
    downloadDir: path.join(__dirname, '..', '.downloads'),
    // 串行（无 slot）跑的落盘根：库 / media / temp 全在这下面，由
    // config.settings.e2e_slot 按 LQDP_E2E_SLOT_DIR 直接指认。刻意**不是**仓库根 ——
    // 仓库根 media/ 与 db.sqlite3 是 Storage Layout v2 迁移前的搁浅副本，
    // 再让测试写回去就等于把 722MB 请回来。
    // helpers 在 frontend/e2e/helpers → 上溯三级即仓库根（与 test-data.ts 的 PROJECT_ROOT 同值）
    dataDir: path.join(path.resolve(__dirname, '..', '..', '..'), 'test', 'e2e-data'),
    backendPort: Number(process.env.E2E_PORT || 8000),
    frontendPort: Number(process.env.E2E_FRONTEND_PORT || 3000),
    frontendOrigin: `http://localhost:${process.env.E2E_FRONTEND_PORT || 3000}`,
  }
}

function readManifest(): SlotManifest | null {
  const file = process.env.LQDP_E2E_SLOT_FILE
  if (!file) return null
  return JSON.parse(fs.readFileSync(file, 'utf-8')) as SlotManifest
}

export const CURRENT_SLOT = readManifest()
export const SLOTS = slotPaths(CURRENT_SLOT)

/** 兼容 test-data.ts 的旧导出名 */
export const LEGACY_SYSTEM_CONFIG_FILE = slotPaths(null).systemConfigFile
export const SYSTEM_CONFIG_FILE = SLOTS.systemConfigFile
export const AUTH_DIR = SLOTS.authDir
export const ADMIN_STATE = SLOTS.adminState
export const USER_STATE = SLOTS.userState
export const DOWNLOAD_DIR = SLOTS.downloadDir
export const DATA_DIR = SLOTS.dataDir
