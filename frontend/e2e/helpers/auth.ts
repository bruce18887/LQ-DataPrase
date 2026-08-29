import { expect, type Page } from '@playwright/test'
import { ACCOUNTS, type Role } from '../fixtures/test-data'

/**
 * 通过登录页 UI 完成登录。
 *
 * 选择器依据 LoginPage.vue 实测：输入框无 label，用 placeholder；
 * 登录按钮文本为「登 录」（中间含空格），用 .login-button 更稳。
 */
export async function uiLogin(page: Page, username: string, password: string) {
  await page.goto('/login')
  const user = page.getByPlaceholder('用户名')
  const pass = page.getByPlaceholder('密码')
  await expect(user).toBeVisible()
  await user.fill(username)
  await pass.fill(password)
  await page.locator('button.login-button').click()
}

/**
 * 以指定角色实时登录，并保持同一 SPA 会话（不刷新页面）。
 * 用于依赖 user/isAdmin 的用例（管理员菜单、Topbar 角色等），
 * 因为应用启动不会从 token 重新拉取 profile。
 */
export async function loginAs(page: Page, role: Role) {
  const acct = ACCOUNTS[role]
  await uiLogin(page, acct.username, acct.password)
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 })
}

/** 退出登录（通过 Topbar 用户菜单） */
export async function logout(page: Page) {
  await page.locator('.user-menu').click()
  await page.getByText('退出登录').click()
  await expect(page).toHaveURL(/\/login/, { timeout: 10_000 })
}
