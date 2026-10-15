// frontend/e2e/helpers/pool-core.mjs
// slot 池的纯逻辑：无 fs、无子进程、无 Playwright —— 全部可在 vitest(node) 下断言。
// 消费方有两个：scripts/e2e_pool.mjs（编排）与 frontend/e2e/helpers/slot.ts（harness 读清单）。
// 判据见 docs/superpowers/specs/2026-10-14-e2e-slot-pool-parallel-design.md
import path from 'node:path'

export const SLOT_BACKEND_BASE = 8101
export const SLOT_FRONTEND_BASE = 3101
export const DEFAULT_SLOTS = 4
export const MAX_SLOTS = 6
export const SLOT_TARGET_MS = 240_000

/** 由 LPT 总量反推 slot 数：目标是单 slot 墙钟不超过 SLOT_TARGET_MS */
export function autoSlots(totalMs, cap = DEFAULT_SLOTS) {
  return Math.max(1, Math.min(cap, Math.ceil((totalMs || 0) / SLOT_TARGET_MS)))
}

/** 连续 n 对端口；扫不到就抛 —— 宁可拒绝启动，也不复用别人在跑的服务 */
export function allocatePortBlock(n, isTaken, baseBackend = SLOT_BACKEND_BASE, baseFrontend = SLOT_FRONTEND_BASE) {
  for (let shift = 0; shift < 40; shift++) {
    const startBackend = baseBackend + shift * n
    const startFrontend = baseFrontend + shift * n
    const block = Array.from({ length: n }, (_, i) => ({ backend: startBackend + i, frontend: startFrontend + i }))
    if (block.every((p) => !isTaken(p.backend) && !isTaken(p.frontend))) return block
  }
  throw new Error(`端口块不足：需要 ${n} 对连续端口（基址 ${baseBackend}/${baseFrontend}，已试 40 个块）`)
}

/**
 * LPT：按实测时长降序，逐个投进当前最轻的桶。
 * 用实测时长而非文件数 —— 386 例里 top5 文件占 31%、中位只有 7.8s，等文件数切分必然一个桶拖尾。
 * 同权重以文件名字序定，使跨运行的桶组合尽量稳定（污染才可复现）。
 */
export function partitionFiles(files, durationsMs, n) {
  if (n < 1) throw new Error('slot 数 n 必须 ≥ 1')
  const buckets = Array.from({ length: n }, () => ({ ms: 0, files: [] }))
  const order = [...files].sort((a, b) => (durationsMs[b] ?? 0) - (durationsMs[a] ?? 0) || a.localeCompare(b))
  for (const file of order) {
    let lightest = buckets[0]
    for (const bucket of buckets) if (bucket.ms < lightest.ms) lightest = bucket
    lightest.files.push(file)
    lightest.ms += durationsMs[file] ?? 0
  }
  return buckets.map((b) => b.files.sort((a, c) => a.localeCompare(c)))
}

// 编排器在 Windows 下用 shell:true 起 Playwright，这些串会直接进命令行 ⇒ 自己把关
const UNSAFE = /["'\s&|^<>()!*$[\];,{}\\]/
export function assertSafeRelPath(p) {
  if (UNSAFE.test(p)) throw new Error(`路径不安全（含 shell 元字符/空格）: ${p}`)
  return p
}

export function buildSlotManifest({ index, ports, slotRoot, templateRoot, redisDb, secretKey }) {
  return {
    index,
    backendPort: ports.backend,
    frontendPort: ports.frontend,
    dataDir: slotRoot,
    tempDir: path.join(slotRoot, 'temp'),
    dbPath: path.join(slotRoot, 'db.sqlite3'),
    mediaDir: path.join(slotRoot, 'media'),
    systemConfigFile: path.join(slotRoot, 'system-config.json'),
    slotFile: path.join(slotRoot, 'slot.json'),
    authDir: path.join(slotRoot, '.auth'),
    downloadsDir: path.join(slotRoot, '.downloads'),
    blobDir: path.join(slotRoot, 'blob'),
    jsonOut: path.join(slotRoot, 'results.json'),
    logFile: path.join(slotRoot, 'run.log'),
    templateDbPath: path.join(templateRoot, 'db.sqlite3'),
    templateMediaDir: path.join(templateRoot, 'media'),
    redisDb,
    secretKey,
  }
}

/**
 * 每 slot 的进程环境。
 * - CI=1：forbidOnly 生效、retries=2，且 playwright.config 的 reuseExistingServer 关掉
 * - DJANGO_SETTINGS_MODULE=e2e_slot + LQDP_E2E_SLOT_DIR：库/媒体/临时区的唯一来源。
 *   刻意不注入存储目录重定向相关变量 —— 那条通路是 move 语义（spec §4.1、lessons 2026-10-14）
 * - SECRET_KEY 逐 slot 不同：每份库副本里 admin 的 PK 都是 1，共用密钥时端口一搞错就是静默写别人的库
 * - SFTP 会话缓存键是 sftp:conn:<user_id>（apps/sftp/cache.py:43,116），同理必须逐 slot 换 Redis db
 */
export function slotEnv(manifest, baseEnv = process.env) {
  return {
    ...baseEnv,
    LQDP_E2E_SLOT_FILE: manifest.slotFile,
    LQDP_SYSTEM_CONFIG_FILE: manifest.systemConfigFile,
    DJANGO_SETTINGS_MODULE: 'config.settings.e2e_slot',
    LQDP_E2E_SLOT_DIR: manifest.dataDir,
    LQDP_ACCESS_TOKEN_MINUTES: '720',
    SECRET_KEY: manifest.secretKey,
    SFTP_SESSION_REDIS_URL: `redis://localhost:6379/${manifest.redisDb}`,
    E2E_PORT: String(manifest.backendPort),
    E2E_FRONTEND_PORT: String(manifest.frontendPort),
    CI: '1',
  }
}

/**
 * N 份 per-slot JSON 的统计合并。
 * 墙钟是并发的 ⇒ 取最长 slot 而不是求和；效率 = Σ通过时长/墙钟 ≈ 实际达到的并行度。
 * 单价只统计通过用例：秒失败的 duration≈0，计入分母会让崩池轮算出比健康轮更好看的数字。
 */
export function mergeRunStats(reports) {
  let specs = 0, passCount = 0, passMs = 0, wallMs = 0
  const stats = { expected: 0, unexpected: 0, flaky: 0, skipped: 0 }
  for (const r of reports) {
    specs += r.specs ?? 0
    passCount += r.passCount ?? 0
    passMs += r.passMs ?? 0
    wallMs = Math.max(wallMs, r.wallMs ?? 0)
    for (const k of Object.keys(stats)) stats[k] += r.stats?.[k] ?? 0
  }
  return {
    specs, passCount, passMs, wallMs, stats,
    perSpecMs: passCount ? passMs / passCount : 0,
    efficiency: wallMs ? passMs / wallMs : 0,
    slots: reports.length,
  }
}
