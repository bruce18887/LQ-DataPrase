/**
 * T2：e2e 用例里禁止写 storageState 的**字面量路径**（也禁止绕道变量塞进去）。
 *
 * 承重方式与 `localStorageHygiene.spec.ts` 同一套：先自证扫描器抓得住每一种形状、也不冤枉合规
 * 写法，再对全仓下断言 —— 少了前两条，这条绊线可能一直在比一个空集合，或者只会抓最笨的那一种。
 *
 * 为什么要钉：四个业务项目的 `use.storageState` 早就是 slot-aware 的 `ADMIN_STATE`
 * （`playwright.config.ts:121/130/137/144`，由 `e2e/helpers/slot.ts` 按 slot.json 算），所以用例侧
 * 再写一遍**本来就是多余的**；而它有害是因为池档（slot）里 slot 的 admin.json 在
 * `C:\lqdp-e2e\slots\<run>\slotN\auth\`，字面量读到的是上一次**串行**跑留下的旧 `SECRET_KEY` 签的
 * token ⇒ 401 ⇒ 守卫弹回 `/login` ⇒ 整个文件红在 `gotoApp` 的 `.main-layout` 上，判据一条都没跑到。
 * 2026-11-14 批1 收口全量池就是这么抓到一个文件（`param-dropdown-full-list.spec.ts`，5 条全红，
 * 而它单跑 `--project=P1` 连续多轮全绿）。教训全文见 `docs/tasks/lessons.md` 同日条目。
 *
 * 合规写法只有两种：① 不写（继承项目级 ADMIN_STATE）；② 显式清空成 `{ cookies: [], origins: [] }`
 * 再走 `loginAs`（`e2e/admin/admin.spec.ts:54` 等 18 处的既有形状）。标识符只放行 slot.ts 导出的那两个。
 */
import { readFileSync, readdirSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const E2E_ROOT = new URL('../../e2e/', import.meta.url)

/** 允许出现在 `storageState:` 右边的标识符：slot.ts 算出来的两份登录态 */
const ALLOWED_IDENTIFIERS = new Set(['ADMIN_STATE', 'USER_STATE'])

/** `\s*` 而不是 `[ ]*`：值写在下一行那种换行写法同样要抓；`g` 供 matchAll 全文扫 */
const VALUE_RE = /storageState:\s*(?:(['"`])|([A-Za-z_$][\w$]*)|(\{))/g

/** 注释行不参与判定：本批就有三份注释在解释「admin.json 登录态」，把注释算进来就是假红 */
const isComment = (line: string) => /^\s*(\/\/|\*|\/\*)/.test(line)

function tsFiles(dir: URL, base = ''): string[] {
  const out: string[] = []
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const rel = base ? `${base}/${ent.name}` : ent.name
    if (ent.isDirectory()) out.push(...tsFiles(new URL(`${ent.name}/`, dir), rel))
    else if (/\.ts$/.test(ent.name)) out.push(rel)
  }
  return out
}

/** 一段源码里所有**不合规**的 storageState 写法（值写在下一行、模板串、绕变量都要抓到） */
export function findBadStorageState(src: string): string[] {
  // 注释行原地抹平（保留长度与换行）：既不让注释里那份字面量造成假红，也不打乱按偏移算行号
  const scan = src.split('\n').map((l) => (isComment(l) ? l.replace(/\S/g, ' ') : l)).join('\n')
  const lines = src.split('\n')
  const hits: string[] = []
  for (const m of scan.matchAll(VALUE_RE)) {
    const line = scan.slice(0, m.index).split('\n').length
    const why = m[1] ? '字面量路径' : m[2] && !ALLOWED_IDENTIFIERS.has(m[2]) ? '绕道变量' : null
    if (why) hits.push(`${why} → 第 ${line} 行 ${lines[line - 1].trim()}`)
  }
  return hits
}

describe('扫描器本身（先把每一种形状与两种合规写法都自证一遍）', () => {
  const cases: Array<[string, boolean]> = [
    [`test.use({ storageState: 'e2e/.auth/admin.json' })`, true],
    ['test.use({ storageState: "frontend/e2e/.auth/user.json" })', true],
    ['test.use({ storageState: `e2e/.auth/admin.json` })', true],
    ["const s = 'e2e/.auth/admin.json'; test.use({ storageState: s })", true],
    ['use: { storageState: SOME_OTHER_CONSTANT }', true],
    ["test.use({\n  storageState: 'e2e/.auth/admin.json',\n})", true],
    ['test.use({\n  storageState: ADMIN_STATE,\n})', false],
    ['test.use({ storageState: { cookies: [], origins: [] } })', false],
    ['use: { ...devices["Desktop Edge"], storageState: USER_STATE }', false],
    ['// 旧实现这里写的是 storageState: \'e2e/.auth/admin.json\'，别学', false],
  ]
  for (const [src, bad] of cases) {
    it(`${bad ? '抓住' : '放过'}：${src.replace(/\s+/g, ' ').slice(0, 52)}`, () => {
      expect(findBadStorageState(src).length > 0).toBe(bad)
    })
  }

  it('扫到的 ts 文件数不是零（否则下面那条恒真）', () => {
    expect(tsFiles(E2E_ROOT).length).toBeGreaterThan(40)
  })
})

describe('全仓 e2e 不许有 storageState 字面量路径 / 绕道变量', () => {
  it('逐文件扫 e2e/**/*.ts，零命中', () => {
    const hits = tsFiles(E2E_ROOT)
      .flatMap((rel) => findBadStorageState(readFileSync(new URL(rel, E2E_ROOT), 'utf8')).map((h) => `${rel}: ${h}`))
    expect(
      hits,
      '写死（或绕变量塞进）storageState 路径的用例在池档（slot）里会读到旧 SECRET_KEY 签的 token ⇒ ' +
        '整文件红在登录那一步。合规写法只有两种：不写（继承项目级 ADMIN_STATE），或清空成 ' +
        `{ cookies: [], origins: [] } 再走 loginAs。命中：\n${hits.join('\n')}`,
    ).toEqual([])
  })
})
