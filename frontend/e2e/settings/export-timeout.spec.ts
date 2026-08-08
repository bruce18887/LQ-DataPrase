import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'

/**
 * 导出超时（系统设置 → 📄 导出模板 tab → ⏱️ 导出超时）。
 *
 * 注意：admin storageState 共享 + 设置持久化，修改导出超时的用例必须在
 * finally 中恢复默认 600，避免污染后续用例（恢复助手只 PUT 单字段）。
 */

/** 设置页为左侧竖排标签页：进入 /settings 后先点击「导出模板」tab。 */
async function gotoExportTab(page: import('@playwright/test').Page) {
  await gotoApp(page, '/settings')
  await page.getByRole('tab', { name: '📄 导出模板' }).click()
}

async function restoreTimeout(page: import('@playwright/test').Page) {
  await page.evaluate(async () => {
    await fetch('/api/v1/auth/settings/', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('access_token')}`,
      },
      body: JSON.stringify({ export_timeout: 600 }),
    })
  })
}

/** data-testid 落在 el-input-number 根 div 上，内部 <input> 才是可填值元素 */
function timeoutInput(page: import('@playwright/test').Page) {
  return page.getByTestId('export-timeout-input').locator('input')
}

test.describe('@p1 导出超时设置', { tag: ['@p1', '@settings'] }, () => {
  test('渲染：导出模板 tab 内显示超时输入框（默认 600）与说明文案', async ({ page }) => {
    await gotoExportTab(page)
    const input = timeoutInput(page)
    await expect(input).toBeVisible()
    await expect(input).toHaveValue('600')
    await expect(page.getByText(/导出请求最长等待秒数/)).toBeVisible()
  })

  test('保存并持久化：改为 900 → 保存 → reload 保留；结束后恢复默认', async ({ page }) => {
    try {
      await gotoExportTab(page)
      const input = timeoutInput(page)
      await input.fill('900')
      await input.blur()

      const [response] = await Promise.all([
        page.waitForResponse(
          (resp) => /\/auth\/settings\//.test(resp.url()) && resp.request().method() === 'PUT',
        ),
        page.getByRole('button', { name: '💾 保存设置' }).click(),
      ])
      expect(response.status()).toBe(200)
      await expect(page.locator('.el-message').filter({ hasText: /保存|成功/ })).toBeVisible()

      await page.reload()
      await page.getByRole('tab', { name: '📄 导出模板' }).click()
      await expect(timeoutInput(page)).toHaveValue('900')
    } finally {
      await restoreTimeout(page)
    }
  })
})

test.describe('@p2 导出超时 API 边界', { tag: ['@p2', '@settings'] }, () => {
  test('后端校验：低于 30 / 高于 3600 / 非数字均返回 400', async ({ page }) => {
    await gotoApp(page, '/settings')
    const statuses = await page.evaluate(async () => {
      const put = (value: unknown) =>
        fetch('/api/v1/auth/settings/', {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${localStorage.getItem('access_token')}`,
          },
          body: JSON.stringify({ export_timeout: value }),
        }).then((resp) => resp.status)
      return {
        belowMin: await put(29),
        aboveMax: await put(3601),
        nonInteger: await put('abc'),
      }
    })
    expect(statuses).toEqual({ belowMin: 400, aboveMax: 400, nonInteger: 400 })
  })
})
