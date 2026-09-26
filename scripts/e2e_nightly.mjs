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
  wallMs: 35 * 60_000, // 全量墙钟
  specs: 450, // 用例数（2026-09-26 基线 393）
  flakes: 5, // 重试后才过的用例数
}

const args = process.argv.slice(2)
const DRY = args.includes('--dry-run')
const ALLOW_DIRTY = args.includes('--allow-dirty')

function git(...a) {
  return execFileSync('git', a, { cwd: ROOT, encoding: 'utf-8' }).trim()
}

function portsBusy() {
  try {
    const out = execFileSync('netstat', ['-ano'], { encoding: 'utf-8' })
    const busy = []
    for (const line of out.split('\n')) {
      const m = /^\s*TCP\s+\S+:(\d{4})\s+\S+\s+(LISTENING)/i.exec(line)
      if (m && (m[1] === '8000' || m[1] === '3000')) busy.push(`${m[1]}(${m[2].toLowerCase()})`)
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
    const dirty = git('status', '--porcelain').split('\n').filter(Boolean)
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

/** Playwright JSON reporter → { 墙钟, 计数, 按 spec 文件累计耗时 top }。 */
function parseReport(file) {
  const j = JSON.parse(fs.readFileSync(file, 'utf-8'))
  const perFile = new Map()
  let specs = 0
  const walk = (node) => {
    for (const s of node.specs ?? []) {
      specs += 1
      const ms = (s.tests ?? []).flatMap((t) => t.results ?? []).reduce((a, r) => a + (r.duration ?? 0), 0)
      const key = s.file ?? '(unknown)'
      perFile.set(key, (perFile.get(key) ?? 0) + ms)
    }
    for (const c of node.suites ?? []) walk(c)
  }
  for (const s of j.suites ?? []) walk(s)
  const top = [...perFile.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10)
  // 实测：墙钟在 stats.duration，顶层 duration 是 undefined。
  return { stats: j.stats ?? {}, specs, wallMs: j.stats?.duration ?? j.duration ?? 0, top }
}

function breach(rep) {
  const b = []
  if (rep.wallMs > THRESHOLDS.wallMs) b.push(`墙钟 ${(rep.wallMs / 60000).toFixed(1)}min > ${THRESHOLDS.wallMs / 60000}min`)
  if (rep.specs > THRESHOLDS.specs) b.push(`用例数 ${rep.specs} > ${THRESHOLDS.specs}`)
  if ((rep.stats?.flaky ?? 0) > THRESHOLDS.flakes) b.push(`flake ${rep.stats.flaky} > ${THRESHOLDS.flakes}`)
  return b
}

const today = new Date().toISOString().slice(0, 10)
const outDir = path.join(OUT_ROOT, today)
const jsonFile = path.join(outDir, 'results.json')

fs.mkdirSync(outDir, { recursive: true })
// DRY 只打印计划、什么都不跑，前置门（防的是「真跑时抢别人的端口/工作区」）无意义。
const skip = DRY ? null : precheck()
const series = []

if (skip) {
  console.log(`SKIPPED: ${skip}`)
  series.push({ date: today, result: 'SKIPPED', reason: skip })
} else {
  fs.writeFileSync(LOCK, `${new Date().toISOString()} pid=${process.pid}\n`)
  try {
    const unit = run('npm run test:unit')
    const py = spawnSync('python', ['-c', 'import pytest'], { cwd: ROOT })
    if (py.status !== 0) {
      console.log('SKIPPED: `python` 无 pytest —— .venv 会缺它并把 import 失败伪装成回归，拒绝在夜间轮里用错解释器')
      series.push({ date: today, result: 'SKIPPED', reason: 'python 无 pytest' })
    } else {
      const labels = backendLabels()
      const t1 = run(`python manage.py test ${labels.join(' ')}`, { PYTHONIOENCODING: 'utf-8' }, ROOT)
      const t3 = run('npx playwright test --reporter=json,html,list', {
        CI: '1',
        PLAYWRIGHT_JSON_OUTPUT_NAME: jsonFile,
      })
      if (DRY) {
        series.push({ date: today, result: 'DRY-RUN', breaches: [] })
      } else if (!fs.existsSync(jsonFile)) {
        console.log(`FAILED: playwright 未产出 ${path.relative(ROOT, jsonFile)}（exit=${t3.status}）`)
        series.push({ date: today, result: 'FAILED', reason: '无 JSON 产物', breaches: [] })
      } else {
        const rep = parseReport(jsonFile)
        const breaches = breach(rep)
        console.log(
          `T3: ${rep.specs} 例 / ${(rep.wallMs / 60000).toFixed(1)}min | expected=${rep.stats?.expected} unexpected=${rep.stats?.unexpected} flaky=${rep.stats?.flaky} skipped=${rep.stats?.skipped}`,
        )
        for (const [f, ms] of rep.top) console.log(`  ${(ms / 1000).toFixed(1).padStart(7)}s  ${f}`)
        if (breaches.length) console.log(`⚠ DEGRADED: ${breaches.join('; ')}`)
        series.push({
          date: today,
          result: (rep.stats?.unexpected ?? 0) > 0 || t1.status || unit.status ? 'FAILED' : 'PASSED',
          breaches,
          specs: rep.specs,
          wallMs: rep.wallMs,
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
// 同一天只留最后一轮，避免多次跳过把曲线挤满。
history = [...(Array.isArray(history) ? history : []).filter((h) => h.date !== series[0]?.date), ...series].slice(-30)
fs.writeFileSync(latestFile, JSON.stringify(history, null, 2))

const rows = history
  .slice()
  .reverse()
  .map((h) => {
    if (h.result === 'SKIPPED') return `| ${h.date} | SKIPPED | ${h.reason} | — |`
    const warn = h.breaches?.length ? '⚠ DEGRADED ' : ''
    if (h.wallMs == null) return `| ${h.date} | ${warn}${h.result} | ${h.reason ?? '—'} | — |`
    return `| ${h.date} | ${warn}${h.result} | ${(h.wallMs / 60000).toFixed(1)}min | ${h.specs} 例 / flaky ${h.stats?.flaky ?? '?'} |`
  })
  .join('\n')

fs.writeFileSync(
  path.join(OUT_ROOT, 'LATEST.md'),
  `# 夜间全量兜底轮（最近 ${history.length} 轮）

阈值：墙钟 ${THRESHOLDS.wallMs / 60000}min · 用例 ${THRESHOLDS.specs} · flaky ${THRESHOLDS.flakes}
最近一轮明细：\`tasks/e2e-nightly/${today}/\`（results.json + playwright-report）

| 日期 | 结果 | 墙钟 | 规模 |
|---|---|---|---|
${rows}

> 出现 ⚠ DEGRADED 时：按 docs/superpowers/specs/ 的三层判据，把最慢文件的断言下沉到 T1/T2，
> 或删掉已陈旧的 T0。别靠加大超时来「消红」。
`,
)

const s = series[0]
process.exit(s?.result === 'FAILED' ? 1 : 0)
