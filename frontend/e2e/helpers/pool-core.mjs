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

/**
 * CLI 解析：`--k=v`、`--k v`、布尔 `--k` 三种写法都认。
 * 只认空格形式的后果实测过：`--slots=1` 被当成没给 ⇒ 静默按默认档跑（等于偷偷改了并行度）。
 * 未在 defaults 里声明的 `--x` 一律进 `unknown`，供调用方拒绝而不是忽略。
 */
export function parseArgs(argv, defaults = {}) {
  const out = { files: [], unknown: [] }
  const set = (name, value) => {
    out[name] = value
    const camel = name.replace(/-([a-z])/g, (_, c) => c.toUpperCase())
    if (camel !== name) out[camel] = value
  }
  for (const [k, v] of Object.entries(defaults)) set(k, v)
  const dd = argv.indexOf('--')
  const head = dd < 0 ? argv : argv.slice(0, dd)
  out.files = dd < 0 ? [] : argv.slice(dd + 1)
  for (let i = 0; i < head.length; i++) {
    const tok = head[i]
    if (!tok.startsWith('--')) { out.unknown.push(tok); continue }
    const eq = tok.indexOf('=')
    const name = eq < 0 ? tok.slice(2) : tok.slice(2, eq)
    if (!(name in defaults)) out.unknown.push(tok)
    if (eq >= 0) { set(name, tok.slice(eq + 1)); continue }
    const next = head[i + 1]
    if (typeof defaults[name] !== 'boolean' && next !== undefined && !next.startsWith('--')) { set(name, next); i++ }
    else set(name, true)
  }
  return out
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

export function buildSlotManifest({ index, ports, slotRoot, templateRoot, redisDb, secretKey, blobRoot, evidenceRoot }) {
  // 取证文件（run.log / results.json）刻意**不放在 slotRoot 里**：收尾会 rmSync(slotRoot) 回收 1GB 级镜像，
  // 一起删掉就等于在最需要看日志的那一轮把证据销毁了（实测归因 A/C 两组红时没日志可看）。
  const ev = evidenceRoot ?? slotRoot
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
    // merge-reports 只接受**一个**目录 ⇒ 编排器给所有 slot 传同一个 blobRoot（blob 文件名自带随机后缀，不冲突）
    blobDir: blobRoot ?? path.join(slotRoot, 'blob'),
    jsonOut: path.join(ev, `slot${index}.results.json`),
    logFile: path.join(ev, `slot${index}.run.log`),
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
 * 把「并行轮测出来的总时长」折回串行等价量，只用于 autoSlots。
 * 为什么需要：LPT 分桶只看相对权重（缩放不影响），但 autoSlots 拿绝对总量反推并行度；
 * 时长表一旦来自 pool 自己的 merged.json（单价含争用），总量就被系统性抬高 ⇒ 每轮多开一个 slot
 * ⇒ 争用更重 ⇒ 下一轮总量更高，是个自我强化的反馈环。实测：串行基线 1054s，N=4 轮 merged.json 是 1404s。
 */
export const SERIAL_REF_PER_SPEC_MS = 2890   // 2026-10-14 串行全量实测单价（只计通过用例）

export function normalizeTotalMs(rawTotalMs, perSpecMs, refPerSpecMs = SERIAL_REF_PER_SPEC_MS) {
  if (!perSpecMs || perSpecMs <= 0 || !rawTotalMs) return rawTotalMs
  return rawTotalMs * (refPerSpecMs / perSpecMs)
}

/**
 * 看门狗的掉线判定：单次探测失败不算掉线。
 * 实测教训：N=4 满载时一次 150ms 的 connect 探测会超时，于是把活着的 4 个 slot 全报成「掉线」
 * （那一轮只有 2 条红、verdict MEASURED ⇒ 谎报）。判死必须满足：连续 LIVENESS_MISSES 次探不到，
 * 且该 slot 的子进程还没退出（退出了端口关闭是正常收尾，不是事故）。
 */
export const LIVENESS_MISSES = 2
export const LIVENESS_TIMEOUT_MS = 1_500

export function nextLivenessState({ misses = 0, dead = false }, probeOpen, childAlive) {
  if (dead || !childAlive) return { misses, dead, done: true }
  if (probeOpen) return { misses: 0, dead: false }
  const next = misses + 1
  return next >= LIVENESS_MISSES ? { misses: next, dead: true } : { misses: next, dead: false }
}

/**
 * 红文件的自动复跑判级（用户 2026-10-15 拍：门禁仍要求零真红，但负载抖动要自动消化）。
 * 输入是第一轮报红的文件清单 + 每个文件「独占一个 slot 复跑」的结果，输出三级：
 *   confirmed   复跑仍红 ⇒ 真红，门禁拦
 *   loadFlakes  复跑绿 ⇒ 判为满载抖动，记 flake 不记真红（台账里可见，不静默丢弃）
 *   unresolved  复跑本身崩池 / 用例压根没跑上 / 结果缺失 ⇒ 保守算红，绝不因「没验成」而放行
 */
export function classifyReds(redFiles, recheckResults) {
  const byFile = new Map((recheckResults ?? []).map((r) => [r.file, r]))
  const confirmed = [], loadFlakes = [], unresolved = []
  for (const f of [...new Set(redFiles ?? [])].sort()) {
    const r = byFile.get(f)
    if (!r || r.infra || r.specs === 0) unresolved.push(f)
    else if (r.red) confirmed.push(f)
    else loadFlakes.push(f)
  }
  return { confirmed, loadFlakes, unresolved, countsBlock: confirmed.length + unresolved.length > 0 }
}

/**
 * 单 slot 健康判定：区分「有用例红」与「服务半路死了导致的成片红」。
 * 实测依据：一次 N=4 轮里两个 slot 的 preview+后端在开跑约 1 分钟后失联，
 * 该轮报出 155 unexpected、效率 1.21 —— 当成真实结果发出去就是假信号。
 * 两条判据任一命中：连接级错误成堆（refused ≥5），或红占该 slot 用例数一半以上且绝对数 ≥20。
 */
export function classifySlotHealth({ specs = 0, unexpected = 0, refusedCount = 0 }) {
  if (refusedCount >= 5) return 'INFRA'
  const share = specs ? unexpected / specs : 0
  if (unexpected >= 20 && share >= 0.5) return 'INFRA'
  return 'OK'
}

/** 整轮结论：任一 slot 判 INFRA ⇒ 本轮指标不可信（不进时间序列、不参与门禁） */
export function roundVerdict(slotReports) {
  const infra = slotReports.filter((r) => classifySlotHealth(r) === 'INFRA').map((r) => r.slot)
  return { verdict: infra.length ? 'VOID (infra)' : 'MEASURED', infraSlots: infra }
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
