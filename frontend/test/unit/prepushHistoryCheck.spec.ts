/**
 * T2：§6.5 push 前历史自检的判定内核（`scripts/prepush-history-check.mjs`）。
 *
 * 为什么值得单独钉：这道门管的是「公开仓库里冒出真实 gage 数据 / 密钥」，
 * 而它的故障形状是**静默**——2026-10-27 实测 `core.hooksPath` 指向一个不存在的目录时
 * `git push` 退 0 且零告警，四步散文一次都没执行。判据错了比没判据更糟，因为它是绿色的。
 *
 * 所以本文件双向：
 * - 「事故形状必须拦」用 2026-10-16 那笔的真形状（改忽略规则放开 `/Data/`）当夹具；
 * - 「合法形状必须放行」用**当下真在等待推送的那一笔**（2a313fc 只放行 `LATEST.md`）当夹具。
 *   只有后半边的门禁会在第一次使用时就被 `--no-verify` 绕过。
 *
 * 跑：npx vitest run（毫秒级，不开浏览器；同 `e2eAffectedDecide.spec.ts` 的口径）
 */
import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

import {
  ALLOWED_EXCEPTIONS,
  HARD_ROOTS,
  RANGE_ROOTS,
  classifyAdded,
  classifyIgnoreDrift,
  formatReport,
  guardRoot,
  hookWiring,
  parsePushRefs,
  secretMatch,
  verdictOf,
} from '../../../scripts/prepush-history-check.mjs'

const verdicts = (rows: { verdict: string }[]) => rows.map((r) => r.verdict)

/** 2a313fc 里 .gitignore 那一段的真实 diff（当下正在等待推送的形状）。 */
const REAL_LATEST_MD_HUNK = [
  '@@ -154,7 +154,13 @@ DEBUG_*.md',
  ' !/test/type-snapshot/',
  ' /test/type-snapshot/after.json',
  '-/tasks/',
  '+# 全量兜底轮的**结论表**要能被另一台检出读到（滚动 30 轮的墙钟/单价/flaky/VOID），',
  '+# 所以只放行 LATEST.md 这一个文件；latest.json、各轮明细目录、锁继续不入库。',
  '+# 顺序承重：父目录被排除时 `!` 无法重新纳入其中的文件，必须先放行目录、再排除内容、最后例外那一个。',
  '+/tasks/*',
  '+!/tasks/e2e-nightly/',
  '+/tasks/e2e-nightly/*',
  '+!/tasks/e2e-nightly/LATEST.md',
].join('\n')

/** 2026-10-16 事故的形状：不是多了一个文件，是摘掉了一条守卫规则。 */
const INCIDENT_UNIGNORE_DATADIR = ['-', '-/Data/', '+# 样例要进 CI，先放开'].join('\n')

describe('守卫根与放行表', () => {
  it('对照组：普通产品路径一条都不拦', () => {
    expect(classifyAdded(['frontend/src/pages/Analysis.vue', 'apps/datafiles/views.py', 'docs/reference/testing-gates.md'])).toEqual([])
  })

  it('Data/ 下的新增一律拦，且下一步按「可能已公开」口径说', () => {
    const rows = classifyAdded(['Data/SampleData/Gage/gage_m_S1.csv'])
    expect(rows).toHaveLength(1)
    expect(rows[0].verdict).toBe('BLOCK')
    expect(rows[0].next).toContain('GitHub 支持工单')
  })

  it('tasks/ 下没点名的文件也拦，但下一步只说本地重做（还没公开）', () => {
    const rows = classifyAdded(['tasks/scratch-notes.md'])
    expect(rows).toEqual([
      expect.objectContaining({ verdict: 'BLOCK', path: 'tasks/scratch-notes.md' }),
    ])
    expect(rows[0].next).toContain('git rm --cached tasks/scratch-notes.md')
    expect(rows[0].next).not.toContain('GitHub 支持工单')
  })

  it('放行表点名的文件不算命中——这正是当下那一笔 push 的形状', () => {
    const rows = classifyAdded(['tasks/e2e-nightly/LATEST.md'])
    expect(verdicts(rows)).toEqual(['ALLOWED'])
    expect(verdictOf(rows)).toBe('PASS')
  })

  it('每条放行都必须挂在守卫根下、且带着出处的引用，否则是没有主人的豁免', () => {
    expect(ALLOWED_EXCEPTIONS.length).toBeGreaterThan(0)
    for (const e of ALLOWED_EXCEPTIONS) {
      expect(guardRoot(e.path)).not.toBeNull()
      expect(e.why).toMatch(/§\d/)
    }
  })

  it('密钥形状在任何目录都拦', () => {
    for (const p of ['deploy/server_secret.key', 'config/.env.production', 'src/id_rsa', 'certs/apitoken.pfx'])
      expect(secretMatch(p), p).not.toBeNull()
    expect(secretMatch('config/settings.py')).toBeNull()
    expect(verdicts(classifyAdded(['deploy/server_secret.key']))).toEqual(['BLOCK'])
  })
})

describe('.gitignore 漂移', () => {
  it('当下真实那笔（只放行 LATEST.md）全绿', () => {
    const rows = classifyIgnoreDrift(REAL_LATEST_MD_HUNK)
    expect(verdictOf(rows)).toBe('PASS')
    expect(verdicts(rows)).toEqual(['OK', 'ALLOWED', 'ALLOWED'])
  })

  it('摘掉守卫根且没有新规则接着守 ⇒ 拦', () => {
    const rows = classifyIgnoreDrift(INCIDENT_UNIGNORE_DATADIR)
    expect(rows.filter((r) => r.verdict === 'BLOCK').map((r) => r.path)).toEqual(['/Data/'])
    expect(rows[0].next).toContain('单独一笔提交')
  })

  it('摘掉守卫根但同时改写同根规则 ⇒ 只算改写，不拦', () => {
    expect(verdictOf(classifyIgnoreDrift('-/tasks/\n+/tasks/*'))).toBe('PASS')
  })

  it('用通配重新纳入 ⇒ 一律拦，哪怕字面上像例外', () => {
    const rows = classifyIgnoreDrift('+!/Data/**')
    expect(verdicts(rows)).toEqual(['BLOCK'])
  })

  it('例外收回时提醒放行表要跟着摘（防放行表烂掉）', () => {
    const rows = classifyIgnoreDrift('-!/tasks/e2e-nightly/LATEST.md')
    expect(verdicts(rows)).toEqual(['STALE'])
    expect(rows[0].next).toContain('ALLOWED_EXCEPTIONS')
  })

  it('上下文行与注释行不参与判定', () => {
    expect(classifyIgnoreDrift(' /tasks/\n+# 提到 /Data/ 只是说明\n+++ b/.gitignore')).toEqual([])
  })
})

describe('钩子 stdin 的范围解析', () => {
  const sha = (c: string) => c.repeat(40)

  it('已是最新那一行 git 照样喂，必须跳过（2026-10-27 实测）', () => {
    expect(parsePushRefs(`refs/heads/master ${sha('a')} refs/heads/master ${sha('a')}\n`)).toEqual([])
  })

  it('删远端分支没有内容带出去，跳过', () => {
    expect(parsePushRefs(`(delete) ${sha('0')} refs/heads/topic ${sha('b')}\n`)).toEqual([])
  })

  it('前进推送解析出基线与目标', () => {
    const [ref] = parsePushRefs(`refs/heads/master ${sha('b')} refs/heads/master ${sha('a')}\n`)
    expect(ref).toMatchObject({ remoteSha: sha('a'), localSha: sha('b'), isNewBranch: false })
  })

  it('新分支（远端全 0）标出来，因为没有已发布基线可比', () => {
    const [ref] = parsePushRefs(`refs/heads/topic ${sha('c')} refs/heads/topic ${sha('0')}\n`)
    expect(ref.isNewBranch).toBe(true)
  })
})

describe('本机钩子接线自检', () => {
  it('hooksPath 指向没有 pre-push 的目录 ⇒ DEAD（就是 2026-10-27 本机那个状态）', () => {
    const w = hookWiring({ hooksPath: 'C:/gone/DataPhrase_Django/.git/hooks', hasPushHook: false, nodeAvailable: true })
    expect(w.state).toBe('DEAD')
    expect(w.why).toContain('没有 pre-push')
  })

  it('钩子在但 node 不在 PATH ⇒ 也判 DEAD，别让人以为门还在', () => {
    expect(hookWiring({ hooksPath: 'githooks', hasPushHook: true, nodeAvailable: false }).state).toBe('DEAD')
  })

  it('装好了才 ACTIVE', () => {
    expect(hookWiring({ hooksPath: 'githooks', hasPushHook: true, nodeAvailable: true }).state).toBe('ACTIVE')
  })
})

describe('输出与文档同源', () => {
  it('结论行永远是最后一行（§1 的 RESULT: 纪律）', () => {
    const text = formatReport({
      source: 'test',
      blocks: [{ label: 'origin/master..HEAD', commits: [], rows: classifyAdded(['Data/x.csv']) }],
      tripwireRows: [],
      tripwireTip: 'origin/master',
      tripwireSkipped: null,
    })
    expect(text.split('\n').at(-1)).toBe('RESULT: FAIL')
  })

  it('绊线为空也要打出来，否则分不清「跑了且干净」与「压根没跑」', () => {
    const text = formatReport({
      source: 'test',
      blocks: [],
      tripwireRows: [],
      tripwireTip: 'origin/master',
      tripwireSkipped: null,
    })
    for (const root of HARD_ROOTS) expect(text).toContain(`${root.prefix} —— 无新增`)
  })

  it('脚本里的守卫根，§6.5 正文必须逐条点名（防两边各改各的）', () => {
    const doc = readFileSync(new URL('../../../docs/reference/testing-gates.md', import.meta.url), 'utf8')
    const section = doc.slice(doc.indexOf('## 6.5'), doc.indexOf('## 7.'))
    expect(section).not.toBe('')
    for (const root of [...HARD_ROOTS, ...RANGE_ROOTS]) expect(section).toContain(root.prefix)
    expect(section).toContain('密钥')
  })
})
