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
 * 判据表与 decide()/matchRule()/backendLabels()、编排三兄弟 planStages()/executePlan()/
 * gateVerdict() 都住在 scripts/affected-rules.mjs（纯函数、零 IO，被
 * frontend/test/unit/e2eAffectedDecide.spec.ts 钉住）。这里只管取改动集、探测解释器、执行与打印。
 * 三条升级为全量的兜底（任一命中即放弃快档），以及「无受影响用例」必须
 * 显式说出来而不是显示成 0 failed 的假绿 —— 判据正文见 docs/reference/testing-gates.md。
 *
 * ⚠ 判这一轮的绿/红，取日志最后的 `RESULT:` 行，不要取 `$?`：
 *   `npm run test:e2e:affected | tail -N` 的退出码是 tail 的，历史上当场骗过一次（2026-10-20）。
 */
import { spawnSync, execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { backendLabels, decide, executePlan, gateVerdict, planStages } from './affected-rules.mjs'

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

/**
 * 结论一律打成日志的**最后**几行：退出码会被 `| tail` 这类管道吃掉（2026-10-20 实测
 * 「exit 0」与「FAILED (failures=1)」同时出自一条命令），而末尾的 RESULT 行落在任何
 * `tail -N` 的窗口里。**判这一轮的绿/红取 RESULT 行，不取 `$?`。**
 */
function report(results, planned) {
  console.log('')
  for (const r of results) {
    const tag = r.aborted
      ? `ABORTED: ${r.aborted}`
      : r.skipped
        ? `SKIP (${r.skipped})`
        : r.status === 0
          ? 'ok'
          : `FAIL (exit=${r.status})`
    console.log(`档:       ${r.name.padEnd(14)} ${tag}`)
  }
  const v = gateVerdict(results)
  console.log(
    `RESULT:   ${v.ok ? 'PASS' : 'FAIL'} · 计划 ${planned} 档` +
      (planned === results.length ? '全部执行' : `，只执行了 ${results.length} 档`) +
      (v.failed.length ? ` · 失败 [${v.failed.join(', ')}]` : '') +
      (v.skipped.length ? ` · 跳档 [${v.skipped.join(', ')}]` : '') +
      (DRY ? ' · dry-run（未真正执行）' : ''),
  )
  process.exit(v.ok ? 0 : 1)
}

/** 没有档可跑：绿灯之外的第三种状态，必须自己说清，别让人当成「测过了」。 */
function reportNoTests(reason) {
  console.log(`RESULT:   NO AFFECTED TESTS —— ${reason}（本轮没有档执行，不等于绿灯）`)
  process.exit(0)
}

const changed = FILES ? { base: '--files（虚构改动集，仅判定）', files: FILES } : collectChanged()
if (!changed) {
  console.log('FULL (reason: 无法确定 base —— 全量是唯一安全选择)')
  report([{ name: 'e2e:全量', status: runPool('') }], 1)
}

const d = decide(changed.files)
const labels = backendLabels(changed.files)

console.log(`base:     ${changed.base}`)
console.log(`changed:  ${changed.files.length} 个文件`)
for (const n of d.notes) console.log(`note:     ${n}`)
if (d.reasons.length) for (const r of d.reasons.slice(0, 8)) console.log(`why:      ${r}`)

if (!changed.files.length) reportNoTests('工作区无改动')
if (!d.global && !d.modules.size && !d.unit && !labels.length) {
  reportNoTests(
    `${changed.files.length} files${d.notes.length ? ' —— 那部分改动不由 e2e 承载，验证通路见上方 note' : ''}`,
  )
}

console.log(
  d.global
    ? 'decide:   全量 e2e（兜底命中，见上 why）'
    : `decide:   e2e 模块 [${[...d.modules].sort().join(', ') || '（仅 T2/后端）'}] + vitest`,
)
if (d.modules.has('electron')) console.log('note:     e2e/electron 需要 `npm run electron:build:ts` 产物，缺则该模块会红')

// 解释器探测留在脚本里（IO），计划本身是纯函数 —— 见 affected-rules.mjs 的 planStages()。
const pytest = RUN_BACKEND && labels.length ? spawnSync('python', ['-c', 'import pytest'], { cwd: ROOT, encoding: 'utf-8' }).status === 0 : true

const plan = planStages({ decision: d, labels, runBackend: RUN_BACKEND, pytest })
report(executePlan(plan, (s) => {
  if (s.kind === 'lint') return run('npm run lint:e2e', 'npm run lint:e2e')
  if (s.kind === 'unit') return run('npm run test:unit', 'npm run test:unit')
  if (s.kind === 'backend') {
    // manage.py 在仓库根，而 npm 脚本挂在 frontend/ —— cwd 必须跟着切，
    // 否则 python 会在 frontend/ 下找不到 manage.py（2026-10-13 实测：后端步骤
    // 只要被选中就必断，这条快门禁从没跑通过）。
    const cmd = `python manage.py test ${s.labels.join(' ')}`
    return run(cmd, cmd, ROOT)
  }
  return runPool(s.files ?? '', s.pw ?? '')
}), plan.length)
