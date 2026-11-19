import { test, expect, type Page } from '@playwright/test'
import { gotoApp, navByMenu } from '../helpers/nav'

/**
 * FIX-4：四个 sibling loader 与占用 chip 一样随激活刷新。
 *
 * 六类请求的计数器口径（两条用例共用 `attachCounter`）：
 * 父页全量列表（page_size=9999）、子页分页列表（file_type=single）、
 * product_codes、format_types、list_tags、usage。
 *
 * 两条判据分工：
 * - 首屏那条：计数器**先装再进页面**，钉「首进只发一轮」——把 `onMounted` 加回来就会各变 2；
 * - 激活那条：计数器从仪表板回来时才装，钉「重新激活各发一轮」——退回 mounted-only 就会各变 0。
 */
function attachCounter(page: Page) {
  const hits = {
    fullList: 0,
    pageList: 0,
    productCodes: 0,
    formatTypes: 0,
    tags: 0,
    usage: 0,
  }
  page.on('request', (r) => {
    const url = r.url()
    if (!url.includes('/api/v1/files/')) return
    if (url.includes('/files/usage/')) hits.usage++
    else if (url.includes('/files/product_codes/')) hits.productCodes++
    else if (url.includes('/files/format_types/')) hits.formatTypes++
    else if (url.includes('/files/list_tags/')) hits.tags++
    else if (/\/files\/\?page_size=9999(&|$)/.test(url)) hits.fullList++
    else if (/\/files\/\?(.*&)?file_type=single/.test(url)) hits.pageList++
  })
  return hits
}

test.describe('数据管理激活刷新 sibling loaders', { tag: ['@p2', '@data'] }, () => {
  test('首屏六类请求各一次（防止把 onMounted 加回来）', async ({ page }) => {
    const hits = attachCounter(page)
    await gotoApp(page, '/data')
    await expect(page.locator('.content-section:visible .el-table .el-table__row').first())
      .toBeVisible({ timeout: 20_000 })
    await expect.poll(() => ({ ...hits }), { timeout: 15_000 }).toEqual({
      fullList: 1, pageList: 1, productCodes: 1, formatTypes: 1, tags: 1, usage: 1,
    })
    await page.waitForTimeout(500)
    expect({ ...hits }).toEqual({
      fullList: 1, pageList: 1, productCodes: 1, formatTypes: 1, tags: 1, usage: 1,
    })
  })

  test('从仪表板回数据管理：六类请求各一次', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.content-section:visible .el-table .el-table__row').first())
      .toBeVisible({ timeout: 20_000 })

    await navByMenu(page, '仪表板')
    await expect(page.getByTestId('page-identity')).toContainText('仪表板')

    const hits = attachCounter(page)

    await navByMenu(page, '数据管理')
    await expect(page.locator('.content-section:visible .el-table .el-table__row').first())
      .toBeVisible({ timeout: 15_000 })

    await expect.poll(() => ({ ...hits }), { timeout: 15_000 }).toEqual({
      fullList: 1,
      pageList: 1,
      productCodes: 1,
      formatTypes: 1,
      tags: 1,
      usage: 1,
    })
  })
})
