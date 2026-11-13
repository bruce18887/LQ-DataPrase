import { expect, test } from '@playwright/test'

/**
 * 介绍书标签页图标的真实浏览器判据（Task 11，设计稿 §3.2）。
 *
 * 根因链：config.mts 过去没有 head ⇒ 构建产物没有 <link rel="icon"> ⇒ 浏览器无条件
 * 兜底请求 /favicon.ico ⇒（生产形态）Django 只挂 /favicon.svg，该请求落 catch-all
 * ⇒ 拿到 200 + text/html 的 SPA 壳（不是 404）⇒ 图标解不出来，标签页空白。
 *
 * 边界（诚实声明）：标签条画在浏览器 chrome 里，Playwright 截不到页面外的标签页，
 * 「图标真的亮起来」本仓无法自动化证明，需人工看一眼（最短路径见 spec 末尾注释）。
 * 本文件钉的是它可证的那一层：声明本体存在 + 声明指向的资产在当前服务器上真的可达。
 *
 * 教训（2026-11-14 复审实测，删掉两条计数器型反向断言）：「/favicon.ico 请求数 == 0」
 * 「404 响应数 == 0」在**任何实现下都绿**——headless Chromium/Edge 有 link 时不请求
 * /favicon.ico，把产物里的 link 删掉后**照样不请求** ⇒ 计数恒 0，抓不到根因。
 * 反向计数挡不住这个根因；真正挡它的是 T1 的 MIME/字节断言 + 本文件的 link 存在断言。
 * （console 采集同样不是通路：`e2e/helpers/nav.ts` 把 favicon 类错误整体过滤。）
 *
 * 为什么这里不断 fetch('/favicon.ico') === 200：e2e 前端档是 vite preview（纯静态发 dist），
 * 既没有 favicon.ico 文件也不走 Django 路由 ⇒ 该断言在此环境必红，与产品修复无关。
 * 「/favicon.ico 在 Django 返回 200 SVG」由 T1（test/backend/test_intro_serving.py ②）钉住。
 * 这里断的是页面内可达性等价物：**按声明里那个 href** 取，必须 200 + SVG MIME。
 */

test.describe('@theme 介绍书标签页图标', { tag: ['@p2', '@theme'] }, () => {
  test('@p2 /intro/ 声明 SVG 图标，且该 href 指向的资产在当前服务器上可达', async ({ page }) => {
    await page.goto('/intro/', { waitUntil: 'load' })

    // ① 声明本体：link[rel="icon"] 存在，href 是绝对根路径 /favicon.svg
    //    （不能是 /intro/favicon.svg——Django 只在根路径挂该文件，见 config.mts 注释）。
    const iconLink = page.locator('link[rel="icon"]')
    await expect(iconLink).toHaveCount(1)
    await expect(iconLink).toHaveAttribute('href', '/favicon.svg')

    // ② 声明不是空口白话：按 ① 那条 link 的 href 现取，证明**当前这个服务器**真发得出这份
    //    SVG 字节（preview 档 = 静态 dist/favicon.svg；生产档同路径由 Django /favicon.svg 路由承接）。
    const href = (await iconLink.getAttribute('href')) ?? ''
    const asset = await page.evaluate(async (iconHref) => {
      const resp = await fetch(iconHref)
      return { status: resp.status, type: resp.headers.get('content-type') }
    }, href)
    expect(asset.status, `声明的图标 ${href} 在当前服务器上取不到`).toBe(200)
    expect(asset.type, `${href} 返回的不是 SVG 字节（MIME=${asset.type}）`).toContain('image/svg+xml')
  })
})

// 人眼验证最短路径（自动化的天花板到此为止）：
//   起服务后开 http://localhost:<前端口>/intro/ （或生产 http://<主机>/intro/），
//   看浏览器标签页标题左侧是否显示蓝色菱形图标（favicon.svg）。
