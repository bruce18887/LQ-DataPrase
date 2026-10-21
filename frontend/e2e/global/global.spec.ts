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

  test('菜单顺序为 仪表板 → 数据管理 → 数据分析 → SFTP 浏览器', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    const expectedOrder = ['仪表板', '数据管理', '数据分析', 'SFTP 浏览器']
    const labels = page.locator('aside.sidebar .menu-item:not(.hidden) .menu-label')
    for (let i = 0; i < expectedOrder.length; i++) {
      await expect(labels.nth(i)).toHaveText(expectedOrder[i])
    }
  })

  test('折叠侧边栏持久化到 localStorage，刷新后仍折叠且链接仍有可访问名', async ({ page }) => {
    await gotoApp(page, '/dashboard')
    const sidebar = page.locator('aside.sidebar')
    const btn = page.locator('button.collapse-btn')

    await expect(sidebar).toHaveCSS('width', '240px')
    await btn.click()
    await expect(sidebar).toHaveCSS('width', '64px')
    await expect
      .poll(() => page.evaluate(() => localStorage.getItem('lqdp-sidebar-collapsed')))
      .toBe('1')

    await page.reload()
    await expect(sidebar).toHaveCSS('width', '64px')
    // 折叠态标签走 v-show（display:none 会移出无障碍树）：没有 aria-label 时
    // 这里会定位不到，而 helpers/nav.ts 的整条 getByRole 通路依赖它
    await expect(sidebarLink(page, '数据分析')).toBeVisible()
    await expect(sidebarLink(page, '数据分析')).toHaveAttribute('title', '数据分析')

    // 复原：不污染同批次其它用例对侧栏宽度/标签可见性的预期
    await btn.click()
    await expect(sidebar).toHaveCSS('width', '240px')
    await expect
      .poll(() => page.evaluate(() => localStorage.getItem('lqdp-sidebar-collapsed')))
      .toBe('0')
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

test.describe('@p2 浏览器档不接管页面缩放', { tag: ['@p2', '@global'] }, () => {
  /**
   * 回归（2026-10-21）：浏览器档曾往 `<html>` 写 CSS `zoom`，而 Element Plus 的下拉是
   * teleport 到 body 的 `position:absolute` 浮层 —— floating-ui 把「已放大的视觉坐标」
   * 原样写进 left/top，浮层于是**再乘一次 zoom**，偏移 = 坐标 ×(zoom−1)，用户看到的就是
   * 「测试项选择框 / 文件选择框的下拉跑到右下方」。现在浏览器档一个监听都不绑，
   * 缩放整个交给浏览器原生（桌面版仍走 webContents.setZoomFactor，见 zoomMode.ts）。
   *
   * 判据取「应用没动过 inline zoom」而不是「缩放量等于几」：浏览器原生缩放不落在
   * inline style 上，派发合成 WheelEvent 之后它必须恒为空串。
   */
  test('Ctrl+滚轮不写 CSS zoom、不出百分比气泡、不落 localStorage', async ({ page }) => {
    await gotoApp(page, '/dashboard')

    const htmlZoom = () => page.evaluate(() => document.documentElement.style.zoom)
    const storedZoom = () => page.evaluate(() => localStorage.getItem('lqdp-zoom-factor'))
    const wheel = (deltaY: number) =>
      page.evaluate((dy) => {
        window.dispatchEvent(new WheelEvent('wheel', { deltaY: dy, ctrlKey: true, bubbles: true }))
      }, deltaY)

    await expect.poll(htmlZoom).toBe('')

    // 放大三步 + 缩小一步 + Ctrl+0：应用若接管，这三样会留下 zoom、气泡与存储
    for (const dy of [-100, -100, -100, 100]) await wheel(dy)
    await page.keyboard.down('Control')
    await page.keyboard.press('0')
    await page.keyboard.up('Control')

    await expect.poll(htmlZoom).toBe('')
    await expect(page.locator('.zoom-indicator')).toHaveCount(0)
    expect(await storedZoom()).toBeNull()

    // 探针自证：同一读法看得见 CSS zoom，否则上面那条「恒为空」是瞎判据
    await page.evaluate(() => { document.documentElement.style.zoom = '1.25' })
    await expect.poll(htmlZoom).toBe('1.25')
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
