#!/usr/bin/env node
/**
 * e2e_affected — 按改动范围选测试，跑「够用的那一层」而不是全量。
 *
 * 用法：
 *   node scripts/e2e_affected.mjs                 # 自动判定 base，打印决定并执行
 *   node scripts/e2e_affected.mjs --dry-run       # 只看决定
 *   node scripts/e2e_affected.mjs --base origin/master
 *   node scripts/e2e_affected.mjs --files a,b,c   # 核判定本身（不碰工作区，等价 --dry-run）
 *   node scripts/e2e_affected.mjs -- --project=P1 # -- 之后的参数转给 playwright
 *
 * 判据表与 decide()/matchRule()/backendLabels() 住在 scripts/affected-rules.mjs
 * （纯函数、被 test/unit/e2eAffectedDecide.spec.ts 钉住）。这里只管取改动集、打印与执行。
 * 三条升级为全量的兜底（任一命中即放弃快档），以及「无受影响用例」必须
 * 显式说出来而不是显示成 0 failed 的假绿 —— 判据正文见 docs/testing-gates.md。
 */
import { spawnSync, execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { MODULES, backendLabels, decide } from './affected-rules.mjs'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const FRONTEND = path.join(ROOT, 'frontend')

const args = process.argv.slice(2)
const sep = args.indexOf('--')
const opts = sep === -1 ? args : args.slice(0, sep)
const PW_EXTRA = sep === -1 ? [] : args.slice(sep + 1)

/**
 * 转发给 playwright 的公共尾巴。此前只拼在模块分支的 `paths` 上，全量分支与
 * 附带 P0 那条都把它丢了 —— 于是 `-- --workers=1` 恰好在最需要它的全量档里静默失效，
 * 6 worker 打单进程 Django 造出 8 条与改动无关的硬红（2026-10-14 实测）。
 */
const TAIL = PW_EXTRA.join(' ')
const RUN_BACKEND = !opts.includes('--no-backend')
const baseIdx = opts.indexOf('--base')
const BASE = baseIdx === -1 ? null : opts[baseIdx + 1]
// --files a,b,c：直接喂改动集，用来核判定本身（不碰工作区）。
const filesIdx = opts.indexOf('--files')
const FILES = filesIdx === -1 ? null : opts[filesIdx + 1].split(',').filter(Boolean)
const DRY = opts.includes('--dry-run') || FILES !== null

function git(...a) {
  return execFileSync('git', a, { cwd: ROOT, encoding: 'utf-8' }).trim()
}

/** 取改动文件集与 base 说明；取不到时返回 null，由调用方判全量。 */
function collectChanged() {
  try {
    const untracked = git('ls-files', '--others', '--exclude-standard').split('\n').filter(Boolean)
    if (BASE) {
      const files = git('diff', '--name-only', BASE).split('\n').filter(Boolean)
      return { base: `--base ${BASE} (+ untracked)`, files: [...new Set([...files, ...untracked])] }
    }
    const files = git('diff', '--name-only', 'HEAD').split('\n').filter(Boolean)
    if (files.length || untracked.length) {
      return { base: 'worktree vs HEAD (+ untracked)', files: [...new Set([...files, ...untracked])] }
    }
    const last = git('diff', '--name-only', 'HEAD~1', 'HEAD').split('\n').filter(Boolean)
    if (last.length) return { base: 'HEAD~1..HEAD (worktree 干净)', files: last }
    return { base: 'no changes', files: [] }
  } catch (e) {
    console.error(`[affected] git 读取失败：${e.message}`)
    return null
  }
}

function run(cmd, printCmd, cwd = FRONTEND, env = {}) {
  console.log(`\n$ ${printCmd}`)
  if (DRY) return 0
  // Windows 下 npm/npx 是 .cmd，必须走 shell；Git Bash 里 shell:true 同样可用。
  const r = spawnSync(cmd, { cwd, stdio: 'inherit', shell: true, env: { ...process.env, ...env } })
  return r.status ?? 1
}

/**
 * T3 一律走 slot 池（1 进程 = 1 worker = 1 slot，每 slot 独立库副本 / data_dir / 端口对）。
 * 文件与目录进 `--` 之后；Playwright 开关经 E2E_PW_ARGS 透传 —— 混在文件表里会被当成
 * 文件名分进桶（旧写法 `paths.concat(PW_EXTRA)` 就是这么拼的）。
 * 改动集小时池的 autoSlots 自然退回 1 个 slot ⇒ 快门禁不必自己管并行度，旋钮只有 --slots/E2E_SLOTS。
 */
function runPool(filesArg, extraPwArgs = '') {
  const cmd = 'node scripts/e2e_pool.mjs --slots=auto'
  const pw = [TAIL, extraPwArgs].filter(Boolean).join(' ')
  const printCmd = cmd + (filesArg ? ' -- ' + filesArg : '') + (pw ? `   [E2E_PW_ARGS="${pw}"]` : '')
  return run(cmd, printCmd, ROOT, pw ? { E2E_PW_ARGS: pw } : {})
}

const changed = FILES ? { base: '--files（虚构改动集，仅判定）', files: FILES } : collectChanged()
if (!changed) {
  console.log('FULL (reason: 无法确定 base —— 全量是唯一安全选择)')
  process.exit(runPool(''))
}

const d = decide(changed.files)
const labels = backendLabels(changed.files)
const selected = d.global ? null : [...d.modules].sort()
const paths = selected ? selected.map((m) => `e2e/${m}`).join(' ') : ''
// 附带 P0：只补跑未被模块覆盖的那部分模块，避免同一用例在两条命令里各跑一遍。
const p0Paths = selected
  ? MODULES.filter((m) => !selected.includes(m)).map((m) => `e2e/${m}`).join(' ')
  : ''

console.log(`base:     ${changed.base}`)
console.log(`changed:  ${changed.files.length} 个文件`)
for (const n of d.notes) console.log(`note:     ${n}`)
if (d.reasons.length) for (const r of d.reasons.slice(0, 8)) console.log(`why:      ${r}`)

if (!changed.files.length) {
  console.log('NO AFFECTED TESTS (工作区无改动)')
  process.exit(0)
}
if (!d.global && !d.modules.size && !d.unit && !labels.length) {
  console.log(
    `NO AFFECTED TESTS (${changed.files.length} files${d.notes.length ? ' —— 那部分改动不由 e2e 承载，验证通路见上方 note' : ''})`,
  )
  process.exit(0)
}

console.log(
  d.global
    ? 'decide:   全量 e2e（兜底命中，见上 why）'
    : `decide:   e2e 模块 [${selected.join(', ') || '（仅 T2/后端）'}] + vitest`,
)

let code = 0
// e2e 静态体检放在最前（约 3 s）：删掉用例后残留的失效 import、失去调用者的助手要在这里
// 出声，而不是等几分钟的浏览器跑完才发现，也不用等下轮有人读文件。
code ||= run('npm run lint:e2e', 'npm run lint:e2e')
// T2 永远跑（实测 175 例 / 408 ms），全量分支也不例外。
code ||= run('npm run test:unit', 'npm run test:unit')
if (selected?.includes('electron')) console.log('note:     e2e/electron 需要 `npm run electron:build:ts` 产物，缺则该模块会红')
if (RUN_BACKEND && labels.length) {
  const py = spawnSync('python', ['-c', 'import pytest'], { cwd: ROOT, encoding: 'utf-8' })
  if (py.status !== 0) {
    console.error('BACKEND SKIPPED: 当前 `python` 无 pytest —— 用 .venv 跑会把 test_outliers 的 import 失败伪装成回归，故拒绝执行')
  } else {
    // manage.py 在仓库根，而 npm 脚本挂在 frontend/ —— cwd 必须跟着切，
    // 否则 python 会在 frontend/ 下找不到 manage.py（2026-10-13 实测：后端步骤
    // 只要被选中就必断，这条快门禁从没跑通过）。
    code ||= run(`python manage.py test ${labels.join(' ')}`, `python manage.py test ${labels.join(' ')}`, ROOT)
  }
}
if (d.global) {
  code ||= runPool('')
} else if (selected.length) {
  code ||= runPool(paths)
  if (p0Paths) code ||= runPool(p0Paths, '--project=P0')
}
process.exit(code)
