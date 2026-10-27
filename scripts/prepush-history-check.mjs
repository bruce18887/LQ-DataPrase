// scripts/prepush-history-check.mjs
// `docs/reference/testing-gates.md` §6.5 push 前历史自检的执行体。
//
// 判据只有这一份：`githooks/pre-push` 与手跑命令都调它，钩子载体里不写任何判断。
// 只覆盖 §6.5 里能机器判定的步骤 1–2；步骤 3（重写历史后验内容再带 lease 强推）与
// 步骤 4（强推 ≠ 撤回公开）是人的动作，这里打印成下一步，不代做。

import { existsSync, readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import os from 'node:os'
import path from 'node:path'

const EMPTY_TREE = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'

/** 连已发布历史里都不该出现的根：全历史绊线按这些根查（§6.5 步 2）。 */
export const HARD_ROOTS = [
  { prefix: 'Data/', why: '真实样例含内部绝对路径、机台主机名、内部账号与产品代号，而仓库是公开的（§6.4）' },
  { prefix: '.venv/', why: '解释器环境，入库等于把本机路径与依赖清单全发布' },
]

/**
 * 只按**本次要带出去的提交**判定的根。
 * `tasks/` 不能进 HARD_ROOTS：origin/master 的历史里有 2026-10-16 之前误入库的
 * `tasks/lessons.md` 等 6 条添加记录（今天已不被跟踪）。全历史一律拦 ⇒ 每次 push 都红，
 * 一道天天误报的门禁等于没有门禁。
 */
export const RANGE_ROOTS = [
  { prefix: 'tasks/', why: '代理与夜跑的落盘物；只有 ALLOWED_EXCEPTIONS 点名的文件可入库（§8）' },
]

/** 文件名形状本身就是密钥材料的，任何目录都不许带出去。 */
export const SECRET_PATTERNS = [
  { re: /(^|\/)\.env(\.[^/]+)?$/, why: '环境变量文件通常装着凭据' },
  { re: /\.(key|pem|pfx|p12|jks|keystore)$/i, why: '私钥/证书/密钥库' },
  { re: /(^|\/)(secrets?|credentials|api[_-]?tokens?|id_[dr]sa)([._-]|$)/i, why: '文件名自称就是密钥材料' },
]

/** 显式放行表：每条必须指向库里一个真实存在的决定，否则就是没有主人的豁免。 */
export const ALLOWED_EXCEPTIONS = [
  {
    path: 'tasks/e2e-nightly/LATEST.md',
    why: '§8（2026-10-27 定）：全量兜底轮结论表入库，`.gitignore` 只放行这一个文件',
  },
]

const nextStep = {
  rangeOnly: (p) =>
    `下一步：${p} 还没公开。先 git rm --cached ${p} 再重做这一笔；已经写进历史就得重写历史——按 §6.5 步 3 先验 git diff --stat <备份ref> master 为 0 字节，再带 --force-with-lease 强推。`,
  maybePublished: (p) =>
    `下一步：${p} 的 blob 可能已在公开仓库上。先按 §6.5 步 4 当「已泄露」处理（别按「已修复」）；本地重写历史只让它不可达，按旧 SHA 仍可取，要立刻抹除得提 GitHub 支持工单。`,
  revertRule: (p) => `下一步：把这条 .gitignore 改动（${p}）退回本次 push 之外，单独一笔提交并在提交信息里写明为什么放开。`,
  staleAllow: (p) =>
    `下一步：忽略规则把例外（${p}）收回了，ALLOWED_EXCEPTIONS 里对应那条要一起摘掉，否则放行表留着没有主人的豁免。`,
}

export function guardRoot(p) {
  for (const root of HARD_ROOTS) if (p.startsWith(root.prefix)) return { root, hard: true }
  for (const root of RANGE_ROOTS) if (p.startsWith(root.prefix)) return { root, hard: false }
  return null
}

export const secretMatch = (p) => SECRET_PATTERNS.find((s) => s.re.test(p)) ?? null

export const allowedEntry = (p) => ALLOWED_EXCEPTIONS.find((e) => e.path === p) ?? null

/** 守卫根 / 密钥形状下的新增文件；放行表外的一律拦。 */
export function classifyAdded(paths) {
  const rows = []
  for (const p of paths) {
    const secret = secretMatch(p)
    if (secret) {
      rows.push({ verdict: 'BLOCK', kind: 'secret', path: p, reason: secret.why, next: nextStep.rangeOnly(p) })
      continue
    }
    const hit = guardRoot(p)
    if (!hit) continue
    const allowed = allowedEntry(p)
    if (allowed) rows.push({ verdict: 'ALLOWED', kind: 'guard', path: p, reason: `显式放行：${allowed.why}` })
    else
      rows.push({
        verdict: 'BLOCK',
        kind: 'guard',
        path: p,
        reason: `命中守卫根 ${hit.root.prefix}（${hit.root.why}）`,
        next: hit.hard ? nextStep.maybePublished(p) : nextStep.rangeOnly(p),
      })
  }
  return rows
}

const normalize = (body) => {
  const bare = body.replace(/^\/+/, '').replace(/\/+$/, '')
  return body.endsWith('/') ? `${bare}/` : bare
}

/** 摘掉一条守卫规则后，同根是否还有别的非否定行接着守卫（改写照过，放开没照过）。 */
function stillGuarded(rootPrefix, addedBodies) {
  const want = normalize(rootPrefix).replace(/\/$/, '')
  return addedBodies.some((body) => !body.startsWith('!') && normalize(body).startsWith(want))
}

/**
 * `.gitignore` 的漂移。2026-10-16 那笔事故的形状不是「多了一个 Data/ 文件」而是
 * 「改了一条忽略规则」，所以规则改动本身要判。
 */
export function classifyIgnoreDrift(diffText) {
  const lines = diffText.split('\n')
  const addedBodies = lines
    .filter((l) => l.startsWith('+') && !l.startsWith('+++'))
    .map((l) => l.slice(1).trim())
    .filter((b) => b && !b.startsWith('#'))

  const rows = []
  const push = (verdict, path, reason, next) => rows.push({ verdict, kind: 'ignore', path, reason, next })
  for (const raw of lines) {
    if (raw.startsWith('+++') || raw.startsWith('---')) continue
    const sign = raw[0]
    if (sign !== '+' && sign !== '-') continue
    const body = raw.slice(1).trim()
    if (!body || body.startsWith('#')) continue

    if (sign === '+' && body.startsWith('!')) {
      const target = body.slice(1)
      if (/[*?[\]]/.test(target)) push('BLOCK', body, '用通配把内容重新纳入仓库——2026-10-16 就是「放开 `/Data/` 入库」那个形状', nextStep.revertRule(body))
      else if (target.endsWith('/'))
        ALLOWED_EXCEPTIONS.some((e) => e.path.startsWith(normalize(target)))
          ? push('ALLOWED', body, '只放行父目录，内容仍被排除（§6.4「顺序承重」那条）')
          : push('BLOCK', body, '放行一个放行表里没有例外的目录', nextStep.revertRule(body))
      else {
        const allowed = allowedEntry(normalize(target))
        allowed
          ? push('ALLOWED', body, `显式放行：${allowed.why}`)
          : push('BLOCK', body, '新增例外不在放行表里', nextStep.revertRule(body))
      }
      continue
    }

    if (sign === '-' && !body.startsWith('!')) {
      const hit = guardRoot(normalize(body))
      if (!hit) continue
      stillGuarded(hit.root.prefix, addedBodies)
        ? push('OK', body, '守卫规则被改写（同根仍有规则守着），不是放开')
        : push('BLOCK', body, `摘掉了守卫根 ${hit.root.prefix} 的忽略规则，且没有新规则接着守卫`, nextStep.revertRule(body))
      continue
    }

    if (sign === '-' && body.startsWith('!') && allowedEntry(normalize(body.slice(1))))
      push('STALE', body, '放行例外被收回', nextStep.staleAllow(body))
  }
  return rows
}

/** 钩子 stdin 一行 = `<local_ref> <local_sha> <remote_ref> <remote_sha>`。 */
export function parsePushRefs(stdinText) {
  const zeros = '0'.repeat(40)
  const refs = []
  for (const line of stdinText.split('\n')) {
    const m = line.trim().match(/^(\S+)\s+([0-9a-f]{40})\s+(\S+)\s+([0-9a-f]{40})$/)
    if (!m) continue
    const [localRef, localSha, remoteRef, remoteSha] = m.slice(1)
    if (localSha === zeros || localSha === remoteSha) continue // 删分支 / 已是最新（git 照样喂这行）
    refs.push({ localRef, localSha, remoteRef, remoteSha, isNewBranch: remoteSha === zeros })
  }
  return refs
}

export const verdictOf = (rows) => (rows.some((r) => r.verdict === 'BLOCK') ? 'FAIL' : 'PASS')

const MARK = { BLOCK: 'BLOCK', ALLOWED: 'allow', STALE: 'stale', OK: 'ok' }

export function formatReport({ source, blocks, tripwireRows, tripwireTip, tripwireSkipped }) {
  const out = ['== push 前历史自检（testing-gates.md §6.5 步 1–2）==', `范围来源：${source}`]
  for (const b of blocks) {
    out.push('')
    out.push(`范围 ${b.label}：${b.commits.length} 笔提交会被带出去`)
    out.push('  §6.5 步 1 —— 逐条看会被带出去什么：')
    for (const c of b.commits)
      out.push(`    ${c.sha} ${c.subject}${c.foreign ? `   ← 作者 ${c.author} 不是本机 git user` : ''}`)
    if (!b.commits.length) out.push('    （空）')
    out.push('  §6.5 步 2 —— 守卫根 / 密钥 / 忽略规则漂移：')
    for (const r of b.rows) {
      out.push(`    [${MARK[r.verdict]}] ${r.path} —— ${r.reason}`)
      if (r.next) out.push(`           ${r.next}`)
    }
    if (!b.rows.length) out.push('    （无命中：本次带出去的改动没落在守卫根、密钥形状或 .gitignore 上）')
  }
  if (tripwireSkipped) out.push('', `已发布侧绊线：跳过（${tripwireSkipped}）`)
  else {
    out.push('', `已发布侧绊线（§6.5 步 2 那条 grep 的代码化，基线 ${tripwireTip}）：`)
    for (const root of HARD_ROOTS) {
      const hits = tripwireRows.filter((r) => r.path.startsWith(root.prefix))
      out.push(`    [${hits.length ? 'BLOCK' : 'ok'}] ${root.prefix} —— ${hits.length ? `${hits.length} 条新增` : '无新增（应为空，成立）'}`)
      for (const r of hits) if (r.next) out.push(`           ${r.next}`)
    }
  }
  const allRows = [...blocks.flatMap((b) => b.rows), ...tripwireRows]
  out.push('', `RESULT: ${verdictOf(allRows)}`)
  return out.join('\n')
}

const gitSafe = (args) => {
  try {
    return execFileSync('git', ['-c', 'core.quotepath=false', ...args], { encoding: 'utf8' })
  } catch {
    return null
  }
}
const gitMust = (args) => {
  const out = gitSafe(args)
  if (out === null) throw new Error(`git ${args.join(' ')} 执行失败`)
  return out
}

/** `--diff-filter=A` 逐笔取，不用范围 diff：那一笔加了、下一笔删掉的 blob 还在历史里。 */
function addedPaths(revArgs) {
  return chunksToPaths(gitMust(['log', '--diff-filter=A', '--name-only', '--format=%x00%h', ...revArgs]))
}

function chunksToPaths(raw) {
  return raw
    .split('\0')
    .slice(1)
    .flatMap((chunk) => chunk.split('\n').slice(1).map((l) => l.trim()))
    .filter(Boolean)
}

function commitsIn(revArgs) {
  const me = (gitSafe(['config', 'user.name']) ?? '').trim()
  return gitMust(['log', '--format=%h\x01%an\x01%s', ...revArgs])
    .split('\n')
    .filter(Boolean)
    .map((line) => {
      const [sha, author, subject] = line.split('\x01')
      return { sha, author, subject, foreign: !!me && author !== me }
    })
}

/** §6.5 步 2 那条绊线的代码化：已发布历史里不该有 HARD_ROOTS 的新增。 */
function publishedTripwire(publishedTip) {
  const rows = []
  for (const root of HARD_ROOTS)
    for (const p of chunksToPaths(gitMust(['log', '--diff-filter=A', '--name-only', '--format=%x00', publishedTip, '--', root.prefix])))
      if (!allowedEntry(p)) rows.push({ verdict: 'BLOCK', path: p, reason: `已发布历史里存在 ${root.prefix} 的新增`, next: nextStep.maybePublished(p) })
  return rows
}

const canResolve = (ref) => gitSafe(['rev-parse', '--verify', '--quiet', ref]) !== null

function resolveBlocks(argv) {
  if (argv.includes('--range')) {
    const spec = argv[argv.indexOf('--range') + 1]
    const [base, head = 'HEAD'] = spec.split('..')
    return { source: `--range ${spec}`, publishedTip: base, blocks: [{ label: spec, revArgs: [`${base}..${head}`], diffFrom: base }] }
  }
  if (argv.includes('--from-stdin')) {
    const refs = parsePushRefs(readStdin())
    if (!refs.length) return { source: 'pre-push 钩子 stdin：本次没有要带出去的提交', publishedTip: 'HEAD', blocks: [] }
    return {
      source: `pre-push 钩子 stdin（${refs.map((r) => r.localRef).join(', ')}）`,
      publishedTip: refs.every((r) => r.isNewBranch) ? null : refs[0].remoteSha,
      blocks: refs.map((r) =>
        r.isNewBranch
          ? { label: `新分支 ${r.localRef}`, revArgs: [r.localSha, '--not', '--remotes'], diffFrom: newBranchBase(r.localSha) }
          : { label: `${r.remoteSha.slice(0, 8)}..${r.localSha.slice(0, 8)}`, revArgs: [`${r.remoteSha}..${r.localSha}`], diffFrom: r.remoteSha },
      ),
    }
  }
  for (const upstream of ['@{u}', 'origin/master']) {
    if (!canResolve(upstream)) continue
    const spec = `${upstream}..HEAD`
    return { source: `手跑（基线 ${upstream}）`, publishedTip: upstream, blocks: [{ label: spec, revArgs: [spec], diffFrom: upstream }] }
  }
  return { source: '手跑：找不到任何远端基线', unresolved: true, blocks: [] }
}

/** 新分支没有远端基线：范围里最老那笔的父提交就是 diff 起点（无父则用空树）。 */
function newBranchBase(headSha) {
  const oldest = gitSafe(['rev-list', '--reverse', headSha, '--not', '--remotes'])
    ?.split('\n')
    .filter(Boolean)[0]
  if (!oldest) return 'HEAD'
  return gitSafe(['rev-parse', '--verify', '--quiet', `${oldest}^`]) !== null ? `${oldest}^` : EMPTY_TREE
}

function readStdin() {
  try {
    return readFileSync(0, 'utf8')
  } catch {
    return ''
  }
}

/** 本机钩子接线自检：`core.hooksPath` 指到不存在的目录时，git 会静默什么都不跑（2026-10-27 实测）。 */
export function hookWiring({ hooksPath, hasPushHook, nodeAvailable }) {
  if (!hasPushHook) return { state: 'DEAD', why: hooksPath ? `core.hooksPath=${hooksPath} 下没有 pre-push` : '未设 core.hooksPath，且 .git/hooks 里没有 pre-push' }
  if (!nodeAvailable) return { state: 'DEAD', why: 'pre-push 在，但它要调的 node 不在 PATH' }
  return { state: 'ACTIVE', why: `pre-push 可执行且 node 可用（${hooksPath || '.git/hooks'}）` }
}

function selfCheck() {
  const toplevel = gitMust(['rev-parse', '--show-toplevel']).trim()
  const hooksPath = (gitSafe(['config', '--get', 'core.hooksPath']) ?? '').trim()
  const dir = hooksPath ? (path.isAbsolute(hooksPath) ? hooksPath : path.join(toplevel, hooksPath)) : path.join(toplevel, '.git', 'hooks')
  const hasPushHook = existsSync(path.join(dir, 'pre-push'))
  const wiring = hookWiring({ hooksPath, hasPushHook, nodeAvailable: true })
  const lines = [
    `主机名     : ${os.hostname()}`,
    `工作区     : ${toplevel}`,
    `hooksPath  : ${hooksPath || '(未设置 → 用 .git/hooks)'}  ← 仓库本地配置（.git/config），不是项目事实`,
    `解析到的目录: ${dir}${existsSync(dir) ? '' : '   ← 该目录不存在！'}`,
    `pre-push   : ${hasPushHook ? '存在' : '不存在'}`,
    `结论       : 本次 push ${wiring.state === 'ACTIVE' ? '会' : '不会'}触发自检 —— ${wiring.why}`,
  ]
  if (wiring.state === 'DEAD') lines.push(`修它的一条命令: git config core.hooksPath githooks`)
  console.log(lines.join('\n'))
  process.exitCode = wiring.state === 'ACTIVE' ? 0 : 1
}

function main() {
  const argv = process.argv.slice(2)
  if (argv.includes('--self-check')) return selfCheck()

  const resolved = resolveBlocks(argv)
  if (resolved.unresolved) {
    console.error('RESULT: FAIL\n找不到可比对的远端基线（先 `git fetch`，或确认 origin/master 存在）。判不了就拦：放过去等于这道门不存在。')
    process.exitCode = 1
    return
  }

  const blocks = resolved.blocks.map((b) => ({
    ...b,
    commits: commitsIn(b.revArgs),
    rows: [...classifyAdded(addedPaths(b.revArgs)), ...classifyIgnoreDrift(gitMust(['diff', b.diffFrom, 'HEAD', '--', '.gitignore']))],
  }))

  const tripwireRows = resolved.publishedTip ? publishedTripwire(resolved.publishedTip) : []
  console.log(
    formatReport({
      source: resolved.source,
      blocks,
      tripwireRows,
      tripwireTip: resolved.publishedTip,
      tripwireSkipped: resolved.publishedTip ? null : '本次 push 是新建分支，没有已发布基线可比',
    }),
  )
  process.exitCode = verdictOf([...blocks.flatMap((b) => b.rows), ...tripwireRows]) === 'FAIL' ? 1 : 0
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main()
