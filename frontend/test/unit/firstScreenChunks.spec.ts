import { existsSync, readFileSync, statSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

/**
 * 首屏 chunk 清单绊线。
 *
 * 根因（2026-10-27 用 hidden sourcemap 取证）：`vite.config.ts` 的函数式 manualChunks
 * 返回值在 rolldown 合并阶段只是建议，`@vue/{shared,reactivity,runtime-core,runtime-dom}`
 * 被并进了 ag-grid-vendor —— 于是**每个** chunk（含登录页）都要下载 1.19MB 才拿到
 * createApp。改成 `codeSplitting.groups` + priority 后首屏从 2,994,611B 降到 1,483,213B。
 *
 * 这条断言的作用是：将来任何人（包括下一次 rolldown 升级改变合并策略）把重型 vendor
 * 拉回首屏时，不必再靠肉眼读 index.html 才发现。
 *
 * 只在 `npm run build` 之后承重：CI 的顺序是 build → test:unit
 * （.github/workflows/ci.yml:72-76），本地只跑 vitest 时 dist 可能不存在，
 * 按本仓既有判例（缺夹具显式 skip，不让它 error 成假红）跳过而不是报错。
 */
const DIST = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'dist')
const HTML = join(DIST, 'index.html')
const built = existsSync(HTML)

/** 浏览器为「进入应用」真正要下载的字节：入口 JS + 全部 modulepreload JS + 全部 stylesheet */
function firstScreen() {
  const html = readFileSync(HTML, 'utf8')
  // base 有两种形态：Web 用 /assets/，Electron 打包用 ./assets/（vite.config.ts:31）
  const js = [
    ...html.matchAll(/<script type="module"[^>]*src="\.?\/assets\/([^"]+)"/g),
    ...html.matchAll(/<link rel="modulepreload"[^>]*href="\.?\/assets\/([^"]+)"/g),
  ].map((m) => m[1])
  const css = [...html.matchAll(/<link rel="stylesheet"[^>]*href="\.?\/assets\/([^"]+)"/g)]
    .map((m) => m[1])
  const bytes = (files: string[]) =>
    files.reduce((sum, f) => sum + statSync(join(DIST, 'assets', f)).size, 0)
  return { js, css, jsBytes: bytes(js), cssBytes: bytes(css) }
}

describe.skipIf(!built)('首屏 chunk 清单（依赖 npm run build 产物）', () => {
  const screen = firstScreen()

  it('探针本身有效：入口至少拉到 3 个 JS、1 个 CSS', () => {
    // 没有这条，正则一旦因 HTML 形状改变而失配，下面的断言会「空集合 = 通过」地假绿。
    expect(screen.js.length).toBeGreaterThanOrEqual(3)
    expect(screen.css.length).toBeGreaterThanOrEqual(1)
  })

  it('重型 vendor 不得进首屏', () => {
    const heavy = screen.js.filter((f) => /^(ag-grid|echarts)-vendor[-.]/.test(f))
    expect(heavy, `首屏 preload 出现重型 chunk: ${heavy.join(', ')}`).toEqual([])
    const heavyCss = screen.css.filter((f) => /^(ag-grid|echarts)-vendor[-.]/.test(f))
    expect(heavyCss).toEqual([])
  })

  it('Vue 运行时单独成 chunk 且在首屏（对照组：证明它没被并回网格）', () => {
    const vue = screen.js.filter((f) => /^vue-vendor[-.]/.test(f))
    expect(vue.length, `首屏应有且仅有一个 vue-vendor，实际: ${vue.join(', ')}`).toBe(1)
  })

  it('首屏字节不超过预算 1,300,000B（2026-10-27 实测 1,094,781B JS）', () => {
    // 预算而非精确值：依赖升级会移动几 KB，但并一个 1MB 级 vendor 进来必然越过它。
    expect(screen.jsBytes).toBeLessThanOrEqual(1_300_000)
  })
})
