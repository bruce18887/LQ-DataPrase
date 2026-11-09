import { test, expect } from '@playwright/test'
import { uiLogin } from '../helpers/auth'

/**
 * 自助改密的端到端接线：
 * Topbar 用户菜单 → 个人资料 → 修改密码 → 旧会话清空 → 新密码可登录。
 *
 * 账号自建自删，不碰种子账号（admin/user 是共享 storageState 的持有者）。
 */
test.describe('账号安全', { tag: ['@auth'] }, () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test.afterAll(async ({ browser }) => {
    const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    try {
      const login = await ctx.request.post('/api/v1/auth/login/', {
        data: { username: 'admin', password: 'admin123' },
      })
      if (!login.ok()) return
      const headers = { Authorization: `Bearer ${(await login.json()).token}` }
      const list = await ctx.request.get('/api/v1/auth/users/', {
        headers,
        failOnStatusCode: false,
      })
      if (!list.ok()) return
      const body = await list.json()
      const users: Array<{ id: number; username: string }> =
        Array.isArray(body) ? body : body.results || []
      for (const user of users) {
        if (/^e2e_pwd_/.test(user.username ?? '')) {
          await ctx.request.delete(`/api/v1/auth/users/${user.id}/`, {
            headers,
            failOnStatusCode: false,
          })
        }
      }
    } catch {
      // 清理失败静默；下一轮 afterAll 再兜底
    } finally {
      await ctx.close()
    }
  })

  test('@p1 修改密码后旧会话失效，新密码可登录', async ({ browser }) => {
    const username = `e2e_pwd_${Date.now()}`
    const initialPassword = 'e2eInitial-12345'
    const newPassword = 'e2eChanged-67890'

    const adminCtx = await browser.newContext({
      storageState: { cookies: [], origins: [] },
    })
    let userId: number | null = null
    try {
      const login = await adminCtx.request.post('/api/v1/auth/login/', {
        data: { username: 'admin', password: 'admin123' },
      })
      expect(login.ok(), '种子 admin 登录失败，无法建临时账号').toBe(true)
      const headers = { Authorization: `Bearer ${(await login.json()).token}` }

      const created = await adminCtx.request.post('/api/v1/auth/users/', {
        headers,
        data: { username, password: initialPassword, role: 'user' },
      })
      expect(created.ok(), `临时账号创建失败：${await created.text()}`).toBe(true)
      userId = (await created.json()).id

      const userCtx = await browser.newContext({
        storageState: { cookies: [], origins: [] },
      })
      const userPage = await userCtx.newPage()
      try {
        await uiLogin(userPage, username, initialPassword)
        await expect(userPage).toHaveURL(/\/dashboard/, { timeout: 15_000 })

        await userPage.locator('.user-menu').click()
        await userPage.getByText('个人资料', { exact: true }).click()
        await expect(userPage.getByTestId('account-dialog')).toBeVisible()

        // Element Plus 把透传属性绑到内层 input 上，data-testid 本身就是输入框。
        await userPage.getByTestId('account-old-password').fill(initialPassword)
        await userPage.getByTestId('account-new-password').fill(newPassword)
        await userPage.getByTestId('account-confirm-password').fill(newPassword)

        // R2①：waitForResponse 必须先于触发动作注册。
        const [resp] = await Promise.all([
          userPage.waitForResponse(
            (r) =>
              r.url().includes('/auth/change-password/') &&
              r.request().method() === 'POST',
            { timeout: 20_000 },
          ),
          userPage.getByTestId('account-change-password').click(),
        ])
        expect(resp.status(), `改密必须 200，实际 ${resp.status()}：${await resp.text()}`).toBe(200)

        // 当前会话被清空并回到登录页。
        await expect(userPage).toHaveURL(/\/login/, { timeout: 15_000 })
        const token = await userPage.evaluate(() =>
          localStorage.getItem('access_token'),
        )
        expect(token).toBeNull()

        // 新密码可以重新登录。
        await uiLogin(userPage, username, newPassword)
        await expect(userPage).toHaveURL(/\/dashboard/, { timeout: 15_000 })
      } finally {
        await userCtx.close()
      }
    } finally {
      if (userId != null) {
        const relogin = await adminCtx.request.post('/api/v1/auth/login/', {
          data: { username: 'admin', password: 'admin123' },
          failOnStatusCode: false,
        })
        if (relogin.ok()) {
          const headers = { Authorization: `Bearer ${(await relogin.json()).token}` }
          await adminCtx.request.delete(`/api/v1/auth/users/${userId}/`, {
            headers,
            failOnStatusCode: false,
          })
        }
      }
      await adminCtx.close()
    }
  })
})
