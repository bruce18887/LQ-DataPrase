/**
 * 分析页「请求失败」必须可见、可重试（2026-09-02 审计批次 1）。
 *
 * 原症状：直方图请求失败时 UI 完全静默——composable 丢弃了 useAsyncData 的
 * error，请求又带 `silent: true` 抑制了全局 toast，右侧只剩一片空白，
 * 用户无法区分「这个参数没数据」与「后端 500 了」。
 *
 * 本用例用 route 强制 histogram 返回 500，断言：
 *  1. 出现内联错误横幅（含失败原因标题），而不是空白；
 *  2. 点「重试」在请求恢复后横幅消失、图表重新渲染。
 */
import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { selectAnalysisFile, listParams, selectParam } from '../helpers/params'
import { expectChartRendered, waitLoadingGone } from '../helpers/charts'
import { SEEDED_FILES } from '../fixtures/test-data'

const SINGLE = '.single-param-tab'
const BANNER = `${SINGLE} [data-testid="error-banner"]`
const HISTOGRAM_ROUTE = '**/api/v1/analysis/histogram/**'

test.describe('@regression 分析页错误态可见性', () => {
  test('直方图请求失败显示错误横幅，重试后恢复', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, SEEDED_FILES.GAGE_S4)
    await expect(page.getByRole('tab', { name: /单文件分析/ })).toBeVisible({ timeout: 20_000 })
    await waitLoadingGone(page.locator(SINGLE))
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)

    // 让 histogram 请求失败（其余端点保持正常，隔离出「只有直方图坏了」）
    await page.route(HISTOGRAM_ROUTE, (route) =>
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ code: 'internal_error', message: 'boom' }),
      }),
    )

    const params = await listParams(page)
    expect(params.length).toBeGreaterThan(1)
    const failed = page.waitForResponse(
      (r) => r.url().includes('/api/v1/analysis/histogram/'),
    )
    await selectParam(page, params[1])
    expect((await failed).status()).toBe(500)

    await expect(page.locator(BANNER)).toBeVisible({ timeout: 10_000 })
    await expect(page.locator(BANNER)).toContainText('直方图数据加载失败')

    // 恢复后端 → 点重试 → 横幅消失且图表重新渲染
    await page.unroute(HISTOGRAM_ROUTE)
    const recovered = page.waitForResponse(
      (r) => r.url().includes('/api/v1/analysis/histogram/') && r.status() === 200,
    )
    await page.locator(BANNER).getByRole('button', { name: '重试' }).click()
    await recovered
    await expect(page.locator(BANNER)).toHaveCount(0)
    await expectChartRendered(page.locator(`${SINGLE} .chart-wrapper`), 0)
  })

  test('切换文件后旧的失败横幅不残留', async ({ page }) => {
    await gotoApp(page, '/analysis')
    await selectAnalysisFile(page, SEEDED_FILES.GAGE_S4)
    await waitLoadingGone(page.locator(SINGLE))

    await page.route(HISTOGRAM_ROUTE, (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: '{}' }),
    )
    const params = await listParams(page)
    const failed = page.waitForResponse((r) => r.url().includes('/api/v1/analysis/histogram/'))
    await selectParam(page, params[1])
    await failed
    await expect(page.locator(BANNER)).toBeVisible({ timeout: 10_000 })

    // 换一个文件：新文件加载成功，旧横幅必须消失（错误态不能跨上下文残留）
    await page.unroute(HISTOGRAM_ROUTE)
    const ok = page.waitForResponse(
      (r) => r.url().includes('/api/v1/analysis/histogram/') && r.status() === 200,
    )
    await selectAnalysisFile(page, SEEDED_FILES.ETS88_FT)
    await ok
    await expect(page.locator(BANNER)).toHaveCount(0)
  })
})
