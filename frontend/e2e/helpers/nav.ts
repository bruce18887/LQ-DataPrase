import { expect, type Page } from '@playwright/test'

/**
 * 导航到指定业务路由并等待主布局就绪。
 * 适用于已注入 storageState（已登录）的用例。
 */
export async function gotoApp(page: Page, route: string) {
  await page.goto(route)
  // 主布局容器出现即认为进入应用（未登录会被守卫重定向到 /login）
  await expect(page.locator('.main-layout')).toBeVisible({ timeout: 15_000 })
}

/** 通过侧边栏菜单点击跳转（限定侧边栏，避免与 Topbar 面包屑同名冲突） */
export async function navByMenu(page: Page, menuText: string) {
  await page.locator('aside.sidebar').getByRole('link', { name: menuText, exact: true }).click()
}

/** 侧边栏中的菜单链接 Locator */
export function sidebarLink(page: Page, menuText: string) {
  return page.locator('aside.sidebar').getByRole('link', { name: menuText, exact: true })
}

/** 收集页面控制台错误（过滤掉无关噪声） */
export function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = []
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text()
      // 过滤常见无害噪声
      if (/favicon|ResizeObserver|Failed to load resource.*404.*\.map/.test(text)) return
      errors.push(text)
    }
  })
  page.on('pageerror', (err) => errors.push(err.message))
  return errors
}
