// scripts/affected-rules.mjs
// e2e 快门禁的**判定内核**：纯数据 + 纯函数，零 IO。
// 从 scripts/e2e_affected.mjs 里拆出来有两个原因：① 原脚本模块顶层就执行整条门禁，
// 一 import 就真跑，vitest 压不住它 —— 而「哪些路径算承重」恰恰是最该被钉住的判据；
// ② 本表是分层节奏里「批内该跑哪一档」的**实现**，判据正文（为什么这么判）在
//    `docs/reference/testing-gates.md`；改判据只需 `npx vitest run`，不开浏览器。
//
// 判据方向（不变的安全边界）：**未知路径一律 GLOBAL，宁可多跑也不漏**。下面新增的每一条
// 放行类目都必须写清「它为什么不由浏览器承载」，且不能反过来把默认值改成放行。

export const GLOBAL = 'GLOBAL'

/** 命中模块数超过它就放弃选例、升级全量。 */
export const MAX_MODULES_BEFORE_FULL = 6

/** 所有已知 e2e 模块（目录名）。用于「命中数超阈值即全量」。 */
export const MODULES = [
  'admin', 'analysis', 'auth', 'batch', 'dashboard', 'data',
  'electron', 'exports', 'settings', 'sftp', 'theme',
]

/**
 * 前缀 → 处置令牌。首条命中即生效，故**长前缀必须写在前**。
 * 令牌四种：模块名（进 e2e 模块档）｜`GLOBAL`（升级全量）｜`unit`（只跑 vitest）｜
 * `none:说明`（不由 e2e 承载，把说明打进 note，避免静默无门禁）。
 * 键用「页面目录 / api 文件 / 端点所在 app」，不用宽泛的词（analysis、files 这类
 * 单词在 e2e 里扇出到 6+ 模块，拿它当键等于每次改动都跑大半套件）。
 */
export const RULES = [
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

  // —— 后端测试自身：由 backendLabels() 跑，不再牵动 e2e 选择
  // ⚠ 必须整块写在下面 `apps/<app>/` 那些条目**之前**：本表是「首条命中即生效」的前缀匹配，
  // 顺序反了就永远轮不到这几条。2026-10-16 写 e2eAffectedDecide.spec.ts 时才发现它们此前
  // 全是死规则（被 apps/analysis/ 等遮蔽），后果是「只改后端测试文件」也要拉起整个 e2e 模块。
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

  // —— 已被 T2 钉住的门禁判据：改判据由毫秒级单测验收，不开浏览器
  // （三条都有对应 spec，不是「应该被测」而是「已经在测」：
  //  nightly-gates → e2eNightlyGates.spec.ts，pool-core → e2ePoolCore.spec.ts，
  //  icon-lib → iconLib.spec.ts。浏览器全量对这三个文件零判据价值：它只是恰好用了它们。）
  ['frontend/e2e/helpers/nightly-gates', ['unit',
    'none:退化阈值与判级纯函数已由 e2eNightlyGates.spec.ts 钉住；用 `--report-only <既有产物>` 验算，别为确认公式跑全量']],
  ['frontend/e2e/helpers/pool-core', ['unit',
    'none:端口/分区/崩池判定已由 e2ePoolCore.spec.ts 钉住；改完请另跑一次 `--slots=2 --dry-run` 与小集合真跑，端口抢占只有实跑才现形']],
  ['scripts/affected-rules.mjs', ['unit',
    'none:本判定内核由 e2eAffectedDecide.spec.ts 钉住（双向：假阳性降级 + 真承重仍升级）']],

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

  // —— 打包期图标工具：判据（内缩比例、审计阈值、ico 组装）全在 icon-lib.cjs 且已被
  // iconLib.spec.ts / appIcon.spec.ts 钉住；audit/metrics/gen 只是调用它们的壳。
  ['scripts/icon-lib.cjs', ['unit']],
  ['scripts/icon-audit.cjs', ['unit', 'none:图标审计 CLI 外壳，判据住在 icon-lib.cjs（已 T2 钉住）']],
  ['scripts/icon-metrics.cjs', ['unit', 'none:图标度量外壳，判据住在 icon-lib.cjs（已 T2 钉住）']],
  ['scripts/gen-icon.ico.js', ['none:打包期图标生成，验证通路 = electron:build 产物与 iconLib/appIcon 单测']],
  ['scripts/generate_icon.py', ['none:打包期图标生成，验证通路 = electron:build 产物与 iconLib/appIcon 单测']],

  // —— 门禁编排器自身（跑测试的脚本，不是被测产品）。产品代码一行没动时，
  // 跑整轮浏览器**验不出编排器的对错**，只会把没变的被测对象再测一遍。
  // ⚠ 编排器自己没有单测（IO 重），自检通路就是它自己的 dry-run —— note 必须喊出来，
  // 否则「门禁坏了但没人知道」会被当成绿灯（lessons 2026-10-13：后端分支 cwd 拼错，
  // 那条快门禁从没跑通过，因为没人制造过一次真命中它的改动）。
  ['scripts/e2e_', ['unit',
    'none:门禁编排器无单测（IO 重）；改完必自证 `node scripts/e2e_affected.mjs --dry-run` 与 `e2e_pool.mjs --slots=2 --dry-run`，看打印的判定与 slot 数对不对']],

  // —— 代理与工具的落盘物：不是被测对象，也不改任何被测对象的行为
  ['.gitignore', ['none:.gitignore 只改忽略规则，无测试判据受影响']],
  ['.lqdp_startup.lock', ['none:启动锁文件的清理动作，无测试判据受影响']],
  ['.commandcode/', ['none:代理工具配置/品味文件，无测试判据受影响']],
  ['.superpowers/', ['none:头脑风暴会话的落盘产物（正式文档在 docs/，不是这里）']],
  ['.workbuddy-ai/', ['none:外部工具的工作目录落盘物，无测试判据受影响']],
  ['.github/', ['none:CI 配置由 CI 自己验；本仓 CI 刻意不跑 Playwright（阈值按本机标定）']],

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

/** 命中这些一律全量（schema 变了谁都说不准）。 */
export const ALWAYS_GLOBAL_RE = [/\/migrations\/[^/]+\.py$/, /^frontend\/src\/pages\/NotFoundPage\.vue$/, /(^|\/)\.env/]

/**
 * 不是被测对象、也不改任何被测对象行为的落盘物。按**形状**收紧，避免整目录放行：
 * - `.gitignore` 允许出现在任意层级（`frontend/.gitignore` 同理），它只改忽略规则；
 * - 诊断截图只认「单层路径下的位图」：`night-diag-fail.png` 这类一次性现场留档。
 *   入库资产带目录前缀（`frontend/public/`、`frontend/src/assets/`），落进各自的规则，
 *   所以这条放过不了真资产。
 */
export const NOT_TEST_BEARING = [
  [/^(?:[^/]+\/)*\.gitignore$/, '.gitignore 只改忽略规则，无测试判据受影响'],
  [/^(?:frontend\/)?[^/]+\.(png|jpe?g)$/, '根级诊断截图（入库资产住 frontend/public 与 src/assets），无测试判据受影响'],
]

/** 前缀 → 模块；首条命中即生效。 */
export function matchRule(file) {
  if (ALWAYS_GLOBAL_RE.some((re) => re.test(file))) return [GLOBAL]
  if (file.endsWith('.md')) return []
  for (const [re, why] of NOT_TEST_BEARING) {
    if (re.test(file)) return [`none:${why}`]
  }
  for (const [prefix, mods] of RULES) {
    if (!file.startsWith(prefix)) continue
    if (mods === null) {
      const dir = file.slice('frontend/e2e/'.length).split('/')[0]
      return MODULES.includes(dir) ? [dir] : [GLOBAL]
    }
    return mods
  }
  return [GLOBAL] // 未知路径 → 兜底全量，不猜
}

/** 一组改动文件 → 该跑哪一档。`global` 为真即升级全量。 */
export function decide(files) {
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
  // note 去重：一条规则被多个文件命中时会重复推（例：一次提交动 10 个 `scripts/e2e_*` 会推 10 条同一提示）
  out.notes = [...new Set(out.notes)]
  return out
}

/** 改动落在哪些 Django 测试标签上（与 e2e 选例正交，由 e2e_nightly.mjs 的同类函数同口径）。 */
export function backendLabels(files) {
  const labels = new Set()
  for (const f of files) {
    const app = /^apps\/([a-z_]+)\//.exec(f)?.[1]
    if (app && app !== '__init__' && app !== 'CLAUDE.md') labels.add(`apps.${app}`)
    if (f.startsWith('test/backend/')) labels.add('test.backend')
  }
  return [...labels]
}
