import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { waitLoadingGone } from '../helpers/charts'

/**
 * ECharts 渲染器（系统设置 → 📊 显示设置 → 「ECharts 渲染器」）。
 *
 * 回归：账号级设置此前只有「访问过设置页」才会写进 echarts-theme.ts 的模块缓存，
 * 刷新/重启后不进设置页 → 全部图表静默回退硬编码 'svg'，用户改成 canvas 无感。
 *
 * 设置走 API PUT 而非 UI：本用例的前提就是「全程不进设置页」，用 UI 改会把自己
 * 要修的那条链路绕过。admin storageState 共享 → finally 恢复默认 'svg'。
 */

async function putRenderer(page: import('@playwright/test').Page, renderer: string) {
  const status = await page.evaluate(async (value) => {
    const resp = await fetch('/api/v1/auth/settings/', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('access_token')}`,
      },
      body: JSON.stringify({ chart_renderer: value }),
    })
    return resp.status
  }, renderer)
  expect(status, `PUT chart_renderer=${renderer} 应成功`).toBe(200)
}

/** 仪表板首屏即渲染的 ECharts 容器（Site 良率柱线组合图）。 */
function siteChart(page: import('@playwright/test').Page) {
  return page.getByRole('img', { name: 'Site良率柱线组合图' })
}

/**
 * 容器内的画笔根节点。SiteYieldAnalysis.vue:21 的 role=img div 是 echarts.init 的
 * 宿主且自身无子节点（图标 SVG 不会落进来），所以「容器内有 canvas 还是有 svg」
 * 就是渲染器的直接证据（与 helpers/charts.ts 的判定同一口径）。
 */
function painterRoot(chart: import('@playwright/test').Locator, kind: 'canvas' | 'svg') {
  return chart.locator(kind)
}

test.describe('ECharts 渲染器设置', { tag: ['@settings'] }, () => {
  test('@p1 账号设为 canvas：不进设置页直接刷新，首屏图表即用 canvas', async ({ page }) => {
    try {
      await gotoApp(page, '/dashboard')
      await putRenderer(page, 'canvas')

      // 重新加载 = 全新 JS 上下文，模块缓存回到初值；这是被修的那条路径
      await gotoApp(page, '/dashboard')
      await waitLoadingGone(page)

      const chart = siteChart(page)
      await expect(chart).toBeVisible()
      await expect(painterRoot(chart, 'canvas')).toBeVisible()
      await expect(painterRoot(chart, 'svg')).toHaveCount(0)
    } finally {
      await putRenderer(page, 'svg')
    }
  })

  test('@p1 默认 svg 不被接线破坏：账号为 svg 时首屏仍是 svg', async ({ page }) => {
    try {
      await gotoApp(page, '/dashboard')
      await putRenderer(page, 'svg')
      await gotoApp(page, '/dashboard')
      await waitLoadingGone(page)

      const chart = siteChart(page)
      await expect(chart).toBeVisible()
      await expect(painterRoot(chart, 'svg')).toBeVisible()
      await expect(painterRoot(chart, 'canvas')).toHaveCount(0)
    } finally {
      await putRenderer(page, 'svg')
    }
  })
})
