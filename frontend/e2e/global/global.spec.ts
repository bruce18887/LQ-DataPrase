import { test, expect } from '@playwright/test'
import { ROUTES } from '../fixtures/test-data'
import { gotoApp, sidebarLink } from '../helpers/nav'
import { loginAs } from '../helpers/auth'
// frontend/package.json 为版本单一事实源（vite 构建时注入，electron-builder 打包版本）
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const appPkgVersion: string = JSON.parse(
  readFileSync(fileURLToPath(new URL('../../package.json', import.meta.url)), 'utf-8'),
).version as string

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

test.describe('@p2 Ctrl+滚轮页面缩放', { tag: ['@p2', '@global'] }, () => {
  test('Ctrl+滚轮放大/缩小页面并持久化到 localStorage', async ({ page }) => {
    await gotoApp(page, '/dashboard')

    const getZoom = () => page.evaluate(() => document.documentElement.style.zoom || '1')
    const getStoredZoom = () => page.evaluate(() => localStorage.getItem('lqdp-zoom-factor'))

    await expect.poll(getZoom).toBe('1')

    // 模拟 Ctrl+向上滚轮放大
    await page.evaluate(() => {
      const event = new WheelEvent('wheel', { deltaY: -100, ctrlKey: true, bubbles: true })
      window.dispatchEvent(event)
    })
    await expect.poll(getZoom).not.toBe('1')
    const zoomedIn = parseFloat(await getZoom())
    expect(zoomedIn).toBeGreaterThan(1)
    expect(parseFloat((await getStoredZoom()) ?? '1')).toBe(zoomedIn)

    // 模拟 Ctrl+向下滚轮缩小
    await page.evaluate(() => {
      const event = new WheelEvent('wheel', { deltaY: 100, ctrlKey: true, bubbles: true })
      window.dispatchEvent(event)
    })
    await expect.poll(async () => parseFloat(await getZoom())).toBeLessThan(zoomedIn)

    // Ctrl+0 恢复 100%
    await page.keyboard.down('Control')
    await page.keyboard.press('0')
    await page.keyboard.up('Control')
    await expect.poll(getZoom).toBe('1')
    expect(await getStoredZoom()).toBe('1')
  })

  test('缩放时右下角显示当前百分比指示器，停止后自动消失', async ({ page }) => {
    await gotoApp(page, '/dashboard')

    const indicator = page.locator('.zoom-indicator')
    await expect(indicator).toHaveCount(0)

    // 连续放大到 150%（5 步 × 0.1）
    for (let i = 0; i < 5; i++) {
      await page.evaluate(() => {
        const event = new WheelEvent('wheel', { deltaY: -100, ctrlKey: true, bubbles: true })
        window.dispatchEvent(event)
      })
    }

    await expect(indicator).toBeVisible()
    await expect(indicator).toHaveText('缩放 150%')

    // 缩小一步 → 百分比实时更新
    await page.evaluate(() => {
      const event = new WheelEvent('wheel', { deltaY: 100, ctrlKey: true, bubbles: true })
      window.dispatchEvent(event)
    })
    await expect(indicator).toHaveText('缩放 140%')

    // 停止滚动 → 指示器自动隐藏（防抖 800ms + 过渡动画）
    await expect(indicator).not.toBeVisible({ timeout: 5_000 })

    // Ctrl+0 重置也会短暂提示 100%
    await page.keyboard.down('Control')
    await page.keyboard.press('0')
    await page.keyboard.up('Control')
    await expect(indicator).toHaveText('缩放 100%')
  })

  test('指示器消失（组件卸载）后 Ctrl+滚轮缩放仍有效（回归：useZoom 引用计数）', async ({ page }) => {
    await gotoApp(page, '/dashboard')

    const getZoom = () => page.evaluate(() => document.documentElement.style.zoom || '1')
    const indicator = page.locator('.zoom-indicator')

    // 第一次缩放：指示器挂载 → 防抖 800ms 后 v-if 移除（组件真正卸载）
    await page.evaluate(() => {
      const event = new WheelEvent('wheel', { deltaY: -100, ctrlKey: true, bubbles: true })
      window.dispatchEvent(event)
    })
    await expect(indicator).toBeVisible()
    await expect(indicator).not.toBeVisible({ timeout: 5_000 })
    // toHaveCount(0) = 元素已从 DOM 移除 = onUnmounted 已执行（旧实现此时误删全局监听）
    await expect(indicator).toHaveCount(0)
    const afterFirst = parseFloat(await getZoom())
    expect(afterFirst).toBeGreaterThan(1)

    // 指示器卸载后再次缩放：引用计数修复前全局监听已被移除，此步缩放失效
    await page.evaluate(() => {
      const event = new WheelEvent('wheel', { deltaY: -100, ctrlKey: true, bubbles: true })
      window.dispatchEvent(event)
    })
    await expect.poll(getZoom).not.toBe(String(afterFirst))

    // 恢复 100%，避免污染其他用例的缩放预期
    await page.keyboard.down('Control')
    await page.keyboard.press('0')
    await page.keyboard.up('Control')
    await expect.poll(getZoom).toBe('1')
  })
})

test.describe('@p2 版本显示', { tag: ['@p2', '@global'] }, () => {
  test('顶栏显示版本徽章，点击弹出「关于」对话框', async ({ page }) => {
    // 版本单一事实源：frontend/package.json（vite 构建时注入，与 electron-builder 一致）
    const version = appPkgVersion
    await gotoApp(page, '/dashboard')

    const badge = page.locator('.version-badge')
    await expect(badge).toBeVisible()
    await expect(badge).toHaveText(`v${version}`)

    // 点击徽章 → 关于对话框
    await badge.click()
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('heading', { name: '关于 LQ-DataPrase' })).toBeVisible()
    await expect(dialog.getByText('LQ-DataPrase', { exact: true })).toBeVisible()
    await expect(dialog.getByText(`v${version}`)).toBeVisible()
    await expect(dialog.getByText(/构建/)).toBeVisible()
    await expect(dialog.getByText(/运行环境/)).toBeVisible()

    // 可关闭
    await dialog.getByRole('button', { name: '关闭' }).click()
    await expect(dialog).not.toBeVisible()
  })
})

// 角色相关用例：清空 storageState，实时 UI 登录使 user/isAdmin 生效
test.describe('Topbar 与角色', { tag: ['@global'] }, () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('@p1 管理员登录后 Topbar 显示管理员、可见“用户管理”菜单', async ({ page }) => {
    await loginAs(page, 'admin')
    await expect(page.locator('.user-role')).toHaveText('管理员')
    await expect(sidebarLink(page, '用户管理')).toBeVisible()
  })

  test('@p1 普通用户登录后 Topbar 显示用户、隐藏“用户管理”菜单', async ({ page }) => {
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
