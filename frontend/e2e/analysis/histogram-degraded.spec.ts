/**
 * KDE 内存降级提示（前端接线证明）。
 *
 * 后端契约（T1 已钉）：`/analysis/histogram/` 每个参数结果恒带 `degraded: string[]`，
 * KDE 撞 `MemoryError` 时是 `'kde_curve'` / `'filtered_kde_curve'`，正常为空数组。
 * 本用例只证明**前端接线**：读到的 `degraded` 非空 → 图表上方出现
 * `[data-degraded-hint]`，清空 → 同一位置消失。
 *
 * ⚠ 归因层要说准（lessons 2026-11-14）：`route.fulfill` 后浏览器收到的是**改写过的**
 * 响应，后端「什么情况会 append reason」在这条通路上不可观察 —— 那一半只有 T1 能证。
 * 所以这里用 `route.fetch()` 取真实响应再改一个字段，保住其余字段的真实性
 * （图表仍要能正常渲染），而不是整个替换成手搓 JSON。
 *
 * 只改写带 `params` 的计算请求：页面首屏另有**不带 params** 的快路径
 * （`useTabFileParams` 拿参数全集），改它会让 `listParams()` 读不到真实列表。
 */
import { test, expect } from '@playwright/test'
import { loginAs } from '../helpers/auth'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, listParams, selectParam } from '../helpers/params'
import { waitLoadingGone } from '../helpers/charts'
import { RECOMMENDED } from '../fixtures/test-data'

const SINGLE = '.single-param-tab'
const HINT = `${SINGLE} [data-degraded-hint]`
const HINT_TEXT = '内存紧张，已省略 KDE 曲线'
const HISTOGRAM_ROUTE = '**/api/v1/analysis/histogram/**'
const COMPUTE_MARK = '"params":['

test.describe('@p1 @analysis KDE 内存降级提示', { tag: ['@p1', '@analysis'] }, () => {
  // 清空注入的 storageState，走实时 UI 登录（与 admin/* 同一约定）：
  // 本用例要拦的是登录后同会话里的计算请求，先登录再进页面最贴近真实路径。
  test.use({ storageState: { cookies: [], origins: [] } })

  test('degraded 非空出提示，改为空数组后提示消失', async ({ page }) => {
    let injected: string[] = ['kde_curve']
    await page.route(HISTOGRAM_ROUTE, async (route) => {
      if (!(route.request().postData() || '').includes(COMPUTE_MARK)) {
        return route.continue()
      }
      const response = await route.fetch()
      const body = await response.json()
      const results = body?.results
      if (results && typeof results === 'object') {
        for (const key of Object.keys(results)) {
          const item = (results as Record<string, any>)[key]
          if (item && typeof item === 'object') item.degraded = [...injected]
        }
      }
      return route.fulfill({ response, json: body })
    })

    await loginAs(page, 'admin')
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, RECOMMENDED.analysis)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await expect(page.locator(`${SINGLE} .chart-wrapper`)).toBeVisible({ timeout: 15_000 })

    const params = await listParams(page)
    expect(
      params.length,
      '需要至少 3 个参数：两次重新加载靠切参数触发（选中项不变不会发新请求）',
    ).toBeGreaterThanOrEqual(3)

    const nextCompute = () =>
      page.waitForResponse(
        (r) =>
          r.url().includes('/api/v1/analysis/histogram/') &&
          r.status() === 200 &&
          (r.request().postData() || '').includes(COMPUTE_MARK),
      )

    // 1) 有降级原因 → 提示可见且文案固定
    const degradedResp = nextCompute()
    await selectParam(page, params[1])
    await degradedResp
    await expect(page.locator(HINT)).toBeVisible({ timeout: 10_000 })
    await expect(page.locator(HINT)).toHaveText(HINT_TEXT)

    // 2) 同一路由改回空数组 → 提示从 DOM 中消失（v-if，不留空壳占位）
    injected = []
    const cleanResp = nextCompute()
    await selectParam(page, params[2])
    await cleanResp
    await expect(page.locator(HINT)).toHaveCount(0)
  })
})
