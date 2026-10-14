#!/usr/bin/env node
/**
 * e2e_affected — 按改动范围选测试，跑「够用的那一层」而不是全量。
 *
 * 用法：
 *   node scripts/e2e_affected.mjs                 # 自动判定 base，打印决定并执行
 *   node scripts/e2e_affected.mjs --dry-run       # 只看决定
 *   node scripts/e2e_affected.mjs --base origin/master
 *   node scripts/e2e_affected.mjs -- --project=P1 # -- 之后的参数转给 playwright
 *
 * 三条升级为全量的兜底（任一命中即放弃快档），以及「无受影响用例」必须
 * 显式说出来而不是显示成 0 failed 的假绿 —— 判据见
 * docs/superpowers/specs/2026-09-26-e2e-tier-and-affected-gate-design.md。
 */
import { execFileSync, spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const FRONTEND = path.join(ROOT, 'frontend')
const E2E = 'frontend/e2e/'

const MAX_MODULES_BEFORE_FULL = 6

/** 所有已知 e2e 模块（目录名）。用于「命中数超阈值即全量」。 */
const MODULES = [
  'admin', 'analysis', 'auth', 'batch', 'dashboard', 'data',
  'electron', 'exports', 'settings', 'sftp', 'theme',
]

const GLOBAL = 'GLOBAL'

/**
 * 前缀 → 模块。首条命中即生效，故长前缀写在前。
 * 键用「页面目录 / api 文件 / 端点所在 app」，不用宽泛的词（analysis、files 这类
 * 单词在 e2e 里扇出到 6+ 模块，拿它当键等于每次改动都跑大半套件）。
 */
const RULES = [
  // —— 前端页面与 api 文件
  ['frontend/src/pages/analysis/', ['analysis']],
  ['frontend/src/pages/dashboard/', ['dashboard']],
  ['frontend/src/pages/data/', ['data', 'exports']],
  ['frontend/src/pages/settings/', ['settings']],
  ['frontend/src/pages/sftp/', ['sftp']],
  ['frontend/src/pages/admin/', ['admin']],
  ['frontend/src/pages/auth/', ['auth']],
  ['frontend/src/api/analysis.ts', ['analysis']],
  ['frontend/src/api/gage.ts', ['analysis', 'exports']],
  ['frontend/src/api/batch.ts', ['batch', 'data']],
  ['frontend/src/api/buyoff.ts', ['data', 'exports']],
  ['frontend/src/api/datafiles.ts', ['data']],
  ['frontend/src/api/sftp', ['sftp']],
  ['frontend/src/api/system.ts', ['settings']],
  ['frontend/src/api/auth.ts', [GLOBAL]],

  // —— 后端 app
  ['apps/analysis/', ['analysis']],
  ['apps/batch_report/', ['batch', 'dashboard']],
  ['apps/buyoff/', ['data', 'exports']],
  ['apps/gage/', ['analysis', 'exports']],
  ['apps/dashboard/', ['dashboard']],
  ['apps/datafiles/', ['data']],
  ['apps/sftp/', ['sftp']],
  ['apps/export/', ['exports']],
  ['apps/common/', [GLOBAL]],
  ['apps/accounts/', [GLOBAL]],

  // —— 后端测试自身：由 backendLabels() 跑，不再牵动 e2e 选择
  ['test/backend/', []],
  ['apps/analysis/tests', []],
  ['apps/batch_report/tests', []],
  ['apps/buyoff/tests', []],
  ['apps/gage/tests', []],
  ['apps/dashboard/tests', []],
  ['apps/datafiles/tests', []],
  ['apps/sftp/tests', []],
  ['apps/export/tests', []],
  ['apps/common/tests', []],
  ['apps/accounts/tests', []],

  // —— e2e 资产：helpers/fixtures/config 一动等于全量
  ['frontend/e2e/helpers/', [GLOBAL]],
  ['frontend/e2e/fixtures/', [GLOBAL]],
  ['frontend/e2e/global/', [GLOBAL]],
  ['frontend/e2e/smoke/', [GLOBAL]],
  ['frontend/e2e/theme/', ['theme']],
  ['frontend/e2e/', null], // 其余按目录名即模块

  // —— T2 层自身
  ['frontend/test/', ['unit']],

  // —— T2 已覆盖的纯函数：只需 vitest，不必开浏览器
  ['frontend/src/utils/format.ts', ['unit']],
  ['frontend/src/utils/minmax.ts', ['unit']],
  ['frontend/src/utils/error.ts', ['unit']],
  ['frontend/src/utils/batchAggregation.ts', ['unit']],

  // —— 子项目自带验证通路，不由 e2e 承载（打印提示，避免静默无门禁）
  ['DataPrase-ExcelAddin/', ['none:ExcelAddin 走 DataPrase-ExcelAddin/verify-installed.ps1']],
  ['DataPrase-LightVBA/', ['none:LightVBA 无自动化测试']],
  ['DataPrase-SFTP Searcher/', ['none:SFTP Searcher 独立于 Django 后端']],

  // —— 无测试判据受影响
  ['docs/', []],
  ['tasks/', []],
  ['.claude/', []],
  ['.qoder/', []],

  // —— 明确的全局清单（宁多勿漏）
  ['frontend/src/router/', [GLOBAL]],
  ['frontend/src/stores/', [GLOBAL]],
  ['frontend/src/layouts/', [GLOBAL]],
  ['frontend/src/components/layout/', [GLOBAL]],
  ['frontend/src/styles/', [GLOBAL]],
  ['frontend/src/theme/', [GLOBAL]],
  ['frontend/src/types/', [GLOBAL]],
  ['frontend/src/constants/', [GLOBAL]],
  ['frontend/src/composables/', [GLOBAL]],
  ['frontend/src/utils/', [GLOBAL]],
  ['frontend/src/api/index.ts', [GLOBAL]],
  ['frontend/e2e/global-setup.ts', [GLOBAL]],
  ['frontend/playwright.config.ts', [GLOBAL]],
  ['frontend/vitest.config.ts', ['unit']],
  ['frontend/vite.config.ts', [GLOBAL]],
  ['frontend/tsconfig', [GLOBAL]],
  ['frontend/package', [GLOBAL]],
  ['frontend/index.html', [GLOBAL]],
  ['config/', [GLOBAL]],
  ['requirements/', [GLOBAL]],
  ['manage.py', [GLOBAL]],
  ['standalone.py', [GLOBAL]],
  ['scripts/', [GLOBAL]],
  ['Data/', [GLOBAL]],
  ['electron/', ['electron']],
  ['build.bat', [GLOBAL]],
  ['package.json', [GLOBAL]],
  ['package-lock.json', [GLOBAL]],
]

/** 命中 migrations 一律全量（schema 变了谁都说不准）。 */
const ALWAYS_GLOBAL_RE = [/\/migrations\/[^/]+\.py$/, /^frontend\/src\/pages\/NotFoundPage\.vue$/, /(^|\/)\.env/]

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

function matchRule(file) {
  if (ALWAYS_GLOBAL_RE.some((re) => re.test(file))) return [GLOBAL]
  if (file.endsWith('.md')) return []
  for (const [prefix, mods] of RULES) {
    if (!file.startsWith(prefix)) continue
    if (mods === null) {
      const dir = file.slice(E2E.length).split('/')[0]
      return MODULES.includes(dir) ? [dir] : [GLOBAL]
    }
    return mods
  }
  return [GLOBAL] // 未知路径 → 兜底全量，不猜
}

function decide(files) {
  const out = { modules: new Set(), unit: false, global: false, notes: [], reasons: [] }
  for (const f of files) {
    for (const m of matchRule(f)) {
      if (m === GLOBAL) {
        out.global = true
        out.reasons.push(`${f} → 全局清单`)
      } else if (m === 'unit') {
        out.unit = true
      } else if (m.startsWith('none:')) {
        out.notes.push(m.slice(5))
      } else {
        out.modules.add(m)
      }
    }
  }
  if (out.modules.size > MAX_MODULES_BEFORE_FULL) {
    out.global = true
    out.reasons.push(`命中 ${out.modules.size} 个模块 > ${MAX_MODULES_BEFORE_FULL} 阈值`)
  }
  return out
}

function backendLabels(files) {
  const labels = new Set()
  for (const f of files) {
    const app = /^apps\/([a-z_]+)\//.exec(f)?.[1]
    if (app && app !== '__init__' && app !== 'CLAUDE.md') labels.add(`apps.${app}`)
    if (f.startsWith('test/backend/')) labels.add('test.backend')
  }
  return [...labels]
}

function run(cmd, printCmd, cwd = FRONTEND) {
  console.log(`\n$ ${printCmd}`)
  if (DRY) return 0
  // Windows 下 npm/npx 是 .cmd，必须走 shell；Git Bash 里 shell:true 同样可用。
  const r = spawnSync(cmd, { cwd, stdio: 'inherit', shell: true })
  return r.status ?? 1
}

const changed = FILES ? { base: '--files（虚构改动集，仅判定）', files: FILES } : collectChanged()
if (!changed) {
  console.log('FULL (reason: 无法确定 base —— 全量是唯一安全选择)')
  process.exit(run(`npx playwright test ${TAIL}`, `npx playwright test ${TAIL}`) )
}

const d = decide(changed.files)
const labels = backendLabels(changed.files)
const selected = d.global ? null : [...d.modules].sort()
const paths = selected ? selected.map((m) => `e2e/${m}`).concat(PW_EXTRA).join(' ') : ''
// 附带 P0：只补跑未被模块覆盖的那部分模块，避免同一用例在两条命令里各跑一遍。
const p0Paths = selected ? MODULES.filter((m) => !selected.includes(m)).map((m) => `e2e/${m}`).join(' ') : ''

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
    `NO AFFECTED TESTS (${changed.files.length} files${d.notes.length ? ' —— 见上方 note，那部分改动有自己的验证通路' : ''})`,
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
// T2 永远跑（162 ms 量级），全量分支也不例外。
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
  code ||= run(`npx playwright test ${TAIL}`, `npx playwright test ${TAIL}`)
} else if (selected.length) {
  code ||= run(`npx playwright test ${paths}`, `npx playwright test ${paths}`)
  if (p0Paths) code ||= run(`npx playwright test --project=P0 ${p0Paths} ${TAIL}`, `npx playwright test --project=P0 ${p0Paths} ${TAIL}`)
}
process.exit(code)
