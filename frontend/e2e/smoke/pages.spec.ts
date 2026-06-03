import { test, expect } from '@playwright/test'
import { ROUTES } from '../fixtures/test-data'
import { collectConsoleErrors } from '../helpers/nav'

/**
 * P0 冒烟：每个受保护页面都能在已登录态下打开，
 * 主布局渲染、对应侧边栏项高亮、且无控制台错误。
 * 使用注入的 admin storageState（仅需 token）。
 */
test.describe('@p0 冒烟 - 页面可达', { tag: ['@p0', '@smoke'] }, () => {
  for (const route of ROUTES) {
    test(`${route.title} (${route.path}) 正常加载且无报错`, async ({ page }) => {
      const errors = collectConsoleErrors(page)

      await page.goto(route.path)
      await expect(page).toHaveURL(new RegExp(route.path.replace('/', '\\/')))
      await expect(page.locator('.main-layout')).toBeVisible({ timeout: 15_000 })

      // 对应侧边栏项处于激活态（限定在侧边栏，避免与 Topbar 面包屑同名冲突）
      await expect(
        page.locator('aside.sidebar').getByRole('link', { name: route.menu, exact: true }),
      ).toHaveClass(/active/)

      // 给异步渲染留出时间后再校验控制台
      await page.waitForTimeout(800)
      expect(errors, `控制台错误:\n${errors.join('\n')}`).toEqual([])
    })
  }
})
