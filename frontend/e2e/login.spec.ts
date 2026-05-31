import { test, expect } from '@playwright/test'

test.describe('登录页面', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login')
  })

  test('页面正常加载', async ({ page }) => {
    await expect(page.locator('h2')).toBeVisible()
  })

  test('空输入时登录按钮禁用', async ({ page }) => {
    const loginBtn = page.getByRole('button', { name: /登录/i })
    await expect(loginBtn).toBeDisabled()
  })

  test('输入用户名密码后可登录', async ({ page }) => {
    await page.getByLabel(/用户名/i).fill('admin')
    await page.getByLabel(/密码/i).fill('admin123')
    await page.getByRole('button', { name: /登录/i }).click()
    await expect(page).toHaveURL(/dashboard/, { timeout: 10000 })
  })

  test('错误密码提示', async ({ page }) => {
    await page.getByLabel(/用户名/i).fill('admin')
    await page.getByLabel(/密码/i).fill('wrongpass')
    await page.getByRole('button', { name: /登录/i }).click()
    await expect(page.getByText(/用户名或密码错误/i)).toBeVisible()
  })
})
