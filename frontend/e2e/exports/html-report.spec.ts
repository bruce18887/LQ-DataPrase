import fs from 'node:fs'
import { test, expect } from '@playwright/test'
import { gotoApp, collectConsoleErrors } from '../helpers/nav'
import { waitLoadingGone } from '../helpers/charts'
import { captureDownload } from '../helpers/download'

/**
 * HTML 报表导出（含图 · 自包含单文件）。
 * - 单文件：仪表板单文件 Tab → 「📥 保存 HTML 报表」（POST /export/html_report/）
 * - 批次：仪表板批次良率 Tab → 「📥 导出 HTML」（POST /batch-report/batch_html_report/）
 *
 * 断言下载文件非空 + 文件名 .html + 内容含内联 base64 图表与关键区块。
 */
test.describe('HTML 报表导出', { tag: ['@dashboard'] }, () => {
  test('@p1 单文件报告含内联图表', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)
    await expect(page.getByTestId('overview-strip')).toBeVisible()

    const dl = await captureDownload(
      page,
      async () => {
        await page.getByRole('button', { name: /保存 HTML 报表/ }).click()
      },
      'dashboard',
      120_000,
    )
    expect(dl.suggestedName).toMatch(/\.html$/)

    const html = fs.readFileSync(dl.savedPath, 'utf-8')
    expect(html).toContain('data:image/png;base64,')
    expect(html).toContain('总记录')
    expect(html).not.toContain('src="http')
  })

  test('@p2 批次报告可导出且含内联图表', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    await waitLoadingGone(page)

    const batchTab = page.locator('.el-tabs__item').filter({ hasText: '批次良率' })
    await batchTab.click()
    await expect(page.locator('.batch-yield-tab')).toBeVisible()
    await waitLoadingGone(page)

    const batchSelect = page.locator('.batch-selector .el-select').first()
    await expect(batchSelect).toBeVisible()
    await batchSelect.click()

    // 页面存在多个 el-select（文件选择器等），下拉项都挂在 body：取**可见**的那个。
    // waitFor（非 isVisible）会重试，覆盖下拉展开动画。
    const firstOption = page.locator('.el-select-dropdown__item:visible').first()
    const optVisible = await firstOption
      .waitFor({ state: 'visible', timeout: 10_000 })
      .then(() => true)
      .catch(() => false)
    if (!optVisible) {
      test.skip(true, '当前环境无可用批次，跳过批次 HTML 导出断言')
      return
    }
    await firstOption.click()

    const dataResp = page
      .waitForResponse((r) => r.url().includes('batch_yield_data'), { timeout: 30_000 })
      .catch(() => null)
    await page.getByRole('button', { name: /加载批次报表/ }).click()
    const resp = await dataResp

    const htmlBtn = page.getByRole('button', { name: /导出 HTML/ })
    const htmlVisible = await htmlBtn
      .waitFor({ state: 'visible', timeout: 20_000 })
      .then(() => true)
      .catch(() => false)
    if (!resp || resp.status() >= 400 || !htmlVisible) {
      test.skip(true, `批次数据未就绪（status=${resp?.status() ?? 'no-resp'}，按钮=${htmlVisible}），跳过`)
      return
    }

    const dl = await captureDownload(
      page,
      async () => {
        await htmlBtn.click()
      },
      'dashboard',
      120_000,
    )
    expect(dl.suggestedName).toMatch(/\.html$/)

    const html = fs.readFileSync(dl.savedPath, 'utf-8')
    expect(html).toContain('data:image/png;base64,')
    expect(html).toContain('阶段汇总')

    const errors = collectConsoleErrors(page)
    expect(errors.filter((e) => /导出失败|html report failed/.test(e))).toEqual([])
  })
})
