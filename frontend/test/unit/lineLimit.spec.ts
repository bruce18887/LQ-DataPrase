/**
 * T2：600 行硬约束的机械 owner（`scripts/line-limit.mjs` + 仓库实测）。
 *
 * 规则正文与适用面在 `.claude/CLAUDE.md`「600 行约束的适用面」一节。这条约束从写下起到 2026-10-27
 * 只有散文、没有任何检查：`docs/tasks/todo.md`「留给拍板」第 6 条当天复核过，
 * `grep -rn "600" scripts/*.mjs` 命中的**全是 `60000` 毫秒换算**，依赖清单里也没有
 * ruff/flake8/ESLint/Prettier/stylelint。结果就是 `tests_jobs.py` 从新建一路长到 846 行无人量过。
 * ⚠ 今天起那条 grep 会多命中本文件所钉的内核 —— 命中它才算这条绊线挂上了。
 *
 * 承重方式与本仓两条既有纪律同构：
 * - 先自证扫描器抓得住那个形状、也不冤枉合规写法，再对全仓下断言
 *   （`localStorageHygiene.spec.ts` 与 `test/backend/test_subprocess_capture_hygiene.py` 同一套）；
 *   少了自证，这条绊线可能一直在比一个空集合。
 * - 基线用**精确计数**而不是 `> 0`：违规集合必须逐字等于豁免账，行数精确到个位。
 *
 * 跑：`cd frontend && npm run test:unit`（CI 已含这一步）。不需要浏览器。
 */
import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import {
  EXEMPT,
  LINE_LIMIT,
  SCOPE_PATHSPECS,
  countLines,
  findStaleExemptions,
  findViolations,
  formatViolation,
  isTestFile,
  ownerOf,
  splitHint,
} from '../../../scripts/line-limit.mjs'

const REPO_ROOT = new URL('../../../', import.meta.url)

/** IO 壳：被 git 跟踪的适用面文件 + 各自行数。判据一律在纯函数里。 */
function scanScope() {
  const out = execFileSync('git', ['ls-files', ...SCOPE_PATHSPECS], {
    cwd: fileURLToPath(REPO_ROOT),
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  })
  return out
    .split('\n')
    .filter(Boolean)
    .map((rel) => ({ path: rel, lines: countLines(readFileSync(new URL(rel, REPO_ROOT), 'utf8')) }))
}

const entries = scanScope()
const overLimit = entries.filter((e) => e.lines > LINE_LIMIT)

describe('判定内核自证（先证明抓得住，再对全仓下断言）', () => {
  it('行数口径：末尾换行不算一行，CRLF 与 LF 同值', () => {
    expect(countLines('a\nb\nc\n')).toBe(3)
    expect(countLines('a\nb\nc')).toBe(3)
    expect(countLines('a\r\nb\r\nc\r\n')).toBe(3)
    expect(countLines('')).toBe(0)
    expect(countLines('\n')).toBe(1)
  })

  it('不在豁免账里的超限文件必须报红，且 kind=new', () => {
    const v = findViolations([{ path: 'apps/x/views.py', lines: 601 }], { exempt: [] })
    expect(v).toHaveLength(1)
    expect(v[0].kind).toBe('new')
  })

  it('恰好 600 行不报（阈值是「不能超过 600」，601 才算破线）', () => {
    expect(findViolations([{ path: 'apps/x/views.py', lines: 600 }], { exempt: [] })).toEqual([])
  })

  it('豁免只免到登记的精确行数：多一行就报红，kind=grew 且带上长了多少', () => {
    const exempt = [{ path: 'apps/x/tests.py', lines: 700, reason: '测试用' }]
    expect(findViolations([{ path: 'apps/x/tests.py', lines: 700 }], { exempt })).toEqual([])
    const v = findViolations([{ path: 'apps/x/tests.py', lines: 701 }], { exempt })
    expect(v).toEqual([{ path: 'apps/x/tests.py', lines: 701, limit: 600, kind: 'grew', frozenLines: 700 }])
  })

  it('反向也要拦：豁免账里的文件拆小或删掉后，名单不许继续留着（防单向膨胀）', () => {
    const exempt = [{ path: 'apps/x/tests.py', lines: 700, reason: '测试用' }]
    expect(findStaleExemptions([{ path: 'apps/x/tests.py', lines: 500 }], { exempt })).toHaveLength(1)
    expect(findStaleExemptions([], { exempt })[0].why).toMatch(/不存在/)
    expect(findStaleExemptions([{ path: 'apps/x/tests.py', lines: 700 }], { exempt })).toEqual([])
  })

  it('豁免账重复写同一个路径要当场炸，而不是静默取一条', () => {
    const dup = [
      { path: 'a.py', lines: 700, reason: 'x' },
      { path: 'a.py', lines: 800, reason: 'y' },
    ]
    expect(() => findViolations([{ path: 'a.py', lines: 900 }], { exempt: dup })).toThrow(/写了两次/)
  })

  it('红字必须含 owner 与拆分建议（只报「超限」等于把活推给下一个人重新踩坑）', () => {
    const text = formatViolation({ path: 'apps/x/views.py', lines: 900, limit: 600, kind: 'new', frozenLines: null })
    expect(text).toMatch(/owner: Django app `apps\/x`/)
    expect(text).toMatch(/拆分建议/)
    expect(text).toMatch(/patch_df_loader/)
    expect(text).toMatch(/EXEMPT/)
  })

  it('拆分建议按文件形状给，各自的既有坑都带在字面上', () => {
    expect(splitHint('frontend/src/pages/data/FileManager.vue')).toMatch(/composable/)
    // 后端测试拆分的两条硬约束：CI 没装 pytest；新子目录缺包标记 = 用例静默消失
    expect(splitHint('apps/jobs/tests_jobs.py')).toMatch(/不得 `import pytest`/)
    expect(splitHint('apps/jobs/tests_jobs.py')).toMatch(/__init__/)
    expect(splitHint('frontend/e2e/data/data.spec.ts')).toMatch(/lint:e2e/)
    // 产品代码：2026-10-16 那条「按 600 行拆 mixin 引爆 patch 绑定」的教训必须在字面上
    expect(splitHint('apps/analysis/views/analysis_views.py')).toMatch(/各自独立的绑定/)
    expect(ownerOf('weird/unknown/file.py')).toMatch(/未归类/)
    expect(ownerOf('frontend/e2e/data/x.spec.ts')).toMatch(/T3/)
  })

  it('测试件分类要判别得住：两种命名各抓得住，也不把业务文件误判成测试', () => {
    // 「业务侧 0 件」那条断言全靠这个谓词，它自己必须先被钉住。
    expect(isTestFile('apps/datafiles/tests.py')).toBe(true)
    expect(isTestFile('apps/jobs/tests_jobs.py')).toBe(true)
    expect(isTestFile('test/backend/test_sftp_search_engine_stream.py')).toBe(true)
    expect(isTestFile('frontend/e2e/data/view-data.spec.ts')).toBe(true)
    expect(isTestFile('frontend/test/unit/lineLimit.spec.ts')).toBe(true)
    expect(isTestFile('apps/analysis/views/analysis_views.py')).toBe(false)
    expect(isTestFile('frontend/src/pages/data/DataBrowserAgGrid.vue')).toBe(false)
    expect(isTestFile('standalone.py')).toBe(false)
  })
})

describe('适用面的取法本身得承重', () => {
  it('三类扩展名各至少抓到一件真实文件（pathspec 拼错时这里先红，而不是全仓比空集合）', () => {
    const has = (re: RegExp) => entries.some((e) => re.test(e.path))
    expect(has(/\.py$/)).toBe(true)
    expect(has(/\.ts$/)).toBe(true)
    expect(has(/\.vue$/)).toBe(true)
    expect(entries.some((e) => e.path === 'manage.py')).toBe(true)
    expect(overLimit.length).toBe(EXEMPT.length)
  })
})

describe('今天的基线（2026-10-27 用 git ls-files 现算）', () => {
  it('超阈集合逐字等于豁免账：五件，行数精确到个位', () => {
    expect(overLimit.map((e) => ({ path: e.path, lines: e.lines })).sort((a, b) => (a.path < b.path ? -1 : 1))).toEqual(
      EXEMPT.map((e) => ({ path: e.path, lines: e.lines })).sort((a, b) => (a.path < b.path ? -1 : 1)),
    )
  })

  it('五件全是测试文件，业务代码一件没有（这正是适用面必须写明「覆盖测试文件」的理由）', () => {
    const product = overLimit.filter((e) => !isTestFile(e.path)).map((e) => e.path)
    expect(product, `业务代码里出现超限件：${product.join(', ')}`).toEqual([])
    expect(overLimit.filter((e) => isTestFile(e.path))).toHaveLength(5)
  })

  it('违规集合为空 —— 新增超限文件、或豁免件再长行，都会让这条变红', () => {
    const v = findViolations(entries)
    expect(v, `600 行硬约束破了 ${v.length} 处：\n${v.map(formatViolation).join('\n\n')}`).toEqual([])
  })

  it('豁免账没有陈旧条目', () => {
    const stale = findStaleExemptions(entries)
    expect(stale, `EXEMPT 里有陈旧登记，拆完要一起销掉：\n${stale.map((s) => `${s.path}: ${s.why}`).join('\n')}`).toEqual(
      [],
    )
  })

  it('阈值只有一个来源：正文里写的数与内核常量一致', () => {
    expect(LINE_LIMIT).toBe(600)
    const rule = readFileSync(new URL('../../../.claude/CLAUDE.md', import.meta.url), 'utf8')
    expect(rule).toMatch(/行数不能超过600行/)
    expect(rule).toMatch(/## 600 行约束的适用面/)
  })
})
