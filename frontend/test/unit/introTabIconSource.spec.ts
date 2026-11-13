/**
 * T2：介绍书标签页图标的**源侧**判据（一条都不会 skip）。
 *
 * 为什么需要这一层：那条契约的另外两个消费者都可能读不到源码 ——
 *  - T1 `test/backend/test_intro_serving.py`：`docs/intro/.vitepress/dist` 不在时整条 skip，
 *    而 dist **不入库**（`.gitignore:223`），CI 的后端档也不跑 `intro:build`；
 *  - T3 `frontend/e2e/theme/intro-favicon.spec.ts`：要真浏览器 + 真产物，而
 *    `.github/workflows/ci.yml` 只有「后端全量 / build / vitest / lint:e2e」四档，
 *    **没有任何 Playwright 步骤**。
 * ⇒ 「改了 config.mts 忘了重跑 intro:build」和「CI 里这条判据根本不存在」两件事叠在一起时，
 * 唯一还站得住的自动化判据就是直接读声明本身。本文件不替代 T1/T3 的产物侧判据，只补源侧。
 *
 * 判据形状照 `e2eAuthStateHygiene.spec.ts` / `localStorageHygiene.spec.ts`：先自证抽取器抓得住、
 * 也不冤枉别的写法（含「rel=icon 写在 head 外面」这一种），再对真源码下断言。
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

/** 介绍书 VitePress 配置源码（`head` 数组是 `<link>` 的唯一来源） */
const vitepressConfig = () =>
  readFileSync(new URL('../../../docs/intro/.vitepress/config.mts', import.meta.url), 'utf8')

/** Django 侧的挂载表（`/favicon.ico` 兜底路由与 `/favicon.svg` 真资产都在里面） */
const djangoUrls = () => readFileSync(new URL('../../../config/urls.py', import.meta.url), 'utf8')

/**
 * 取 `head:` 那**一个数组本体**（VitePress 的写法是 `[['link', {...}], ['meta', {...}]]`，一层嵌套）。
 * 只认这一段：数组外面出现的 `rel: 'icon'` 一律不算数 —— 否则「把声明挪出 head」或「在注释里留一份
 * 旧声明」都会让这条恒绿，而构建产物里根本没有那个 `<link>`。
 */
function headEntries(src: string): string[] {
  const m = /head:\s*\[((?:[^\[\]]|\[[^\[\]]*\])*)\]/.exec(src)
  if (!m) throw new Error('config.mts 里找不到 head 数组本体 ⇒ 「声明标签页图标」这件事的前提已经没了')
  return m[1].split(/\]\s*,\s*\[/).map((e) => e.trim())
}

/** head 里那条 `rel: 'icon'` 的 href；没有就带上下文红掉，不返回 undefined 让调用方 `!` 出 TypeError */
function declaredIconHref(src: string): string {
  const hit = headEntries(src).find((e) => /rel:\s*['"]icon['"]/.test(e))
  if (!hit) throw new Error(`head 的 ${headEntries(src).length} 条里没有 rel=icon 的条目`)
  const href = /href:\s*['"]([^'"]+)['"]/.exec(hit)
  if (!href) throw new Error(`rel=icon 那条没有 href：${hit}`)
  return href[1]
}

describe('抽取器本身（先自证，再对真源码下断言）', () => {
  const real = vitepressConfig()

  it('真源码的 head 里确实有一条 rel=icon，且 href 是绝对根路径', () => {
    // base 是 `/intro/`，相对 href（`favicon.svg`）会被解析成 /intro/favicon.svg，
    // 而那份文件挂在站点根（config/urls.py）⇒ 必须写 `/favicon.svg`
    expect(declaredIconHref(real)).toBe('/favicon.svg')
  })

  it('rel=icon 写在 head 数组外面 ⇒ 抽取器不认（挡住「挪出 head」与「注释里留一份」）', () => {
    const decoy = `export default defineConfig({\n  head: [['meta', { name: 'x', content: 'y' }]],\n`
    const outside = `${decoy}  // rel: 'icon', href: '/favicon.svg'\n})`
    expect(() => declaredIconHref(outside)).toThrow(/没有 rel=icon/)
  })

  it('head 整个没了 ⇒ 硬失败，不静默给 undefined', () => {
    expect(() => declaredIconHref('export default defineConfig({ lang: \'zh-CN\' })')).toThrow(/head 数组本体/)
  })

  it('rel=icon 有条目但没 href ⇒ 报的是那条的内容，不是 TypeError', () => {
    const src = `head: [['link', { rel: 'icon', type: 'image/svg+xml' }]]`
    expect(() => declaredIconHref(src)).toThrow(/没有 href/)
  })
})

describe('声明与 Django 侧复用同一份资产', () => {
  it('/favicon.ico 兜底路由喂的就是 head 里指的那一份', () => {
    const href = declaredIconHref(vitepressConfig())
    const served = /path\(\s*['"]favicon\.ico['"]\s*,\s*_serve_frontend_file\(\s*['"]([^'"]+)['"]/.exec(
      djangoUrls(),
    )
    expect(
      served,
      'urls.py 里没有把 /favicon.ico 转到某份资产的路由 ⇒ 该请求会落 SPA catch-all，拿到 200 + text/html 的壳',
    ).not.toBeNull()
    // 两边写的是同一个文件名才算同源：head 指 /favicon.svg、兜底路由喂 favicon.svg
    expect(served![1]).toBe(href.replace(/^\//, ''))
  })
})
