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
 * 跑：npm run test:unit
 */
import { describe, expect, it } from 'vitest'

import {
  GLOBAL,
  MAX_MODULES_BEFORE_FULL,
  backendLabels,
  decide,
  matchRule,
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
    expect(r.notes.join()).toMatch(/无单测|双向/)
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

describe('判定表的形状', () => {
  it('GLOBAL 令牌只有 `GLOBAL` 一个字面量，防止拼出第二个哨兵', () => {
    expect(GLOBAL).toBe('GLOBAL')
    expect(matchRule('config/settings/production.py')).toEqual([GLOBAL])
  })
})
