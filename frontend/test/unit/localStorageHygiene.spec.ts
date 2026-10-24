/**
 * T2：localStorage 只能经 `utils/safeStorage` 出入。
 *
 * 判据承重的方式与 `test/backend/test_subprocess_capture_hygiene.py` 同一套：
 * 先自证「扫描器抓得住那个形状、也不冤枉合规写法」，再对全仓下断言。
 * 少了前两条，这条绊线可能一直在比一个空集合。
 *
 * 为什么值得钉：Electron 的 userData 目录磁盘满/权限异常时 `localStorage.getItem`
 * 会抛 DOMException，而 `api/index.ts` 的请求拦截器在**每一个请求**上读 token ——
 * 一次抛错等于全站请求失败。封装早就有（DEV 下 warn、生产静默降级），
 * 但 api 层一直没接（2026-10-24 实测 4 处裸调），本批补上后由这里看着。
 */
import { readFileSync, readdirSync } from 'node:fs'
import * as path from 'node:path'
import { describe, expect, it } from 'vitest'

import { safeGetItem } from '../../src/utils/safeStorage'

const SRC_ROOT = new URL('../../src/', import.meta.url)
/** 封装本体是唯一允许直接摸 localStorage 的地方。 */
const ALLOWED = 'utils/safeStorage.ts'

const CALL_RE = /\blocalStorage\.(?:getItem|setItem|removeItem)\s*\(/

function tsFiles(dir: URL, base = ''): string[] {
  const out: string[] = []
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    const rel = base ? `${base}/${ent.name}` : ent.name
    if (ent.isDirectory()) out.push(...tsFiles(new URL(`${ent.name}/`, dir), rel))
    else if (/\.(ts|vue)$/.test(ent.name)) out.push(rel)
  }
  return out
}

/** 去掉**整行注释**（`//`、`*`、`/*` 开头）—— 源码里有 8 行注释提到「裸调 localStorage」，
 *  不按行剥就会把它们当违规；同时不碰行内 URL（`https://` 里的 `//` 不能当注释）。 */
function stripWholeLineComments(text: string): string {
  return text.split('\n').filter((line) => {
    const t = line.trim()
    return !(t.startsWith('//') || t.startsWith('*') || t.startsWith('/*'))
  }).join('\n')
}

function bareCalls(rel: string): number {
  const text = readFileSync(new URL(rel, SRC_ROOT), 'utf8')
  return stripWholeLineComments(text).split('\n').filter((l) => CALL_RE.test(l)).length
}

describe('扫描器自己先得当用', () => {
  it('抓得住代码行上的裸调用', () => {
    expect(CALL_RE.test("  const token = localStorage.getItem('access_token')")).toBe(true)
  })
  it('不冤枉整行注释里的提及', () => {
    const src = "// 此前裸调 localStorage.getItem 无 try/catch\nconst a = 1\n"
    expect(stripWholeLineComments(src).match(CALL_RE)).toBeNull()
  })
  it('不冤枉含 URL 的代码行', () => {
    const src = "const u = 'https://example.com/x' // 带两个斜杠的字符串\n"
    expect(stripWholeLineComments(src).split('\n').filter((l) => CALL_RE.test(l))).toHaveLength(0)
  })
})

describe('safeStorage 在非浏览器环境的行为', () => {
  it('localStorage 这个全局不存在时返回 null 而不是抛（api 层去掉 typeof 的依据）', () => {
    expect(() => safeGetItem('access_token')).not.toThrow()
    expect(safeGetItem('access_token')).toBeNull()
  })
})

describe('src/ 下不再有裸 localStorage 调用', () => {
  it('除 utils/safeStorage.ts 外，任何 .ts/.vue 都不得直接调 getItem/setItem/removeItem', () => {
    const offenders = tsFiles(SRC_ROOT)
      .filter((rel) => rel !== ALLOWED)
      .filter((rel) => bareCalls(rel) > 0)
    expect(offenders).toEqual([])
  })

  it('封装确实在被引用（防止「0 处裸调」是靠把封装一起删掉达成的）', () => {
    const importers = tsFiles(SRC_ROOT).filter((rel) => {
      if (rel === ALLOWED) return false
      const text = readFileSync(new URL(rel, SRC_ROOT), 'utf8')
      return /from '[^']*utils\/safeStorage'/.test(text)
    })
    expect(importers.length).toBeGreaterThanOrEqual(4)
    expect(importers).toContain('api/index.ts')
    expect(importers).toContain('api/auth.ts')
  })

  it('路径推导本身可复核：src 根下确实找得到那两个文件', () => {
    expect(path.basename(new URL('api/index.ts', SRC_ROOT).pathname)).toBe('index.ts')
    expect(tsFiles(SRC_ROOT).length).toBeGreaterThan(50)
  })
})
