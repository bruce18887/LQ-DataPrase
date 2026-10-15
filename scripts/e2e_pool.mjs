#!/usr/bin/env node
/**
 * e2e_pool — 并行全量的唯一入口。
 *
 * 流程：预铸 TEMP 模板（库 + 种子 media）→ 按实测时长 LPT 分区 → 起 N 个
 * 「1 进程 = 1 worker = 1 slot」的 Playwright 子进程 → 自算统计合并 + 官方 merge-reports 出 HTML。
 *
 * 每个 slot 的隔离面（全部靠 env，见 pool-core.slotEnv）：
 *   DJANGO_SETTINGS_MODULE=config.settings.e2e_slot + LQDP_E2E_SLOT_DIR=<slot>
 *   → 独立的 db.sqlite3（模板拷贝）/ media（模板的硬链镜像）/ temp / .auth / .downloads
 *   → 独立的 Django 与 preview 端口对、独立的 SECRET_KEY、独立的 Redis db index
 * 判据：docs/superpowers/specs/2026-10-14-e2e-slot-pool-parallel-design.md
 */
import { execFileSync, spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  MAX_SLOTS, SERIAL_REF_PER_SPEC_MS, SLOT_BACKEND_BASE, SLOT_FRONTEND_BASE,
  allocatePortBlock, assertSafeRelPath, autoSlots, buildSlotManifest, classifyReds, classifySlotHealth, mergeRunStats,
  LIVENESS_MISSES, LIVENESS_TIMEOUT_MS, nextLivenessState,
  normalizeTotalMs, parseArgs, parsePassthrough, partitionFiles, roundVerdict, slotEnv,
} from '../frontend/e2e/helpers/pool-core.mjs'

// Windows 上 npx/npm 是 .cmd，必须经 cmd.exe 起；一律用 argv 数组而不是拼 shell 字符串 ——
// 文件路径来自 CLI，拼字符串就是命令注入面（assertSafeRelPath 是第一道，argv 是第二道）。
const CMD = process.env.ComSpec || 'C:\\Windows\\System32\\cmd.exe'
const runTool = (tool, args, opts) => spawnSync(CMD, ['/c', tool, ...args], { shell: false, ...opts })
const captureTool = (tool, args, opts) => execFileSync(CMD, ['/c', tool, ...args], { shell: false, ...opts })

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const FRONTEND = path.join(ROOT, 'frontend')
const PY = process.env.PYTHON_BIN || path.join(ROOT, '.venv', 'Scripts', 'python.exe')
// 短基址是硬要求：Django 对 sqlite 也执行 63 字符库名检查（P0 实测 89 字符直接拒绝 migrate）
const E2E_BASE = process.env.LQDP_E2E_ROOT || 'C:\\lqdp-e2e'
const TEMPLATE = path.join(E2E_BASE, 'template')
const SLOTS_ROOT = path.join(E2E_BASE, 'slots')
const PW_EXTRA = parsePassthrough(process.env.E2E_PW_ARGS)   // 调用方透传给 Playwright 的开关（走 env，不混进 `--` 后的文件表）
const RUN_ID = new Date().toISOString().slice(11, 19).replace(/:/g, '') + `-${process.pid}`
const PORT_SPAN = 60
// 基址会进 cmd 的 argv 与 Django 的库名：空格/引号/元字符一律拒绝，别让它变成解析歧义
if (/["'`$&|<>\s]/.test(E2E_BASE) || path.join(E2E_BASE, 'template', 'db.sqlite3').length > 63) {
  throw new Error(`LQDP_E2E_ROOT 不可用：需无空格引号且拼出的库名 ≤63 字符（Django 对 sqlite 也查），当前 ${E2E_BASE}`)
}
const log = (...a) => console.log('[pool]', ...a)

const ARGS = parseArgs(process.argv.slice(2), {
  slots: 'auto', 'timeout-min': '25', 'only-slot': undefined, 'dry-run': false, 'keep-slots': false,
})
if (ARGS.unknown.length) {
  console.error(`[pool] 未知参数：${ARGS.unknown.join(' ')} —— 拒绝启动。拼错的开关不能当成没写（--slots=1 被忽略过一次，等于偷偷改了并行度）`)
  process.exit(2)
}
const bare = (p) => p.replace(/^e2e[\\/]/, '')
const FILES = ARGS.files.map(bare)

const netBlock = {}
const taken = (port) => netBlock[port] === true

/** 仓库根 media 的文件总数 —— 模板/slot 操作前后必须相等（那条重定向通路会整目录搬走） */
function repoMediaCount() {
  const root = path.join(ROOT, 'media')
  if (!fs.existsSync(root)) return -1
  let n = 0
  const walk = (d) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) e.isDirectory() ? walk(path.join(d, e.name)) : n++ }
  walk(root)
  return n
}

function dj(args, env) {
  return execFileSync(PY, ['manage.py', ...args], {
    cwd: ROOT, env: { ...env, PYTHONIOENCODING: 'utf-8' }, encoding: 'utf-8', timeout: 900_000, maxBuffer: 128e6,
  })
}

/** 模板：库 + 种子 media 全在短基址下。配置文件钉的是**仓库根** ⇒ 导入期重定向是空操作 */
function buildTemplate() {
  const before = repoMediaCount()
  fs.mkdirSync(path.join(TEMPLATE, 'temp'), { recursive: true })
  const cfg = path.join(TEMPLATE, 'system-config.json')
  fs.writeFileSync(cfg, JSON.stringify({ data_dir: ROOT }), 'utf-8')
  const env = {
    ...process.env, DJANGO_SETTINGS_MODULE: 'config.settings.e2e_slot', LQDP_E2E_SLOT_DIR: TEMPLATE,
    LQDP_SYSTEM_CONFIG_FILE: cfg, SECRET_KEY: 'e2e-template-not-used',
  }
  const t0 = Date.now()
  dj(['migrate', '--noinput'], env)
  dj(['seed_users'], env)
  dj(['seed_test_data', '--refresh'], env)
  // WAL：只拷主文件会丢 -wal 里的内容 ⇒ 先 TRUNCATE checkpoint 落盘，再清 sidecar
  dj(['shell', '-c', "from django.db import connection as c; c.cursor().execute('PRAGMA wal_checkpoint(TRUNCATE)'); print('ok')"], env)
  for (const s of ['-wal', '-shm', '-journal']) { const p = path.join(TEMPLATE, 'db.sqlite3' + s); if (fs.existsSync(p)) fs.rmSync(p) }
  const after = repoMediaCount()
  if (after !== before) throw new Error(`仓库根 media 文件数变了 ${before}→${after} —— 立即停止，别继续起 slot`)
  log(`模板就绪 ${((Date.now() - t0) / 1000).toFixed(1)}s → ${TEMPLATE}（仓库根 media 仍为 ${after} 文件）`)
}

/** 每 slot：新建自己的目录 → 拷库 → 硬链镜像 media → 写 config → 写 slot.json */
function prepareSlot(m) {
  fs.rmSync(m.dataDir, { recursive: true, force: true })   // 只删本次 RUN_ID 下自己造的目录
  for (const dir of [m.tempDir, m.authDir, m.downloadsDir, m.blobDir, path.dirname(m.mediaDir),
    path.dirname(m.jsonOut), path.dirname(m.logFile)]) fs.mkdirSync(dir, { recursive: true })
  fs.copyFileSync(m.templateDbPath, m.dbPath)
  const mirror = (src, rel = '') => {
    for (const e of fs.readdirSync(src, { withFileTypes: true })) {
      const from = path.join(src, e.name), to = path.join(m.mediaDir, rel, e.name)
      if (e.isDirectory()) { fs.mkdirSync(to, { recursive: true }); mirror(from, path.join(rel, e.name)) }
      else fs.linkSync(from, to)   // 硬链：不占磁盘、删除只摘本 slot 的目录项
    }
  }
  fs.mkdirSync(m.mediaDir, { recursive: true })
  if (fs.existsSync(m.templateMediaDir)) mirror(m.templateMediaDir)
  fs.writeFileSync(m.systemConfigFile, JSON.stringify({ data_dir: ROOT }), 'utf-8')
  fs.writeFileSync(m.slotFile, JSON.stringify(m, null, 2), 'utf-8')
}

/**
 * 给 LPT 定权的 per-file 通过时长 + 那份数据的单价。
 * 优先串行 results.json（无争用）；只有 pool 产物时用 merged.json，并把它含争用的单价带回去，
 * 交给 normalizeTotalMs 折回串行等价量 —— 否则 autoSlots 会顺着「争用抬高单价」越开越多 slot。
 */
function latestDurations() {
  const base = path.join(ROOT, 'tasks', 'e2e-nightly')
  if (!fs.existsSync(base)) return { byFile: {}, perSpecMs: 0 }
  const dirs = fs.readdirSync(base).filter((d) => /^\d{4}-\d{2}-\d{2}/.test(d)).sort().reverse()
  for (const d of dirs) {
    for (const name of ['merged.json', 'results.json']) {
      const p = path.join(base, d, name)
      if (!fs.existsSync(p)) continue
      try {
        const j = JSON.parse(fs.readFileSync(p, 'utf-8'))
        if (name === 'merged.json' && j.files && Object.keys(j.files).length) {
          return { byFile: j.files, perSpecMs: j.perSpecMs ?? 0 }
        }
        const out = {}
        let passMs = 0, passCount = 0
        const walk = (s) => {
          for (const x of s.suites ?? []) walk(x)
          for (const sp of s.specs ?? []) {
            let ms = 0
            for (const t of realTests(sp)) for (const r of t.results ?? []) if (r.status === 'passed') { ms += r.duration; passCount++; passMs += r.duration }
            if (ms) out[sp.file] = (out[sp.file] ?? 0) + ms
          }
        }
        for (const s of j.suites ?? []) walk(s)
        if (Object.keys(out).length) return { byFile: out, perSpecMs: passCount ? passMs / passCount : 0 }
      } catch { /* 坏 JSON 就往下找一轮 */ }
    }
  }
  return { byFile: {}, perSpecMs: 0 }
}

function allFiles() {
  const out = captureTool('npx', ['playwright', 'test', '--list', '--reporter=json'],
    { cwd: FRONTEND, encoding: 'utf-8', maxBuffer: 128e6 })
  const j = JSON.parse(out.slice(out.indexOf('{')))
  const files = new Set()
  const walk = (s) => {
    for (const x of s.suites ?? []) walk(x)
    // fixtures/ 下的 auth.setup 属于 setup project，每个 slot 进程自己会跑；
    // 把它当业务文件分进桶只会污染分区（实测 slot2 因此多摊了一个「文件」）
    for (const sp of s.specs ?? []) if (sp.file && !sp.file.startsWith('fixtures/')) files.add(sp.file)
  }
  for (const s of j.suites ?? []) walk(s)
  return [...files]
}

function parseSlots(raw, totalMs) {
  if (raw === undefined || raw === 'auto') return autoSlots(totalMs)
  const n = Number(raw)
  if (!Number.isInteger(n) || n < 1) throw new Error(`--slots 需为 ≥1 整数或 auto，收到 ${raw}`)
  return Math.min(n, MAX_SLOTS)
}

async function prefetchPorts() {
  const ports = []
  for (let i = 0; i < PORT_SPAN; i++) ports.push(SLOT_BACKEND_BASE + i, SLOT_FRONTEND_BASE + i)
  await Promise.all([...new Set(ports)].map(async (p) => {
    netBlock[p] = await new Promise((res) => {
      const s = net.connect(p, '127.0.0.1')
      s.setTimeout(150)
      s.on('connect', () => { s.destroy(); res(true) })
      s.on('error', () => res(false))
      s.on('timeout', () => { s.destroy(); res(false) })
    })
  }))
}

function runSlot(m, files, timeoutMs, aliveFlags) {
  const out = fs.openSync(m.logFile, 'w')
  // reporter 与输出路径由 playwright.config 在 slot 模式下给出（blob/json 的目录只能走 reporter 选项）
  const args = ['playwright', 'test', ...files.map((f) => assertSafeRelPath(`e2e/${f}`)), '--workers=1', ...PW_EXTRA]
  fs.writeSync(out, `$ cmd /c npx ${args.join(' ')}\n(cwd=${FRONTEND}) (ports ${m.backendPort}/${m.frontendPort}) (slotDir=${m.dataDir})\n\n`)
  return new Promise((resolve) => {
    const child = spawn(CMD, ['/c', 'npx', ...args], {
      cwd: FRONTEND, shell: false, stdio: ['ignore', out, out],
      env: { ...slotEnv(m, process.env), E2E_SKIP_BUILD: '1' },
    })
    const killer = setTimeout(() => { try { child.kill('SIGKILL') } catch { /* 已退出 */ } }, timeoutMs)
    child.on('close', (code) => { clearTimeout(killer); fs.closeSync(out); if (aliveFlags) aliveFlags.set(m.index, false); resolve(code ?? 1) })
  })
}

/**
 * 一条 spec 在本进程里真正跑起来的非 setup 测试。
 * 注意：运行期 JSON 的 spec 条目**没有** projectIds 字段（那是 --list 才有的），
 * 用它过滤会一个都不排除 ⇒ 每 slot 多算 2 条 auth.setup（实测把 386 报成 388/392）。
 */
function realTests(sp) {
  return (sp.tests ?? []).filter((t) => t.projectId !== 'setup')
}

function statsOf(jsonPath) {
  if (!fs.existsSync(jsonPath)) return null
  let j
  try { j = JSON.parse(fs.readFileSync(jsonPath, 'utf-8')) } catch { return null }
  let specs = 0, passCount = 0, passMs = 0, refusedCount = 0
  const files = {}
  const redSet = new Set()
  const countRefused = (t) => {
    for (const r of t.results ?? []) for (const e of r.errors ?? []) {
      if (/ERR_CONNECTION_REFUSED|ECONNREFUSED|ERR_CONNECTION_RESET/.test(String(e.message || ''))) refusedCount++
    }
  }
  const walk = (s) => {
    for (const x of s.suites ?? []) walk(x)
    for (const sp of s.specs ?? []) {
      const tests = realTests(sp)
      if (!tests.length) continue          // 纯 setup project 的 spec 整条不计
      specs++
      for (const t of tests) {
        countRefused(t)
        for (const r of t.results ?? []) if (r.status === 'passed') {
          passCount++; passMs += r.duration
          files[sp.file] = (files[sp.file] ?? 0) + r.duration
        }
      }
      // 「所有 attempt 都没过」才算红文件（重试后过的算 flaky，交给 stats.flaky）
      if (tests.some((t) => (t.results ?? []).length
        && t.results.at(-1).status === 'failed'
        && !t.results.some((r) => r.status === 'passed'))) redSet.add(sp.file)
    }
  }
  for (const s of j.suites ?? []) walk(s)
  return { specs, passCount, passMs, wallMs: j.stats?.duration ?? 0, stats: j.stats ?? {}, files, refusedCount, redFiles: [...redSet] }
}

/**
 * 服务存活看门狗：崩池轮的教训就是「后端 12:44:19 静音，没人知道，直到读完 155 条红」。
 * 每 20s 探一次每个 slot 的 backend/preview 端口，掉线就当场记下时刻。
 */
function probePortOpen(port) {
  return new Promise((res) => {
    const s = net.connect(port, '127.0.0.1')
    s.setTimeout(LIVENESS_TIMEOUT_MS)
    s.on('connect', () => { s.destroy(); res(true) })
    s.on('error', () => res(false))
    s.on('timeout', () => { s.destroy(); res(false) })
  })
}

/**
 * 掉线时刻的进程现场。
 *
 * 崩池轮「为什么死」定不下来，缺的不是时刻（看门狗给得出）而是**那一刻的进程表**：
 * 事后 tasklist 只能看到幸存者，看不到是谁把 preview 的 node 摘掉的、它的父进程是谁。
 * 这里在判死的当场落一份 node/python/cmd 的 PID+父 PID+创建时刻，加上该端口的 netstat 状态。
 * 采集本身不是判据，失败就打一行日志，绝不影响判定与退出码。
 */
function captureDeathSnapshot(logFile, label, port) {
  const file = path.join(path.dirname(logFile), `dead-${label}.txt`)
  const parts = [`# 掉线现场 ${label} @ ${new Date().toISOString()}`]
  const ps = "Get-CimInstance Win32_Process -Filter \"Name='node.exe' OR Name='python.exe' OR Name='cmd.exe'\"" +
    ' | Select-Object ProcessId,ParentProcessId,CreationDate,Name | ConvertTo-Csv -NoTypeInformation'
  try {
    parts.push('===== 进程表（node/python/cmd） =====',
      execFileSync('powershell', ['-NoProfile', '-Command', ps], { encoding: 'utf-8', timeout: 20_000 }).trim())
  } catch (e) { parts.push(`===== 进程表采集失败: ${e.message} =====`) }
  try {
    const all = execFileSync('netstat', ['-ano'], { encoding: 'utf-8', timeout: 20_000 })
    const hits = all.split('\n').filter((l) => l.includes(`:${port}`))
    parts.push(`===== netstat 含 :${port} 的行 =====`, hits.join('\n').trim() || `(无任何行 ⇒ 端口连 TIME_WAIT 都没留)`)
  } catch (e) { parts.push(`===== netstat 采集失败: ${e.message} =====`) }
  try { fs.writeFileSync(file, parts.join('\n'), 'utf-8') } catch (e) { log(`掉线现场写入失败: ${e.message}`) }
  return file
}

/**
 * 服务存活看门狗。两条防误报：单次探测不算数（满载时 150ms 会假超时），
 * 且子进程已经正常退出的 slot 不再判死（端口关闭是收尾不是事故）。
 */
function startLivenessWatch(manifests, aliveFlags) {
  const state = new Map()
  for (const m of manifests) {
    state.set(`slot${m.index}:backend:${m.backendPort}`, { misses: 0, dead: false, m, kind: 'backend' })
    state.set(`slot${m.index}:preview:${m.frontendPort}`, { misses: 0, dead: false, m, kind: 'preview' })
  }
  const t0 = Date.now()
  const timer = setInterval(async () => {
    for (const [key, st] of state) {
      if (st.dead || !aliveFlags.get(st.m.index)) continue
      const port = Number(key.split(':').at(-1))
      st.state = nextLivenessState(st.state ?? { misses: 0, dead: false }, await probePortOpen(port), true)
      if (st.state.dead) {
        st.dead = true
        const label = `slot${st.m.index}-${st.kind}-${port}`
        const childAlive = aliveFlags.get(st.m.index)
        log(`⏱ ${label} 连续 ${LIVENESS_MISSES} 次探不到，开跑后 ${((Date.now() - t0) / 1000).toFixed(0)}s`
          + `（该 slot 的 playwright 子进程${childAlive ? '仍在跑 ⇒ 红是环境造成的' : '已退出 ⇒ 端口关闭是收尾'}）`)
        log(`   现场 → ${captureDeathSnapshot(st.m.logFile, label, port)}`)
      }
    }
  }, 20_000)
  if (timer.unref) timer.unref()
  return () => clearInterval(timer)
}

/**
 * 红文件自动复跑判级：每个红文件独占一个 slot 重跑一遍（一批最多 MAX_SLOTS 个，分批串行）。
 * 判据与理由见 pool-core.classifyReds —— 门禁仍要求零真红，但「一隔离就绿」的负载抖动不该拦轮子。
 */
async function runRecheck(redFiles) {
  const out = []
  for (let start = 0; start < redFiles.length; start += MAX_SLOTS) {
    const batch = redFiles.slice(start, start + MAX_SLOTS)
    await prefetchPorts()
    const ports = allocatePortBlock(batch.length, taken)
    const tag = `${RUN_ID}-recheck${Math.floor(start / MAX_SLOTS)}`
    const manifests = ports.map((p, i) => buildSlotManifest({
      index: i, ports: p, slotRoot: path.join(SLOTS_ROOT, tag, `slot${i}`), templateRoot: TEMPLATE,
      redisDb: 30 + i, secretKey: `e2e-recheck-${i}-${RUN_ID}-padded-to-32bytes`,
      blobRoot: path.join(SLOTS_ROOT, tag, 'blob'), evidenceRoot: path.join(SLOTS_ROOT, tag),
    }))
    manifests.forEach(prepareSlot)
    const aliveFlags = new Map(manifests.map((m) => [m.index, true]))
    const stopWatch = startLivenessWatch(manifests, aliveFlags)
    await Promise.all(manifests.map((m, i) => runSlot(m, [batch[i]], 10 * 60_000, aliveFlags)))
    stopWatch()
    manifests.forEach((m, i) => {
      const file = batch[i]
      const st = statsOf(m.jsonOut)
      if (!st) { out.push({ file, red: true, infra: true, specs: 0 }); log(`↻ ${file} 复跑没出 JSON ⇒ 悬而未决（保守算红）`); return }
      const infra = classifySlotHealth({
        specs: st.specs, unexpected: st.stats?.unexpected ?? 0, refusedCount: st.refusedCount,
      }) === 'INFRA'
      const red = st.redFiles.includes(file)
      out.push({ file, red, infra, specs: st.specs })
      log(`↻ ${file} 独占 slot${i} 复跑：${infra ? '该轮崩池 ⇒ 悬而未决' : red ? '仍红 ⇒ 真红' : '绿 ⇒ 判为负载抖动'}`)
    })
    manifests.forEach((m) => fs.rmSync(m.dataDir, { recursive: true, force: true }))
  }
  return out
}

async function main() {
  await prefetchPorts()
  const { byFile: durations, perSpecMs: basisPerSpec } = latestDurations()
  const files = FILES.length ? FILES : allFiles()
  const rawTotalMs = files.reduce((a, f) => a + (durations[f] ?? 0), 0)
  // 分桶只看相对权重（缩放不影响），slot 数看折算后的串行等价总量
  const totalMs = normalizeTotalMs(rawTotalMs, basisPerSpec)
  const buckets = partitionFiles(files, durations, parseSlots(ARGS.slots, totalMs)).filter((b) => b.length)
  log(`文件 ${files.length} · 加权总量 ${(totalMs / 1000).toFixed(0)}s`
    + (basisPerSpec ? `（原始 ${(rawTotalMs / 1000).toFixed(0)}s ÷ 争用系数 ${(basisPerSpec / SERIAL_REF_PER_SPEC_MS).toFixed(2)}）` : '')
    + ` · 计划 slot ${buckets.length}`
    + (Object.keys(durations).length ? '' : '（无夜跑 JSON ⇒ 分区未加权）'))
  if (ARGS.dryRun) {
    buckets.forEach((b, i) => log(`slot${i}: ${b.length} 文件 · ${(b.reduce((a, f) => a + (durations[f] ?? 0), 0) / 1000).toFixed(0)}s`))
    return 0
  }

  buildTemplate()
  // 构建输出必须接住：失败时 stdio:'ignore' 会让错误一个字都不留（实测撞过一次无从判因）
  const built = runTool('npm', ['run', 'build'], { cwd: FRONTEND, encoding: 'utf-8' })
  if (built.status !== 0) {
    const detail = `${built.stderr || ''}${built.stdout || ''}`.split('\n').filter(Boolean).slice(-12).join('\n  ')
    throw new Error(`前端构建失败（exit=${built.status}）：\n  ${detail || '无输出'}`)
  }

  const ports = allocatePortBlock(buckets.length, taken)
  const blobRoot = path.join(SLOTS_ROOT, RUN_ID, 'blob')   // 共享：merge-reports 只接受一个目录
  const evidenceRoot = path.join(SLOTS_ROOT, RUN_ID)       // 日志与 JSON 住在 slot 目录之外
  // 密钥要 ≥32 字节：PyJWT 对 HMAC-SHA256 短密钥**每次签发/校验都打一条 InsecureKeyLengthWarning**，
  // 实测每条用例刷 4 行进 run.log —— 取证日志被噪声淹没（而 run.log 正是崩池轮唯一的现场）。
  const manifests = ports.map((p, i) => buildSlotManifest({
    index: i, ports: p, slotRoot: path.join(SLOTS_ROOT, RUN_ID, `slot${i}`), templateRoot: TEMPLATE,
    redisDb: 12 + i, secretKey: `e2e-slot-${i}-${RUN_ID}-padded-to-32bytes`, blobRoot, evidenceRoot,
  }))
  manifests.forEach(prepareSlot)

  const only = ARGS.onlySlot === undefined ? null : Number(ARGS.onlySlot)
  const timeoutMs = Number(ARGS['timeout-min']) * 60_000
  const started = Date.now()
  const aliveFlags = new Map(manifests.map((m) => [m.index, true]))
  const stopWatch = startLivenessWatch(manifests, aliveFlags)
  const codes = await Promise.all(manifests.map((m, i) =>
    (only !== null && Number(only) !== i) ? Promise.resolve(0) : runSlot(m, buckets[i], timeoutMs, aliveFlags)))
  stopWatch()
  const spanMs = Date.now() - started

  const perSlot = manifests.map((m, i) => ({ slot: i, ...(statsOf(m.jsonOut) ?? { missing: true }) }))
  const reports = perSlot.filter((r) => !r.missing)
  const health = perSlot.map((r) => (r.missing
    ? { slot: r.slot, specs: 0, unexpected: 0, refusedCount: 5 }      // 连 JSON 都没有 = 直接 INFRA
    : { slot: r.slot, specs: r.specs, unexpected: r.stats?.unexpected ?? 0, refusedCount: r.refusedCount ?? 0 }))
  const { verdict, infraSlots } = roundVerdict(health)
  const merged = mergeRunStats(reports)

  // 红文件自动复跑判级（只有整轮不是崩池时才做 —— 崩池轮的复跑同样不可信）
  let recheck = null
  if (verdict === 'MEASURED') {
    const redFiles = [...new Set(perSlot.flatMap((r) => (r.missing ? [] : r.redFiles ?? [])))].sort()
    if (redFiles.length) {
      log(`${redFiles.length} 个红文件 ⇒ 逐文件独占 slot 复跑判级`)
      const results = await runRecheck(redFiles)
      recheck = { redFiles, results, ...classifyReds(redFiles, results) }
    }
  }
  merged.files = reports.reduce((acc, r) => {
    for (const [f, ms] of Object.entries(r.files)) acc[f] = (acc[f] ?? 0) + ms
    return acc
  }, {})
  merged.wallMs = spanMs
  merged.slotsPlanned = buckets.length
  merged.runId = RUN_ID
  merged.verdict = verdict
  merged.infraSlots = infraSlots
  merged.health = health
  merged.recheck = recheck
  if (only !== null) merged.partial = true
  const outDir = process.env.LQDP_E2E_OUTDIR || path.join(ROOT, 'tasks', 'e2e-pool', 'latest')
  fs.mkdirSync(outDir, { recursive: true })
  fs.writeFileSync(path.join(outDir, 'merged.json'), JSON.stringify(merged, null, 2), 'utf-8')

  try {
    const mergedReport = runTool('npx', ['playwright', 'merge-reports', blobRoot, '--reporter=html'],
      { cwd: FRONTEND, stdio: 'inherit' })
    if (mergedReport.status !== 0) throw new Error(`exit=${mergedReport.status}`)
  } catch (e) { log('HTML 合并失败（统计不受影响）:', e.message) }

  codes.forEach((c, i) => {
    if (c === 0) return
    // Playwright 有用例失败也是 exit 1 ⇒ 有 JSON 就只是「有红」，没 JSON 才是崩池/INFRA
    const infra = !fs.existsSync(manifests[i].jsonOut)
    log(`slot${i} EXIT=${c} ${infra ? 'INFRA：没产出 JSON，看日志' : '（有用例红，JSON 在）'}→ ${manifests[i].logFile}`)
  })
  log(`用例 ${merged.specs} · 墙钟 ${(spanMs / 60000).toFixed(1)}min · 单价 ${(merged.perSpecMs / 1000).toFixed(2)}s/例`
    + ` · 效率 ${merged.efficiency.toFixed(2)}（目标 ≥${(0.7 * buckets.length).toFixed(1)}）`
    + ` · unexpected ${merged.stats.unexpected} · flaky ${merged.stats.flaky} · skipped ${merged.stats.skipped}`)
  log(`结论 ${verdict}` + (infraSlots.length
    ? ` —— slot${infraSlots.join('/slot')} 带连接级错误或红占比过半，指标不可信，别当退化读；现场已保留` : ''))
  if (recheck) {
    log(`复跑判级：真红 ${recheck.confirmed.length} · 负载抖动 ${recheck.loadFlakes.length} · 悬而未决 ${recheck.unresolved.length}`)
    if (recheck.loadFlakes.length) log(`  判为负载抖动（记 flaky，不拦门禁）：${recheck.loadFlakes.join(' ')}`)
    if (recheck.unresolved.length) log(`  悬而未决（复跑崩池或没跑上，保守算红）：${recheck.unresolved.join(' ')}`)
  }
  log(`merged.json → ${path.join(outDir, 'merged.json')}`)
  // INFRA 轮不清现场：崩过一次就知道清掉日志有多误事（证据本身已在 slot 目录之外）
  if (ARGS.keepSlots || verdict !== 'MEASURED') log(`slot 镜像保留在 ${path.join(SLOTS_ROOT, RUN_ID)}`)
  else manifests.forEach((m) => fs.rmSync(m.dataDir, { recursive: true, force: true }))
  if (verdict !== 'MEASURED') return 3
  // 有复跑判级时以它为准：子进程 exit 1 可能只是那些「一隔离就绿」的抖动
  if (recheck) return recheck.countsBlock ? 1 : 0
  return codes.some((c) => c !== 0) ? 1 : (merged.stats.unexpected > 0 ? 1 : 0)
}

main().then((code) => process.exit(code)).catch((e) => { console.error('[pool] 失败:', e.message); process.exit(1) })
