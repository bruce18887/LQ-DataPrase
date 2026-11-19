import { test, expect } from '@playwright/test'
import { gotoApp, navByMenu } from '../helpers/nav'

/**
 * FIX-4：四个 sibling loader 与占用 chip 一样随激活刷新。
 * 从仪表板客户端路由回 /data，六类请求各恰好一次：
 * 父页全量列表（page_size=9999）、子页分页列表（file_type=single）、
 * product_codes、format_types、list_tags、usage。
 */
test.describe('数据管理激活刷新 sibling loaders', { tag: ['@p2', '@data'] }, () => {
  test('从仪表板回数据管理：六类请求各一次', async ({ page }) => {
    await gotoApp(page, '/data')
    await expect(page.locator('.content-section:visible .el-table .el-table__row').first())
      .toBeVisible({ timeout: 20_000 })

    await navByMenu(page, '仪表板')
    await expect(page.getByTestId('page-identity')).toContainText('仪表板')

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
