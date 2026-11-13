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
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

/** 介绍书 VitePress 配置源码（`head` 数组是 `<link>` 的唯一来源） */
const vitepressConfig = () =>
  readFileSync(new URL('../../../docs/intro/.vitepress/config.mts', import.meta.url), 'utf8')

/** Django 侧的挂载表（`/favicon.ico` 兜底路由与 `/favicon.svg` 真资产都在里面） */
const djangoUrls = () => readFileSync(new URL('../../../config/urls.py', import.meta.url), 'utf8')

describe('介绍书标签页图标的声明（源侧）', () => {
  it('head 里声明了 rel=icon 的 link，且 href 是绝对根路径', () => {
    const m = /head:\s*\[[\s\S]*?rel:\s*['"]icon['"][\s\S]*?href:\s*['"]([^'"]+)['"]/.exec(vitepressConfig())
    expect(m, 'config.mts 的 head 里没有 rel=icon 的 link ⇒ 构建产物就不会有 <link>，标签页空白').not.toBeNull()
    // 必须是 `/favicon.svg` 这种绝对路径：`base: '/intro/'` 会把相对 href 解析成 /intro/favicon.svg，
    // 而那份文件挂在站点根（config/urls.py），/intro/ 前缀下没有
    expect(m![1]).toBe('/favicon.svg')
  })

  it('浏览器兜底请求 /favicon.ico 复用的正是 head 里声明的那一份资产', () => {
    const href = /head:\s*\[[\s\S]*?rel:\s*['"]icon['"][\s\S]*?href:\s*['"]([^'"]+)['"]/.exec(
      vitepressConfig(),
    )![1]
    const served = /path\(\s*['"]favicon\.ico['"]\s*,\s*_serve_frontend_file\(\s*['"]([^'"]+)['"]/.exec(djangoUrls())
    expect(served, 'urls.py 里没有把 /favicon.ico 转到某份资产的路由 ⇒ 该请求会落 SPA catch-all').not.toBeNull()
    // 两边写的是同一个文件名才算同源：head 指 /favicon.svg、兜底路由喂 favicon.svg
    expect(served![1]).toBe(href.replace(/^\//, ''))
  })
})
