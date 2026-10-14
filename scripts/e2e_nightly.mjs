#!/usr/bin/env node
/**
 * e2e_nightly — 每日全量兜底轮：干净环境跑 T1+T2+T3 全套，写时间序列，报退化。
 *
 * 用法：
 *   node scripts/e2e_nightly.mjs              # 前置通过则跑，否则 SKIPPED（exit 0）
 *   node scripts/e2e_nightly.mjs --dry-run    # 只跑前置检查并打印计划
 *   node scripts/e2e_nightly.mjs --allow-dirty # 跳过「工作区必须干净」这一门
 *
 * 硬约束（为什么这么设计见 docs/superpowers/specs/ 同名设计文档）：
 * - 杀进程 / git 写操作 / 改 docs/tasks/* 一律不做：本脚本会在无人值守时被独立
 *   会话执行，与别人的会话共享同一份工作区、同一颗 8000 端口和同一个 db.sqlite3。
 * - 前置不过一律 SKIPPED + exit 0。跳过不是失败；把跳过报成失败会让兜底轮失去可信度。
 * - CI=1 强制自起自收：reuseExistingServer=false 才不会复用上一轮遗留的旧包（假绿）。
 */
import { execFileSync, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const FRONTEND = path.join(ROOT, 'frontend')
const OUT_ROOT = path.join(ROOT, 'tasks', 'e2e-nightly')
const LOCK = path.join(OUT_ROOT, 'e2e-nightly.lock')

// 退化阈值：任一命中即在 LATEST.md 顶部打 ⚠ DEGRADED。改阈值=改代码，不留口头约定。
const THRESHOLDS = {
  // 「变慢」的信号是**单价**（每例平均执行时长，只计通过的用例），不是墙钟 —— 套件变大由 specs 那条单独报。
  // 2026-10-13 实测两次：删掉被吞掉的等待**之前** 5.21 s/例（385 例 / 37.1 min），
  // **之后** 2.78 s/例（21.9 min）。此处按新基线留 ~26% 余量。
  // 旧值 8 000 是照 6.29 s/例定的 —— 提速后它比实测慢 2.9 倍，等于这条判据失效。
  perSpecMs: 3_500,
  // 墙钟只当**挂死探测器**（CI=1 强制 workers=1，385 例实测 21.9 min）。
  // 旧值 75 min 是照「天然要 43 min」的**未实测估计**定的，那个估计错了 2 倍。
  wallMs: 30 * 60_000,
  specs: 450, // 用例数（2026-10-13 快照 385）
  flakes: 5, // 重试后才过的用例数
}

/**
 * 基础设施塌方判定：连接级错误占比过高时，这一轮的**所有指标都不可信**，
 * 尤其不能拿它去比退化阈值。
 *
 * 为什么非有不可（2026-10-14 第六轮实证）：Playwright 自起的 `vite preview` 在第 13 次
 * attempt 就退出，于是 1099 次 attempt 里 923 次是 `ERR_CONNECTION_REFUSED`、只 23 次通过。
 * 而账本当时记的是 `FAILED · 21.2min · 3.04s/例 · flaky 0` —— 单价只计通过用例，
 * 秒失败的不进分母（这是 10-13 修对的口径），于是 23 个样本算出**比阈值还好看**的单价，
 * 一条环境塌方被记成"普通失败 + 性能正常"。无人值守的 cron 第一晚就会被这种数字骗到。
 */
const INFRA_RE =
  /ERR_CONNECTION_REFUSED|ERR_CONNECTION_RESET|ERR_CONNECTION_CLOSED|ERR_EMPTY_RESPONSE|ERR_NETWORK_CHANGED|ERR_ADDRESS_UNREACHABLE|ERR_TIMED_OUT|ECONNREFUSED|ECONNRESET/i
const INFRA = { minCount: 20, minShare: 0.1 }

const args = process.argv.slice(2)
const DRY = args.includes('--dry-run')
const ALLOW_DIRTY = args.includes('--allow-dirty')

// 只复盘既有产物，不开浏览器：改阈值/改单价口径时用这条验证，
// 不该为确认一个公式再花 40 分钟跑全量。
const REPORT_ONLY = args.find((a, i) => args[i - 1] === '--report-only')
if (REPORT_ONLY) {
  const rep = parseReport(path.resolve(REPORT_ONLY))
  const b = breach(rep)
  console.log(
    `specs=${rep.specs} 墙钟=${(rep.wallMs / 60000).toFixed(1)}min ` +
      `单价=${(rep.perSpecMs / 1000).toFixed(2)}s/例 ` +
      `flaky=${rep.stats?.flaky} unexpected=${rep.stats?.unexpected} skipped=${rep.stats?.skipped} ` +
      `拒连=${rep.infraCount}/${rep.attempts}`,
  )
  if (rep.voidInfra) console.log(`判 VOID(infra)：连接级错误占 ${(rep.infraShare * 100).toFixed(1)}%，本轮指标不可信`)
  else console.log(b.length ? `判 DEGRADED：${b.join('；')}` : '不判 DEGRADED')
  for (const [f, ms] of rep.top.slice(0, 5)) console.log(`  ${(ms / 1000).toFixed(0).padStart(5)}s  ${f}`)
  process.exit(0)
}

function git(...a) {
  return execFileSync('git', a, { cwd: ROOT, encoding: 'utf-8' }).trim()
}

function portsBusy() {
  // 要探的是「本轮实际会用到的端口」，不是写死的 8000/3000：
  // playwright.config.ts 与 vite.config.ts 现在同读 E2E_PORT / E2E_FRONTEND_PORT，
  // 端口值的来源只能有一份，否则设了变量的那轮会探错端口（未设时与旧行为逐字一致）。
  const wanted = new Set([process.env.E2E_PORT || '8000', process.env.E2E_FRONTEND_PORT || '3000'])
  try {
    const out = execFileSync('netstat', ['-ano'], { encoding: 'utf-8' })
    const busy = []
    for (const line of out.split('\n')) {
      const m = /^\s*TCP\s+\S+:(\d{4})\s+\S+\s+(LISTENING)/i.exec(line)
      if (m && wanted.has(m[1])) busy.push(`${m[1]}(${m[2].toLowerCase()})`)
    }
    return [...new Set(busy)]
  } catch (e) {
    return [`netstat 读取失败: ${e.message}`] // 读不到就当占用，宁跳过不误跑
  }
}

function precheck() {
  const busy = portsBusy()
  if (busy.length) return `端口被占用 ${busy.join(', ')} —— 另一会话在服务，跳过而不是抢它的端口`
  if (fs.existsSync(LOCK)) {
    const ageSec = (Date.now() - fs.statSync(LOCK).mtimeMs) / 1000
    if (ageSec < 4 * 3600) return `锁 ${path.relative(ROOT, LOCK)} 存在（${Math.round(ageSec / 60)} 分钟前）—— 已有轮次在跑`
    fs.rmSync(LOCK, { force: true }) // 陈旧锁（>4h）视为上一轮崩溃残留
  }
  if (!ALLOW_DIRTY) {
    // 只查**被跟踪文件的未提交改动**：这条门防的是"别人的在制品被算到本轮账上"
    // （2026-10-14 实测两次：另一会话在夜跑后端套件跑到一半时改
    // test/backend/test_browse_api.py，制造出一条自相矛盾的假失败，而该文件单独重跑 31 例全过）。
    // 未跟踪目录（如工具自己的 .qoder-credits/）改不动测试结果，
    // 却会迫使运维加 --allow-dirty 绕过整条门 —— 那是净损失，所以按 untracked=no 判。
    const dirty = git('status', '--porcelain', '--untracked-files=no').split('\n').filter(Boolean)
    if (dirty.length) return `工作区有 ${dirty.length} 项未提交改动 —— 全量结果会算到本不归属它的会话头上`
  }
  return null
}

function backendLabels() {
  const apps = fs
    .readdirSync(path.join(ROOT, 'apps'), { withFileTypes: true })
    .filter((e) => e.isDirectory() && !e.name.startsWith('__'))
    .map((e) => `apps.${e.name}`)
  return ['test.backend', ...apps]
}

function run(cmd, env = {}, cwd = FRONTEND) {
  console.log(`$ ${cmd}`)
  if (DRY) return { status: 0, output: '' }
  const r = spawnSync(cmd, { cwd, encoding: 'utf-8', shell: true, env: { ...process.env, ...env } })
  return { status: r.status ?? 1, output: `${r.stdout ?? ''}\n${r.stderr ?? ''}` }
}

/** Playwright JSON reporter → { 墙钟, 计数, 按 spec 文件累计耗时 top, 基础设施塌方判定 }。 */
function parseReport(file) {
  const j = JSON.parse(fs.readFileSync(file, 'utf-8'))
  const perFile = new Map()
  let specs = 0
  let passMs = 0
  let passCount = 0
  let attempts = 0
  let infraCount = 0
  const walk = (node) => {
    for (const s of node.specs ?? []) {
      specs += 1
      const results = (s.tests ?? []).flatMap((t) => t.results ?? [])
      const ms = results.reduce((a, r) => a + (r.duration ?? 0), 0)
      // 单价只按**跑完并通过**的用例计：连不上、秒失败的那些时长≈0，
      // 把它们算进分母会让"整片崩溃"看起来比健康轮更快（2026-10-13 首跑实测 4.48 < 6.29）。
      // 但这条修法有个反面：通过样本极少时单价依然可能好看 → 必须配下面的 INFRA 判定。
      for (const r of results) {
        attempts += 1
        if (r.status === 'passed') { passMs += r.duration ?? 0; passCount += 1 }
        const msg = r.error?.message ?? ''
        if (INFRA_RE.test(msg)) infraCount += 1
      }
      const key = s.file ?? '(unknown)'
      perFile.set(key, (perFile.get(key) ?? 0) + ms)
    }
    for (const c of node.suites ?? []) walk(c)
  }
  for (const s of j.suites ?? []) walk(s)
  const top = [...perFile.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10)
  const infraShare = attempts ? infraCount / attempts : 0
  // 实测：墙钟在 stats.duration，顶层 duration 是 undefined。
  return {
    stats: j.stats ?? {}, specs, wallMs: j.stats?.duration ?? j.duration ?? 0,
    // 2026-10-13 首跑：255 例通过 / 26.7 min → 6.29 s/例（workers=1）。分母为 0 时不判退化。
    perSpecMs: passCount ? passMs / passCount : 0,
    attempts, passCount, infraCount, infraShare,
    // 既要有绝对量下限（别因一两条偶发拒连就作废），也要占比门槛
    voidInfra: infraCount >= INFRA.minCount && infraShare >= INFRA.minShare,
    top,
  }
}

function breach(rep) {
  if (rep.voidInfra) return []   // 这一轮什么都不判：指标不可信，见 INFRA 注释
  const b = []
  if (rep.perSpecMs > THRESHOLDS.perSpecMs) {
    b.push(`单价 ${(rep.perSpecMs / 1000).toFixed(2)}s/例 > ${THRESHOLDS.perSpecMs / 1000}s/例`)
  }
  if (rep.wallMs > THRESHOLDS.wallMs) b.push(`墙钟 ${(rep.wallMs / 60000).toFixed(1)}min > ${THRESHOLDS.wallMs / 60000}min（挂死探测）`)
  if (rep.specs > THRESHOLDS.specs) b.push(`用例数 ${rep.specs} > ${THRESHOLDS.specs}`)
  if ((rep.stats?.flaky ?? 0) > THRESHOLDS.flakes) b.push(`flake ${rep.stats.flaky} > ${THRESHOLDS.flakes}`)
  return b
}

const now = new Date()
const today = [
  now.getFullYear(),
  String(now.getMonth() + 1).padStart(2, '0'),
  String(now.getDate()).padStart(2, '0'),
].join('-')
// 目录带**本地时分**：产物目录原先只按日期命名，同一天跑第二轮会静默覆盖第一轮的
// results.json + run.log（2026-10-14 实测：第五轮「365 通过 / 1 红」的有效产物被第六轮
// 那场 923 次拒连的塌方整个盖掉，账本里那一行也一起没了）。
const stamp = `${today}-${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}`
const outDir = path.join(OUT_ROOT, stamp)
const jsonFile = path.join(outDir, 'results.json')

fs.mkdirSync(outDir, { recursive: true })
// DRY 只打印计划、什么都不跑，前置门（防的是「真跑时抢别人的端口/工作区」）无意义。
const skip = DRY ? null : precheck()
const series = []

if (skip) {
  console.log(`SKIPPED: ${skip}`)
  series.push({ date: today, stamp, result: 'SKIPPED', reason: skip })
} else {
  fs.writeFileSync(LOCK, `${new Date().toISOString()} pid=${process.pid}\n`)
  try {
    const unit = run('npm run test:unit')
    const py = spawnSync('python', ['-c', 'import pytest'], { cwd: ROOT })
    if (py.status !== 0) {
      console.log('SKIPPED: `python` 无 pytest —— .venv 会缺它并把 import 失败伪装成回归，拒绝在夜间轮里用错解释器')
      series.push({ date: today, stamp, result: 'SKIPPED', reason: 'python 无 pytest' })
    } else {
      const labels = backendLabels()
      const t1 = run(`python manage.py test ${labels.join(' ')}`, { PYTHONIOENCODING: 'utf-8' }, ROOT)
      const t3 = run('npx playwright test --reporter=json,html,list', {
        CI: '1',
        PLAYWRIGHT_JSON_OUTPUT_NAME: jsonFile,
      })
      // 无头作业必须自己留下可归因的现场：webServer 的 stdout/stderr 只在进程内，
      // 不落盘就永远不知道「30 分钟处大面积连不上」是谁把服务杀了（2026-10-13 首跑的教训）。
      if (!DRY) {
        fs.writeFileSync(
          path.join(outDir, 'run.log'),
          `===== python manage.py test（exit=${t1.status}）=====\n${t1.output}\n` +
            `===== npx playwright test（exit=${t3.status}）=====\n${t3.output}\n`,
        )
        console.log(`日志: ${path.relative(ROOT, path.join(outDir, 'run.log'))}`)
      }
      if (DRY) {
        series.push({ date: today, result: 'DRY-RUN', breaches: [] })
      } else if (!fs.existsSync(jsonFile)) {
        console.log(`FAILED: playwright 未产出 ${path.relative(ROOT, jsonFile)}（exit=${t3.status}）`)
        series.push({ date: today, stamp, result: 'FAILED', reason: '无 JSON 产物', breaches: [] })
      } else {
        const rep = parseReport(jsonFile)
        const breaches = breach(rep)
        console.log(
          `T3: ${rep.specs} 例 / ${(rep.wallMs / 60000).toFixed(1)}min | expected=${rep.stats?.expected} unexpected=${rep.stats?.unexpected} flaky=${rep.stats?.flaky} skipped=${rep.stats?.skipped} | 连接级失败 ${rep.infraCount}/${rep.attempts} attempt`,
        )
        for (const [f, ms] of rep.top) console.log(`  ${(ms / 1000).toFixed(1).padStart(7)}s  ${f}`)
        if (rep.voidInfra) {
          // 环境塌方：不评退化、不记单价 —— 这种轮的指标全部不可信，重跑才是结论
          console.log(
            `VOID (infra): ${(rep.infraShare * 100).toFixed(1)}% 的 attempt 是连接级错误 ` +
              `（通过仅 ${rep.passCount}/${rep.specs} 例）—— 服务中途退出之类，` +
              `本轮不计退化、不比单价，**请重跑**（明细见 ${path.relative(ROOT, jsonFile)}）`,
          )
        } else if (breaches.length) {
          console.log(`⚠ DEGRADED: ${breaches.join('; ')}`)
        }
        series.push({
          date: today,
          stamp,
          result: rep.voidInfra
            ? 'VOID-INFRA'
            : (rep.stats?.unexpected ?? 0) > 0 || t1.status || unit.status ? 'FAILED' : 'PASSED',
          breaches: rep.voidInfra ? [] : breaches,
          specs: rep.specs,
          wallMs: rep.wallMs,
          perSpecMs: rep.voidInfra ? null : rep.perSpecMs,
          infraCount: rep.infraCount,
          attempts: rep.attempts,
          stats: rep.stats,
          top: rep.top,
        })
      }
    }
  } finally {
    fs.rmSync(LOCK, { force: true })
  }
}

// DRY 只出计划，不写时间序列（否则假轮次会污染退化判断的曲线）。
if (DRY) {
  console.log('(dry-run：未执行、未写 latest.json/LATEST.md)')
  process.exit(0)
}

// 时间序列：latest.json 保留最近 30 轮，供「越来越慢」这类判断有曲线可看。
const latestFile = path.join(OUT_ROOT, 'latest.json')
let history = []
try {
  history = JSON.parse(fs.readFileSync(latestFile, 'utf-8'))
} catch {}
// 同一天**只合并「跳过」轮次**（它们没跑、留一条就够）。有效轮次一律保留：
// 原先这里是「同一天只留最后一轮」，于是第二次跑会把第一次的账目行静默顶掉
// （2026-10-14 实测：第五轮 365 通过/1 红 那行被第六轮那场塌方盖掉）。
const cur = series[0]
history = [...(Array.isArray(history) ? history : []).filter(
    (h) => h.date !== cur?.date || h.result !== 'SKIPPED',
  ),
  ...series,
].slice(-30)
fs.writeFileSync(latestFile, JSON.stringify(history, null, 2))

const rows = history
  .slice()
  .reverse()
  .map((h) => {
    const when = h.stamp || h.date
    if (h.result === 'SKIPPED') return `| ${when} | SKIPPED | ${h.reason} | — |`
    if (h.result === 'VOID-INFRA')
      return `| ${when} | ❌ VOID (infra) | ${h.infraCount}/${h.attempts} 次 attempt 连接级失败，指标不可信 | 请重跑 |`
    const warn = h.breaches?.length ? '⚠ DEGRADED ' : ''
    if (h.wallMs == null) return `| ${when} | ${warn}${h.result} | ${h.reason ?? '—'} | — |`
    const price = h.perSpecMs == null ? '—' : ` · ${(h.perSpecMs / 1000).toFixed(2)}s/例`
    return `| ${when} | ${warn}${h.result} | ${(h.wallMs / 60000).toFixed(1)}min${price} | ${h.specs} 例 / flaky ${h.stats?.flaky ?? '?'} |`
  })
  .join('\n')

fs.writeFileSync(
  path.join(OUT_ROOT, 'LATEST.md'),
  `# 夜间全量兜底轮（最近 ${history.length} 轮）

阈值：单价 ${THRESHOLDS.perSpecMs / 1000}s/例 · 墙钟 ${THRESHOLDS.wallMs / 60000}min（挂死探测）· 用例 ${THRESHOLDS.specs} · flaky ${THRESHOLDS.flakes}
最近一轮明细：\`tasks/e2e-nightly/${stamp}/\`（results.json + run.log + playwright-report）

| 日期 | 结果 | 墙钟 | 规模 |
|---|---|---|---|
${rows}

> 出现 ⚠ DEGRADED 时：按 docs/superpowers/specs/ 的三层判据，把最慢文件的断言下沉到 T1/T2，
> 或删掉已陈旧的 T0。别靠加大超时来「消红」。
`,
)

const s = series[0]
// VOID-INFRA 也要非零退出：环境塌方是"这轮没结论、需要有人重跑"，不是"没事"。
process.exit(s?.result === 'FAILED' || s?.result === 'VOID-INFRA' ? 1 : 0)
