import { test, expect } from '@playwright/test'
import { ROUTES } from '../fixtures/test-data'
import { gotoApp, sidebarLink } from '../helpers/nav'
import { loginAs } from '../helpers/auth'

/**
 * 跨页/全局能力：侧边栏导航、主题切换、Topbar 角色显示、管理员菜单可见性。
 */

test.describe('@p1 侧边栏导航', { tag: ['@p1', '@global'] }, () => {
  // 使用注入的 admin storageState（token 即可，这些菜单项不要求管理员角色）
  test('点击各菜单项跳转且高亮正确', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    for (const route of ROUTES) {
      await sidebarLink(page, route.menu).click()
      await expect(page).toHaveURL(new RegExp(route.path.replace('/', '\\/')))
      await expect(sidebarLink(page, route.menu)).toHaveClass(/active/)
    }
  })

  test('菜单顺序为 仪表板 → 数据管理 → 数据分析 → SFTP浏览器', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    const expectedOrder = ['仪表板', '数据管理', '数据分析', 'SFTP浏览器']
    const labels = page.locator('aside.sidebar .menu-item:not(.hidden) .menu-label')
    for (let i = 0; i < expectedOrder.length; i++) {
      await expect(labels.nth(i)).toHaveText(expectedOrder[i])
    }
  })
})

test.describe('@p2 主题切换', { tag: ['@p2', '@global'] }, () => {
  test('切换暗黑/浅色并持久化到 localStorage', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    const toggle = page.locator('button.theme-toggle')
    await expect(toggle).toBeVisible()

    const before = await page.evaluate(() => document.documentElement.getAttribute('data-theme'))
    await toggle.click()
    await expect
      .poll(() => page.evaluate(() => document.documentElement.getAttribute('data-theme')))
      .not.toBe(before)

    const after = await page.evaluate(() => document.documentElement.getAttribute('data-theme'))
    const stored = await page.evaluate(() => localStorage.getItem('theme'))
    expect(stored).toBe(after)
  })
})

// 角色相关用例：清空 storageState，实时 UI 登录使 user/isAdmin 生效
test.describe('@p1 Topbar 与角色', { tag: ['@p1', '@p2', '@global'] }, () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('管理员登录后 Topbar 显示管理员、可见“用户管理”菜单', async ({ page }) => {
    await loginAs(page, 'admin')
    await expect(page.locator('.user-role')).toHaveText('管理员')
    await expect(sidebarLink(page, '用户管理')).toBeVisible()
  })

  test('普通用户登录后 Topbar 显示用户、隐藏“用户管理”菜单', async ({ page }) => {
    await loginAs(page, 'user')
    await expect(page.locator('.user-role')).toHaveText('用户')
    await expect(sidebarLink(page, '用户管理')).toBeHidden()
  })

  test('@p2 用户菜单可打开并包含退出登录', async ({ page }) => {
    await loginAs(page, 'admin')
    await page.locator('.user-menu').click()
    await expect(page.getByText('退出登录')).toBeVisible()
  })
})
