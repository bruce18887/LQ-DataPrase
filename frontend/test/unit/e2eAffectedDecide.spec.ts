/**
 * T2：e2e 快门禁的判定内核（`scripts/affected-rules.mjs`）。
 *
 * 为什么值得单独钉：这张表决定一次改动要不要开一轮 6–7 分钟的浏览器全量。
 * 2026-10-16 实测最近 25 个提交：**14 个（56%）被判成全量，且全部来自「未知路径 → 默认 GLOBAL」
 * 这条兜底**，其中 7 个是改 `.gitignore`、代理残留物、打包期图标工具、门禁自己的阈值文件——
 * 这些改动一行产品代码都没动，跑浏览器只是把没变的东西再测一遍。
 *
 * 所以本文件是**双向**的：
 * - 「假阳性必须降级」防的是白烧墙钟；
 * - 「真承重必须升级」防的是把兜底改松过头 —— 那会把漏测换成省时间，是净损失。
 *   默认方向必须是保守：未知路径仍然 GLOBAL。
 *
 * 2026-10-20 起还钉**编排内核**（`planStages` / `executePlan` / `gateVerdict`），
 * 2026-10-21 再补 `poolCmd` / `expandPoolFiles`：这类判据只能这样测——
 * 故障形状是「某一档根本没出现在日志里」或「门禁打印了 narrowed 命令、池自己却说跑了 75 个文件」，
 * 看退出码永远看不出来。
 *
 * 跑：npm run test:unit
 */
import { describe, expect, it } from 'vitest'

import {
  GLOBAL,
  MAX_MODULES_BEFORE_FULL,
  MODULES,
  backendLabels,
  decide,
  executePlan,
  expandPoolFiles,
  gateVerdict,
  matchRule,
  planStages,
  poolCmd,
} from '../../../scripts/affected-rules.mjs'

/** 判定结果的速记：既不升级全量、也没选中 e2e 模块（可能只落 vitest 或纯 note） */
function staysFast(files: string[]) {
  const d = decide(files)
  return { global: d.global, modules: [...d.modules].sort(), unit: d.unit, notes: d.notes, reasons: d.reasons }
}

describe('假阳性：不是被测对象的落盘物，不得升级全量', () => {
  it('.gitignore 在任意层级都只改忽略规则', () => {
    for (const f of ['.gitignore', 'frontend/.gitignore', 'electron/.gitignore']) {
      const r = staysFast([f])
      expect(r.global, `${f} 不该升级全量`).toBe(false)
      expect(r.modules).toEqual([])
      expect(r.notes.join(), `${f} 必须有可见提示`).toMatch(/gitignore/)
    }
  })

  it('代理与工具的落盘物、CI 配置各归各位', () => {
    const r = staysFast([
      '.lqdp_startup.lock',
      '.commandcode/settings.json',
      '.commandcode/taste/taste.md',
      '.superpowers/brainstorm/1050-1788356309/content/data-controls.html',
      '.workbuddy-ai/state.json',
      '.github/workflows/ci.yml',
    ])
    expect(r.global).toBe(false)
    expect(r.modules).toEqual([])
    expect(r.notes.join()).toMatch(/CI 配置由 CI 自己验/)
  })

  it('根级诊断截图不算资产；带目录前缀的真资产仍按原规则走', () => {
    expect(staysFast(['frontend/night-diag-fail.png']).global).toBe(false)
    expect(staysFast(['shot.png']).global).toBe(false)
    // 反向：带目录前缀的真资产不归这条放行，仍按未知路径 → GLOBAL
    expect(matchRule('frontend/public/favicon.svg')).toEqual([GLOBAL])
  })

  it('打包期图标工具：判据已在 iconLib.spec 里，不再开浏览器', () => {
    const r = staysFast(['scripts/icon-lib.cjs', 'scripts/icon-audit.cjs', 'scripts/icon-metrics.cjs'])
    expect(r.global).toBe(false)
    expect(r.unit).toBe(true)
    // 纯壳（生成 ico / 生成 png）连 vitest 都不需要，但必须出声
    const shell = staysFast(['scripts/gen-icon.ico.js', 'scripts/generate_icon.py'])
    expect(shell.global).toBe(false)
    expect(shell.notes.join()).toMatch(/打包期图标生成/)
  })

  it('门禁自己的阈值与分区判据：改它由 vitest 验收，不是由浏览器验收', () => {
    const r = staysFast([
      'frontend/e2e/helpers/nightly-gates.mjs',
      'frontend/e2e/helpers/nightly-gates.d.mts',
      'frontend/e2e/helpers/pool-core.mjs',
    ])
    expect(r.global).toBe(false)
    expect(r.unit).toBe(true)
    // pool-core 的端口抢占只有实跑才现形 ⇒ note 必须把这条喊出来，不能静默放行
    expect(staysFast(['frontend/e2e/helpers/pool-core.mjs']).notes.join()).toMatch(/dry-run/)
  })

  it('门禁编排器自身：产品没动时浏览器全量验不出它的对错，但必须自证 dry-run', () => {
    const r = staysFast([
      'scripts/e2e_affected.mjs',
      'scripts/e2e_pool.mjs',
      'scripts/e2e_nightly.mjs',
      'scripts/e2e_preview_supervised.mjs',
      'scripts/affected-rules.mjs',
    ])
    expect(r.global).toBe(false)
    expect(r.unit).toBe(true)
    // 判据层有单测、IO 壳只剩 dry-run —— note 必须同时说清这两件事
    expect(r.notes.join()).toMatch(/IO 壳无单测.*dry-run/)
  })

  it('实测过的 25 提交里剩下的 6 个假阳性案例，逐个不再升级', () => {
    const cases = [
      ['.commandcode/settings.json', '.gitignore', '.lqdp_startup.lock', '.superpowers/brainstorm/a/b.html', 'frontend/.gitignore'],
      ['.gitignore', 'docs/tasks/lessons.md'],
      ['.github/workflows/ci.yml', 'docs/superpowers/specs/x.md'],
      ['frontend/test/unit/iconLib.spec.ts', 'scripts/icon-audit.cjs', 'scripts/icon-lib.cjs'],
      ['docs/tasks/todo.md', 'scripts/e2e_preview_supervised.mjs'],
      ['frontend/e2e/helpers/nightly-gates.d.mts', 'frontend/e2e/helpers/nightly-gates.mjs', 'frontend/test/unit/e2eNightlyGates.spec.ts'],
    ]
    for (const files of cases) expect(staysFast(files).global, files.join(',')).toBe(false)
  })
})

describe('真承重：兜底方向必须仍然是全量', () => {
  it('未被 T2 钉住的 e2e helper 一动等于全量（新 carve-out 没把它顺手放过）', () => {
    for (const f of ['frontend/e2e/helpers/auth.ts', 'frontend/e2e/helpers/colors.ts', 'frontend/e2e/fixtures/test-data.ts']) {
      expect(staysFast([f]).global, f).toBe(true)
    }
  })

  it('跑测试的配置与被测产品都算全局', () => {
    for (const f of ['frontend/playwright.config.ts', 'frontend/vite.config.ts', 'config/settings/base.py', 'manage.py', 'build.bat', 'frontend/src/stores/auth.ts']) {
      expect(staysFast([f]).global, f).toBe(true)
    }
  })

  it('migrations 与环境文件无条件全量（先于放行类目生效）', () => {
    expect(staysFast(['apps/sftp/migrations/0004_x.py']).global).toBe(true)
    expect(staysFast(['frontend/src/migrations/a.py']).global).toBe(true)
    expect(staysFast(['.env.prod']).global).toBe(true)
  })

  it('未知路径一律 GLOBAL —— 这条是整张表的安全边界，不许改成默认放行', () => {
    for (const f of ['random/foo.ts', 'worker/x.py', 'newdir/sub/y.vue']) {
      expect(staysFast([f]).global, f).toBe(true)
    }
  })

  it('模块数超过阈值即放弃选例（此前从没有测试压过这条分支）', () => {
    expect(MAX_MODULES_BEFORE_FULL).toBe(6)
    const within = ['admin', 'analysis', 'auth'].map((m) => `frontend/e2e/${m}/${m}.spec.ts`)
    expect(staysFast(within).global).toBe(false)
    const seven = ['admin', 'analysis', 'auth', 'batch', 'dashboard', 'data', 'settings']
      .map((m) => `frontend/e2e/${m}/${m}.spec.ts`)
    const r = staysFast(seven)
    expect(r.global).toBe(true)
    expect(r.reasons.join()).toMatch(/7 个模块 > 6 阈值/)
  })

  it('单模块改动走模块档，不升级', () => {
    const r = staysFast(['frontend/src/pages/sftp/SearchPage.vue', 'apps/sftp/views.py'])
    expect(r.global).toBe(false)
    expect(r.modules).toEqual(['sftp'])
  })
})

describe('后端标签与 e2e 选例正交', () => {
  it('apps/<app>/ 出标签，apps/*tests* 与 __init__ 不重复出', () => {
    expect(backendLabels(['apps/sftp/views/search.py', 'apps/sftp/tests_api.py'])).toEqual(['apps.sftp'])
    expect(backendLabels(['apps/__init__.py', 'apps/CLAUDE.md'])).toEqual([])
  })

  it('test/backend/ 出 test.backend，且不带任何 e2e 模块', () => {
    expect(backendLabels(['test/backend/test_sftp_pool.py'])).toEqual(['test.backend'])
    expect(staysFast(['test/backend/test_sftp_pool.py']).modules).toEqual([])
  })

  it('后端 app 的测试文件自身不牵动 e2e 选例', () => {
    const r = staysFast(['apps/analysis/tests_histogram.py'])
    expect(r.global).toBe(false)
    expect(r.modules).toEqual([])
  })
})

describe('编排内核：一档红不得吃掉后面的档', () => {
  /**
   * 假 runner：记下**实际被调用**的档名并返回预设退出码。
   * `seen` 是本文件唯一的承重项 —— 旧写法 `code ||= runPool('')` 的故障形状是
   * 「日志里根本没有 pool 那一档」，光看返回码永远测不出来。
   */
  function fakeRun(failsOn: string[] = []) {
    const seen: string[] = []
    const run = (s: { name: string }) => {
      seen.push(s.name)
      return failsOn.includes(s.name) ? 1 : 0
    }
    return { seen, run }
  }

  const plan = (files: string[], opts: { runBackend?: boolean; pytest?: boolean } = {}) =>
    planStages({ decision: decide(files), labels: backendLabels(files), pytest: true, ...opts })

  it('后端那档失败，T3 仍被排进计划并被执行（旧 ||= 短路的直接反证）', () => {
    const files = ['frontend/playwright.config.ts', 'apps/gage/gage_views.py']
    const stages = plan(files)
    expect(stages.map((s) => s.kind)).toEqual(['lint', 'unit', 'backend', 'pool'])
    const f = fakeRun(['backend'])
    const v = gateVerdict(executePlan(stages, f.run))
    expect(f.seen).toEqual(['lint:e2e', 'vitest', 'backend', 'e2e:全量'])
    expect(v).toEqual({ ok: false, failed: ['backend'], skipped: [] })
  })

  it('对照组：只改后端测试文件时计划里没有 pool 档（修法没把快档改成恒跑全量）', () => {
    const stages = plan(['test/backend/test_bin_grid_consistency.py'])
    expect(stages.map((s) => s.kind)).toEqual(['lint', 'unit', 'backend'])
    expect(gateVerdict(executePlan(stages, fakeRun().run)).ok).toBe(true)
  })

  it('兜底升级全量时只有一条 pool，不再叠 P0（同一批用例不得跑两遍）', () => {
    const pools = plan(['config/settings/base.py']).filter((s) => s.kind === 'pool')
    expect(pools).toHaveLength(1)
    expect(pools[0].name).toBe('e2e:全量')
    expect(pools[0].files).toBe('')
  })

  it('模块档与附带 P0 互不重叠，且合起来恰好覆盖全部 e2e 模块', () => {
    const pools = plan(['frontend/src/pages/sftp/SearchPage.vue']).filter((s) => s.kind === 'pool')
    expect(pools.map((s) => s.name)).toEqual(['e2e:sftp', 'e2e:附带P0'])
    expect(pools[1].pw).toBe('--project=P0')
    const dirs = pools.flatMap((s) => (s.files ?? '').split(' ').filter(Boolean))
    expect(new Set(dirs).size, dirs.join(',')).toBe(dirs.length)
    expect(dirs.length).toBe(MODULES.length)
  })

  it('该跑的档跑不了 = 本轮没结论：无 pytest 判 FAIL（旧写法只 print 就退 0）', () => {
    const stages = plan(['test/backend/test_bin_grid_consistency.py'], { pytest: false })
    const f = fakeRun()
    const results = executePlan(stages, f.run)
    expect(f.seen).toEqual(['lint:e2e', 'vitest']) // 后端档没有可执行的命令，但不能记成通过
    expect(gateVerdict(results).ok).toBe(false)
    expect(gateVerdict(results).failed).toEqual(['backend'])
    expect(results.find((r) => r.name === 'backend')?.aborted).toMatch(/pytest/)
  })

  it('显式 --no-backend 可以退 0，但必须进结论表的「跳档」，不能与跑过且绿长成一样', () => {
    const stages = plan(['test/backend/test_bin_grid_consistency.py'], { runBackend: false })
    const f = fakeRun()
    expect(gateVerdict(executePlan(stages, f.run))).toEqual({
      ok: true,
      failed: [],
      skipped: ['backend(--no-backend)'],
    })
    expect(f.seen).toEqual(['lint:e2e', 'vitest'])
  })

  it('计划是改动集的纯函数：同一改动集重复求计划，结果逐字相同（退出码无处影响它）', () => {
    const files = ['apps/sftp/views/search.py', 'frontend/src/pages/sftp/SearchPage.vue']
    expect(JSON.stringify(plan(files))).toBe(JSON.stringify(plan(files)))
  })
})

describe('池的命令构造：打印与执行必须同源', () => {
  const POOL = 'node scripts/e2e_pool.mjs --slots=auto'

  it('模块档的文件表必须进**执行**命令（旧写法只拼进 printCmd ⇒ 模块档偷偷跑全量）', () => {
    const { cmd, printCmd } = poolCmd({ files: 'e2e/analysis' })
    expect(cmd).toBe(`${POOL} -- e2e/analysis`)
    expect(printCmd.startsWith(cmd), 'printCmd 只能是 cmd 加注解，不能多于 cmd').toBe(true)
    // 多目录档也一样整串带上（空格分隔不是分隔符）
    expect(poolCmd({ files: 'e2e/admin e2e/auth' }).cmd).toBe(`${POOL} -- e2e/admin e2e/auth`)
  })

  it('全量档不带 `--`：给池留一个空文件表会让后面的 Playwright 开关被当成文件名', () => {
    const { cmd } = poolCmd({ files: '' })
    expect(cmd).toBe(POOL)
    // 注意判 `' -- '`（带尾空格）：`--slots=auto` 里也含 `--`，判前缀会误红
    expect(cmd.includes(' -- ')).toBe(false)
  })

  it('Playwright 开关只走 printCmd 的注解（真值是 E2E_PW_ARGS 环境变量），不进命令行', () => {
    const { cmd, printCmd } = poolCmd({ files: 'e2e/sftp', pw: '--project=P0' })
    expect(cmd).toBe(`${POOL} -- e2e/sftp`)
    expect(cmd).not.toContain('--project=P0')
    expect(printCmd).toContain('--project=P0')
  })

  it('模块目录必须先摊成 spec 文件：给池目录时权重查不到，autoSlots 会退回 1 slot 串行', () => {
    const list = (d: string) => (d === 'e2e/analysis' ? ['e2e/analysis/a.spec.ts', 'e2e/analysis/b.spec.ts'] : [])
    expect(expandPoolFiles(['e2e/analysis'], list)).toEqual(['e2e/analysis/a.spec.ts', 'e2e/analysis/b.spec.ts'])
    // 已经是文件的原样通过，不重复展开
    expect(expandPoolFiles(['e2e/sftp/x.spec.ts'], list)).toEqual(['e2e/sftp/x.spec.ts'])
    // 读不到的目录与空串给空数组 —— 调用方据此拒绝执行，而不是留个空文件表去跑全量
    expect(expandPoolFiles(['e2e/nope', ''], list)).toEqual([])
  })

  it('展开出来的文件表整串进**执行**命令（两条判据接起来才闭环）', () => {
    const list = (d: string) => [`${d}/a.spec.ts`, `${d}/b.spec.ts`]
    const files = expandPoolFiles(['e2e/analysis', 'e2e/theme'], list).join(' ')
    expect(files.split(' ')).toHaveLength(4)
    expect(poolCmd({ files }).cmd).toBe(`${POOL} -- ${files}`)
  })
})

describe('判定表的形状', () => {
  it('GLOBAL 令牌只有 `GLOBAL` 一个字面量，防止拼出第二个哨兵', () => {
    expect(GLOBAL).toBe('GLOBAL')
    expect(matchRule('config/settings/production.py')).toEqual([GLOBAL])
  })
})
