import { expect, test } from '@playwright/test'

/**
 * 介绍书标签页图标的真实浏览器判据（Task 11，设计稿 §3.2）。
 *
 * 根因链：config.mts 过去没有 head ⇒ 构建产物没有 <link rel="icon"> ⇒ 浏览器无条件
 * 兜底请求 /favicon.ico ⇒（生产形态）Django 只挂 /favicon.svg ⇒ 404 ⇒ 标签页空白。
 *
 * 边界（诚实声明）：标签条画在浏览器 chrome 里，Playwright 截不到页面外的标签页，
 * 「图标真的亮起来」本仓无法自动化证明，需人工看一眼（最短路径见 spec 末尾注释）。
 * 本文件钉的是它可证的两层：HTML 里声明了图标 + 声明生效后浏览器不再发出那条 404 兜底请求。
 *
 * 为什么计数走 page.on('request'/'response') 而不是 console：
 * `e2e/helpers/nav.ts` 的 collectConsoleErrors 把 favicon 类 console 错误整体过滤
 * （`/favicon|.../`），console 断言永远不会红，是死判据；response 监听不经过它。
 *
 * 为什么这里不断 fetch('/favicon.ico') === 200：e2e 前端档是 vite preview（纯静态发 dist），
 * 既没有 favicon.ico 文件也不走 Django 路由 ⇒ 该断言在此环境必红，与产品修复无关。
 * 「/favicon.ico 在 Django 返回 200 SVG」由 T1（test/backend/test_intro_serving.py ②）钉住。
 * 这里断的是页面内可达性等价物：声明指向的 /favicon.svg 必须 200。
 */

test.describe('@theme 介绍书标签页图标', { tag: ['@p2', '@theme'] }, () => {
  test('@p2 /intro/ 声明 SVG 图标且不再发出 /favicon.ico 兜底请求', async ({ page }) => {
    const faviconIcoRequests: string[] = []
    const notFoundResponses: string[] = []
    page.on('request', (req) => {
      if (new URL(req.url()).pathname === '/favicon.ico') faviconIcoRequests.push(req.url())
    })
    page.on('response', (resp) => {
      if (resp.status() === 404) notFoundResponses.push(`${resp.status()} ${resp.url()}`)
    })

    await page.goto('/intro/', { waitUntil: 'load' })

    // ① 声明本体：link[rel="icon"] 存在，href 是绝对根路径 /favicon.svg
    //    （不能是 /intro/favicon.svg——Django 只在根路径挂该文件，见 config.mts 注释）。
    const iconLink = page.locator('link[rel="icon"]')
    await expect(iconLink).toHaveCount(1)
    await expect(iconLink).toHaveAttribute('href', '/favicon.svg')

    // ② 声明生效后 Chromium 不会再兜底请求 /favicon.ico；404 计数为零。
    //    修复前的红法：无声明 ⇒ 浏览器自动请求 /favicon.ico ⇒ preview 回 404 ⇒ 两处都红。
    expect(faviconIcoRequests, '浏览器仍在兜底请求 /favicon.ico（link 声明丢了？）').toHaveLength(0)
    expect(notFoundResponses, `加载 /intro/ 出现 404：\n${notFoundResponses.join('\n')}`).toHaveLength(0)

    // ③ 声明指向的资产真实可达（同 origin，即 preview 直接发 dist/favicon.svg；
    //    生产形态同路径由 Django /favicon.svg 路由承接）。
    const assetStatus = await page.evaluate(async () => {
      const resp = await fetch('/favicon.svg')
      return { status: resp.status, type: resp.headers.get('content-type') }
    })
    expect(assetStatus.status, '声明的 /favicon.svg 取不到').toBe(200)
    expect(assetStatus.type).toContain('image/svg+xml')
  })
})

// 人眼验证最短路径（自动化的天花板到此为止）：
//   起服务后开 http://localhost:<前端口>/intro/ （或生产 http://<主机>/intro/），
//   看浏览器标签页标题左侧是否显示蓝色菱形图标（favicon.svg）。
