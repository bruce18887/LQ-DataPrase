import { expect, type Page } from '@playwright/test'

/**
 * 打开「数据修复」并点「开始检查」。
 *
 * 前提：当前页已在 `/data` —— 导航不归它，由各 spec 的 `beforeEach` 走
 * `helpers/nav` 的 `gotoApp`。它原来住在 `describe` 内部（`repair-center.spec.ts:171`），
 * 拆文件后两半都要用，留在任一半里就是往 spec 里复制第二份。
 * 第二个点击带 `timeout: 10_000` 是原值，别调小：对话框打开与检查请求在同一次交互里。
 */
export async function openRepairCenter(page: Page) {
  await page.locator('button').filter({ hasText: '数据修复' }).first().click()
  await expect(page.getByRole('button', { name: '开始检查' })).toBeVisible({ timeout: 10_000 })
  await page.getByRole('button', { name: '开始检查' }).click()
}
