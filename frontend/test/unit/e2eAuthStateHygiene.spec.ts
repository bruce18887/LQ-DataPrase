/**
 * T2：e2e 用例里禁止写 storageState 的**字面量路径**。
 *
 * 承重方式与 `localStorageHygiene.spec.ts` 同一套：先自证扫描器抓得住那个形状、也不冤枉两种合规
 * 写法，再对全仓下断言 —— 少了前两条，这条绊线可能一直在比一个空集合。
 *
 * 为什么要钉：四个业务项目的 `use.storageState` 已经是 slot-aware 的 `ADMIN_STATE`
 * （`playwright.config.ts:121/130/137/144`，由 `e2e/helpers/slot.ts` 按 slot.json 算），所以用例侧
 * 再写一遍**本来就是多余的**；而它有害是因为池档（slot）里 slot 的 admin.json 在
 * `C:\lqdp-e2e\slots\<run>\slotN\auth\`，字面量读到的是上一次**串行**跑留下的旧 `SECRET_KEY` 签的
 * token ⇒ 401 ⇒ 守卫弹回 `/login` ⇒ 整个文件红在 `gotoApp` 的 `.main-layout` 上，判据一条都没跑到。
 * 2026-11-14 批1 收口全量池就是这么抓到一个文件（`param-dropdown-full-list.spec.ts`，5 条全红，
 * 而它单跑 `--project=P1` 连续多轮全绿）。教训全文见 `docs/tasks/lessons.md` 同日条目。
 */
import { readFileSync, readdirSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const E2E_ROOT = new URL('../../e2e/', import.meta.url)

/** 只抓「写成字符串路径」这一种；`{ cookies: … }`（清空）与裸标识符（继承/传常量）都放行 */
const LITERAL_STATE_RE = /storageState:\s*['"]/

function specFiles(dir: URL, base = ''): string[] {
  const out: string[] = []
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const rel = base ? `${base}/${ent.name}` : ent.name
    if (ent.isDirectory()) out.push(...specFiles(new URL(`${ent.name}/`, dir), rel))
    else if (/\.ts$/.test(ent.name)) out.push(rel)
  }
  return out
}

describe('扫描器本身（正负对照，先自证再下断言）', () => {
  it('抓住字面量路径的两种写法', () => {
    expect(LITERAL_STATE_RE.test(`test.use({ storageState: 'e2e/.auth/admin.json' })`)).toBe(true)
    expect(LITERAL_STATE_RE.test('storageState: "frontend/e2e/.auth/user.json"')).toBe(true)
  })

  it('不冤枉两种合规写法：清空成空对象、以及传 slot-aware 常量', () => {
    expect(LITERAL_STATE_RE.test('test.use({ storageState: { cookies: [], origins: [] } })')).toBe(false)
    expect(LITERAL_STATE_RE.test('use: { storageState: ADMIN_STATE }')).toBe(false)
  })

  it('扫到的文件数不是零（否则下面那条恒真）', () => {
    expect(specFiles(E2E_ROOT).length).toBeGreaterThan(40)
  })
})

describe('全仓 e2e 不许有 storageState 字面量路径', () => {
  it('逐文件扫 e2e/**/*.ts，零命中', () => {
    const hits = specFiles(E2E_ROOT)
      .map((rel) => {
        const lines = readFileSync(new URL(rel, E2E_ROOT), 'utf8').split('\n')
        return lines
          .map((line, i) => ({ line, no: i + 1 }))
          .filter(({ line }) => LITERAL_STATE_RE.test(line))
          .map(({ line, no }) => `${rel}:${no}: ${line.trim()}`)
      })
      .flat()
    expect(
      hits,
      `写死 storageState 路径的用例在池档（slot）里会读到旧 SECRET_KEY 的 token ⇒ 整文件红在登录那一步。` +
        `正确做法：不写（继承项目级 ADMIN_STATE），或清空成 { cookies: [], origins: [] } 再走 loginAs。命中：\n${hits.join('\n')}`,
    ).toEqual([])
  })
})
