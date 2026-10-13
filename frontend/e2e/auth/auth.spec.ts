import { test, expect } from '@playwright/test'
import { ACCOUNTS } from '../fixtures/test-data'
import { uiLogin, loginAs, logout } from '../helpers/auth'

// 认证用例从“未登录”开始，覆盖掉项目级注入的 admin storageState
test.use({ storageState: { cookies: [], origins: [] } })

// describe 只挂模块 tag，优先级由各用例标题的 @pN 前缀承担
// （Playwright grep 匹配完整标题，describe 级多挂 @pN 会让用例在多个 P 项目重复执行）
test.describe('认证与路由守卫', { tag: ['@auth'] }, () => {
  test('@p0 未登录访问受保护路由 → 跳转 /login', async ({ page }) => {
    await page.goto('/dashboard')
    await expect(page).toHaveURL(/\/login/)
  })

  test('@p0 登录页正常加载', async ({ page }) => {
    await page.goto('/login')
    await expect(page.getByRole('heading', { level: 1, name: 'LQ-DataPrase' })).toBeVisible()
    await expect(page.getByPlaceholder('用户名')).toBeVisible()
    await expect(page.getByPlaceholder('密码')).toBeVisible()
    await expect(page.locator('button.login-button')).toBeVisible()
  })

  test('@p0 空输入触发表单校验', async ({ page }) => {
    await page.goto('/login')
    await page.getByPlaceholder('用户名').fill('')
    await page.getByPlaceholder('密码').fill('')
    await page.locator('button.login-button').click()
    // 仍停留在登录页，且出现校验错误
    await expect(page).toHaveURL(/\/login/)
    await expect(page.locator('.el-form-item__error').first()).toBeVisible()
  })

  test('@p0 正确账号登录成功跳转看板', async ({ page }) => {
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

  test('@p1 401 响应在 refresh_token 也失效时清除登录态并跳登录', async ({ page }) => {
    // access_token 失效时拦截器会尝试 refresh；只有当 refresh_token
    // 也无效时才会真正走 logout 重定向。这里同时损坏两个 token 来
    // 模拟 refresh token 已被吊销/过期的最坏情况。
    await loginAs(page, 'admin')
    await page.evaluate(() => {
      localStorage.setItem('access_token', 'invalid.token.value')
      localStorage.setItem('refresh_token', 'invalid.token.value')
    })
    // window.location.href 会 abort PagePlay 的 page.goto（net::ERR_ABORTED），
    // 故用 waitForURL 等待重定向，不对 goto 抛错断言。
    page.goto('/data').catch(() => {})
    await page.waitForURL(/\/login/, { timeout: 15_000 })
    // 首次落地 /login 后，其余在途请求仍会各自触发 401 → 再次 window.location
    // 重定向；生产包导航更密，evaluate 可能撞上导航（context destroyed）→ 捕获重试
    await expect.poll(
      async () => {
        try {
          return await page.evaluate(() => localStorage.getItem('access_token'))
        } catch {
          return 'navigating'
        }
      },
      { timeout: 10_000 },
    ).toBe(null)
  })

  test('@p2 access_token 失效但 refresh_token 有效时自动续签并放行原请求', async ({ page }) => {
    // 这是「单页内连续操作跨过 30 min」场景的核心回归。
    await loginAs(page, 'admin')
    const originalAccess = await page.evaluate(() => localStorage.getItem('access_token'))
    const originalRefresh = await page.evaluate(() => localStorage.getItem('refresh_token'))

    // 伪造一个无效 access_token，refresh_token 保持原样可用
    await page.evaluate(() => localStorage.setItem('access_token', 'invalid.token.value'))

    // 触发受保护请求：拦截器收到 401 → 调 /auth/refresh/ 拿到新 token → 重发
    await page.goto('/data')
    await expect(page).toHaveURL(/\/data/, { timeout: 15_000 })

    // 刷新在请求管线内异步完成（URL 到位 ≠ 续签已落盘）：轮询等新 access 写入
    await expect.poll(
      () => page.evaluate(() => localStorage.getItem('access_token')),
      { timeout: 15_000 },
    ).not.toBe('invalid.token.value')

    const newAccess = await page.evaluate(() => localStorage.getItem('access_token'))
    const newRefresh = await page.evaluate(() => localStorage.getItem('refresh_token'))
    expect(newAccess).toBeTruthy()
    // access token 续签过，必须不等于原值
    expect(newAccess).not.toBe(originalAccess)
    // refresh token 因为 ROTATE_REFRESH_TOKENS=True 也被换掉
    expect(newRefresh).not.toBe(originalRefresh)
  })

  test('@p2 用户名不存在时显示「用户名「xxx」不存在」', async ({ page }) => {
    // 不走 auth.setup 的 storageState，从干净状态开始
    await page.goto('/login')
    await page.getByPlaceholder('用户名').fill('ghost-user-does-not-exist')
    await page.getByPlaceholder('密码').fill('whatever-12345')
    await page.locator('button.login-button').click()

    // 错误提示 + 类别 class（user_not_found）都应出现
    const hint = page.getByTestId('login-error-hint').or(page.locator('.error-msg'))
    await expect(hint).toBeVisible({ timeout: 10_000 })
    await expect(hint).toContainText('不存在')
    await expect(page.locator('.error-msg--user_not_found')).toBeVisible()
  })

  test('@p2 错误密码显示「密码错误」+ 剩余尝试次数', async ({ page }) => {
    await page.goto('/login')
    await page.getByPlaceholder('用户名').fill(ACCOUNTS.admin.username)
    await page.getByPlaceholder('密码').fill('wrong-password-xyz')
    await page.locator('button.login-button').click()

    // LoginPage 自身 try/catch 内联展示错误（不走全局 401 → /login 拦截）
    await expect(page.locator('.error-msg--invalid_credentials')).toBeVisible({
      timeout: 10_000,
    })
    await expect(page.getByTestId('login-error-hint')).toContainText('次尝试')
  })
})
