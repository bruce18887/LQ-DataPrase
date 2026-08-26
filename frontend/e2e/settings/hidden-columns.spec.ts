import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { DEFAULT_HIDDEN_COLUMNS } from '../../src/constants/hidden-columns'

/**
 * 默认隐藏列（系统设置 → 📋 表格设置 tab → 默认隐藏列）。
 *
 * 注意：admin storageState 共享 + 设置持久化，修改默认隐藏列的用例必须在
 * finally 中恢复默认值，避免污染后续用例（恢复助手只 PUT 单字段）。
 */

async function gotoTableTab(page: import('@playwright/test').Page) {
  await gotoApp(page, '/settings')
  await page.getByRole('tab', { name: '📋 表格设置' }).click()
}

/** CTA8290D 平台分区的容器（各属性复选框可能同名，需按平台作用域） */
function cta8290dSection(page: import('@playwright/test').Page) {
  return page.locator('.platform-section[data-platform="CTA8290D"]')
}

/** 勾选状态：el-checkbox 视觉隐藏 input，用容器 + class 断言（R4） */
function checkbox(scope: import('@playwright/test').Locator, label: string) {
  return scope.locator('.el-checkbox').filter({ hasText: label }).first()
}

async function putHiddenColumns(page: import('@playwright/test').Page, cols: string[]) {
  await page.evaluate(async (cols) => {
    await fetch('/api/v1/auth/settings/', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('access_token')}`,
      },
      body: JSON.stringify({ default_hidden_columns: cols }),
    })
  }, cols)
}

test.describe('@p1 默认隐藏列设置', { tag: ['@p1', '@settings'] }, () => {
  test('渲染：按平台分区展示，默认 8 列勾选', async ({ page }) => {
    await gotoTableTab(page)
    const group = page.locator('.hidden-cols-checkboxes')
    await expect(group).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.hidden-cols-hint')).toBeVisible()

    // 四个 ATE 平台分区
    for (const platform of ['CTA8290D', 'CTA8280F', 'ETS88', 'STS8200']) {
      await expect(page.locator(`.platform-section[data-platform="${platform}"]`)).toBeVisible()
    }

    // 默认勾选：Part_No / Dut_Pass / X_COORD / Y_COORD / QR_Code / Start_T / Alarm / Data_Cnt
    const section = cta8290dSection(page)
    for (const col of DEFAULT_HIDDEN_COLUMNS) {
      await expect(checkbox(section, col)).toHaveClass(/is-checked/)
    }
    // 未勾选示例：Serial_No / SW_Bin（默认隐藏列表不含它们）
    await expect(checkbox(section, 'Serial_No')).not.toHaveClass(/is-checked/)
    await expect(checkbox(section, 'SW_Bin')).not.toHaveClass(/is-checked/)
  })

  test('属性复选框整组勾选：「槽位」→ Dut_No/Site_No 同时勾选，再次点击整组取消', async ({ page }) => {
    try {
      await gotoTableTab(page)
      const section = cta8290dSection(page)
      const slotGroup = checkbox(section, '槽位')
      const dutNo = checkbox(section, 'Dut_No')
      const siteNo = checkbox(section, 'Site_No')

      // 初始：Dut_No/Site_No 均未勾选（不在默认 8 列中）
      await expect(dutNo).not.toHaveClass(/is-checked/)
      await expect(siteNo).not.toHaveClass(/is-checked/)

      // 点击属性「槽位」→ 整组勾选
      await slotGroup.click()
      await expect(dutNo).toHaveClass(/is-checked/)
      await expect(siteNo).toHaveClass(/is-checked/)
      await expect(slotGroup).toHaveClass(/is-checked/)

      // 再次点击 → 整组取消
      await slotGroup.click()
      await expect(dutNo).not.toHaveClass(/is-checked/)
      await expect(siteNo).not.toHaveClass(/is-checked/)
      await expect(slotGroup).not.toHaveClass(/is-checked/)
    } finally {
      await putHiddenColumns(page, DEFAULT_HIDDEN_COLUMNS)
    }
  })

  test('保存并持久化：取消 Dut_Pass、勾选 Serial_No → 保存 → reload 保留；结束后恢复', async ({ page }) => {
    try {
      await gotoTableTab(page)
      const section = cta8290dSection(page)
      await checkbox(section, 'Dut_Pass').click()
      await checkbox(section, 'Serial_No').click()

      const [response] = await Promise.all([
        page.waitForResponse(
          (resp) => /\/auth\/settings\//.test(resp.url()) && resp.request().method() === 'PUT',
        ),
        page.getByRole('button', { name: '💾 保存设置' }).click(),
      ])
      expect(response.status()).toBe(200)
      await expect(page.locator('.el-message').filter({ hasText: /保存|成功/ })).toBeVisible()

      await page.reload()
      await page.getByRole('tab', { name: '📋 表格设置' }).click()
      await expect(checkbox(cta8290dSection(page), 'Dut_Pass')).not.toHaveClass(/is-checked/)
      await expect(checkbox(cta8290dSection(page), 'Serial_No')).toHaveClass(/is-checked/)
    } finally {
      await putHiddenColumns(page, DEFAULT_HIDDEN_COLUMNS)
    }
  })
})
