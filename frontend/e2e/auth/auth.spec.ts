import { test, expect } from '@playwright/test'
import { ACCOUNTS } from '../fixtures/test-data'
import { uiLogin, loginAs, logout } from '../helpers/auth'

// 认证用例从“未登录”开始，覆盖掉项目级注入的 admin storageState
test.use({ storageState: { cookies: [], origins: [] } })

test.describe('@p0 认证与路由守卫', { tag: ['@p0', '@p1', '@p2', '@auth'] }, () => {
  test('未登录访问受保护路由 → 跳转 /login', async ({ page }) => {
    await page.goto('/dashboard')
    await expect(page).toHaveURL(/\/login/)
  })

  test('登录页正常加载', async ({ page }) => {
    await page.goto('/login')
    await expect(page.getByRole('heading', { level: 1, name: 'DataPhrase' })).toBeVisible()
    await expect(page.getByPlaceholder('用户名')).toBeVisible()
    await expect(page.getByPlaceholder('密码')).toBeVisible()
    await expect(page.locator('button.neon-button')).toBeVisible()
  })

  test('空输入触发表单校验', async ({ page }) => {
    await page.goto('/login')
    await page.getByPlaceholder('用户名').fill('')
    await page.getByPlaceholder('密码').fill('')
    await page.locator('button.neon-button').click()
    // 仍停留在登录页，且出现校验错误
    await expect(page).toHaveURL(/\/login/)
    await expect(page.locator('.el-form-item__error').first()).toBeVisible()
  })

  test('正确账号登录成功跳转看板', async ({ page }) => {
    await uiLogin(page, ACCOUNTS.admin.username, ACCOUNTS.admin.password)
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 })
    await expect(page.locator('.main-layout')).toBeVisible()
  })

  test('@p1 错误密码登录失败、停留登录页且未获得登录态', async ({ page }) => {
    // 注意：登录接口 401 会被 api/index.ts 的全局响应拦截器捕获并
    // window.location.href='/login'，导致 LoginPage 的内联 error-msg 来不及展示
    // （已记录为 UX 问题）。故此处断言真实可观测行为：未登录 + 停留登录页。
    await uiLogin(page, ACCOUNTS.admin.username, 'wrong-password-xyz')
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 })
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    expect(token).toBeNull()
  })

  test('@p1 已登录访问 /login 跳回看板', async ({ page }) => {
    await loginAs(page, 'admin')
    await page.goto('/login')
    await expect(page).toHaveURL(/\/dashboard/)
  })

  test('@p2 登出后清除登录态并回到登录页', async ({ page }) => {
    await loginAs(page, 'admin')
    await logout(page)
    await expect(page).toHaveURL(/\/login/)
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    expect(token).toBeNull()
  })

  test('@p1 401 响应自动清除登录态并跳登录', async ({ page }) => {
    await loginAs(page, 'admin')
    // 伪造失效 token，触发受保护接口 401 → 响应拦截器 window.location.href='/login'
    // 注意：window.location.href 会 abort PagePlay 的 page.goto（net::ERR_ABORTED），
    // 故用 waitForURL 等待重定向，不对 goto 抛错断言。
    await page.evaluate(() => localStorage.setItem('access_token', 'invalid.token.value'))
    page.goto('/data').catch(() => {})
    await page.waitForURL(/\/login/, { timeout: 15_000 })
  })
})
