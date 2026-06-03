import { test as setup, expect } from '@playwright/test'
import fs from 'node:fs'
import { ACCOUNTS, ADMIN_STATE, USER_STATE, AUTH_DIR, type Role } from './test-data'
import { uiLogin } from '../helpers/auth'

/**
 * 登录态准备（在所有业务用例之前运行一次）。
 *
 * 通过真实 UI 登录获取 JWT，并把 localStorage(token) 导出为 storageState，
 * 供后续“仅需登录”的功能用例直接复用，避免每条用例重复登录。
 *
 * 注意：App 启动不会重新拉取用户 profile（见 tasks/todo.md），
 * storageState 仅恢复 token，不恢复角色。角色相关用例请用 loginAs() 实时登录。
 */
setup.beforeAll(() => {
  fs.mkdirSync(AUTH_DIR, { recursive: true })
})

async function persist(role: Role, statePath: string, page: import('@playwright/test').Page) {
  await uiLogin(page, ACCOUNTS[role].username, ACCOUNTS[role].password)
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 })
  await page.context().storageState({ path: statePath })
}

setup('authenticate as admin', async ({ page }) => {
  await persist('admin', ADMIN_STATE, page)
})

setup('authenticate as user', async ({ page }) => {
  await persist('user', USER_STATE, page)
})
