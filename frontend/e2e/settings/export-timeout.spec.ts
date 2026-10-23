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

    /*
     * 宽度判据（承重，别删）。这一行的说明文案与 el-input-number 同在一个 flex 行里，
     * 控件默认 `flex: 0 1 auto` ⇒ 会被文案压缩，下限只有 `.el-input__wrapper` 的 42+42px 内边距。
     * 2026-10-23 在 1280×720（本用例的默认视口）实测：
     *   导出超时行  控件 150→84px，内部 <input> **0px**  ⇒ 只有 toBeVisible 的用例能红（真红 1 条）
     *   SFTP 超时行 控件 150→109.9px，内部 <input> 25.9px ⇒ 同一个缺陷，但「可见」所以全绿
     * 回归点是 73c4791（把导出这行的文案从一行加到三行），不是测试写错。
     * 阈值取自修复后的实测值：控件 = Element Plus 声明的 150px；
     * 内部 <input> = 150 − 42 − 42 = 66px。取 140 / 40 留余量，同时稳稳压住 0 与 25.9。
     */
    const numberBox = await page.getByTestId('export-timeout-input').boundingBox()
    expect(numberBox?.width, 'el-input-number 被说明文案挤扁（历史实测 84px）').toBeGreaterThanOrEqual(140)
    const inputBox = await input.boundingBox()
    expect(inputBox?.width, '内部 <input> 宽度归零，用户看不到也点不着（历史实测 0px）').toBeGreaterThanOrEqual(40)
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
