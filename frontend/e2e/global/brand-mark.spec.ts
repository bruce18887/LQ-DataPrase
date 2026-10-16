import { test, expect, type Page } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { loginAs } from '../helpers/auth'

/**
 * T3（浏览器不可替代的两件事）：
 *   1) 品牌位真的渲染出实心 SVG 剪影，而不是 EP 折线图图标或 emoji；
 *   2) 双主题下的**计算色** —— CSS 变量在运行时解析的结果，T2 拿不到。
 * 形状本身不漂移由 T2（brandMark.spec.ts）负责，这里不重复。
 *
 * 覆盖 spec §7 第 7–8 条要求的**四个槽位**（侧栏 / 登录页 / 连接页 / 关于对话框）：
 *   侧栏 `.logo-icon` 是 40×40 的 var(--brand) 实色底板 + 符号 → **墨与底成对断言**
 *     （light 白墨压蓝底、night 深墨压金底）；只钉墨色不成立，墨 vs 底是一对关系；
 *   登录页 / 连接页 / 关于对话框是无底板形制（宿主只给 `color: var(--brand)`）
 *     → 各自钉自己那一页的 light `rgb(37,99,235)` / night `rgb(249,168,37)`。
 * 侧栏 night 下原本仍是"白符号压 #f9a825 金黄底"= 约 1.9:1，本任务按 spec D6 改深墨。
 *
 * 品牌位的夜主题**不能**由 e2e/theme/night-visibility.spec.ts 的对比度扫描代劳：
 * 那个扫描只经 gotoApp 访问登录后路由（/login、/connect 从不加载），且跳过有子节点（:64）
 * 与无文本（:66）的元素 —— 一个 `<svg>` 符号永远进不了它的候选集。
 */

// 每条用例都要一个**未登录**的上下文：
//   · loginAs 走 UI 登录，而 src/router/index.ts:176 的守卫会把已登录会话的
//     /login 弹回 /dashboard → 带着项目注入的 admin storageState 时登录表单根本渲染不出来
//     （e2e/admin/admin.spec.ts:35 与 e2e/global/global.spec.ts:184 同一处理）；
//   · 登录页与连接页断言的是**该页唯一**那个 [data-test="app-logo"]，
//     若被弹回 /dashboard 就会命中侧栏那枚（strict mode violated）。
test.use({ storageState: { cookies: [], origins: [] } })

const BRAND_LIGHT = 'rgb(37, 99, 235)'    // --brand light  = #2563eb
const BRAND_NIGHT = 'rgb(249, 168, 37)'   // --brand night  = #f9a825
const INK_LIGHT = 'rgb(255, 255, 255)'    // 侧栏底板上的反白
const INK_NIGHT = 'rgb(19, 19, 39)'       // 侧栏 night 底板上的深墨 = --p-slate-950

/**
 * 以夜主题打开公开页（/login、/connect 都在 MainLayout 之外，没有 ThemeToggle 可点）：
 * index.html:11-19 的 FOUC 内联脚本在首帧前就把 localStorage.theme 写到 html[data-theme]，
 * 所以这两页的 --brand 同样有 night 解析结果可断言。
 */
async function gotoPublicPageInNight(page: Page, url: string) {
  await page.addInitScript(() => localStorage.setItem('theme', 'night'))
  await page.goto(url)
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'night')
}

test.describe('@p1 品牌位', { tag: ['@p1', '@global'] }, () => {
  test('侧栏品牌位是 AppLogo，底板墨色随主题切换且不再是白压金黄', async ({ page }) => {
    await loginAs(page, 'user')
    await gotoApp(page, '/dashboard')
    const logo = page.locator('aside.sidebar [data-test="app-logo"]')
    await expect(logo).toBeVisible()
    await expect(logo.locator('path')).toHaveCount(1)
    await expect(logo).toHaveCSS('color', INK_LIGHT)
    await expect(page.locator('aside.sidebar .logo-icon')).toHaveCSS('background-color', BRAND_LIGHT)

    await page.addInitScript(() => localStorage.setItem('theme', 'night'))
    await page.reload()
    await gotoApp(page, '/dashboard')
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'night')
    await expect(page.locator('aside.sidebar .logo-icon')).toHaveCSS('background-color', BRAND_NIGHT)
    await expect(page.locator('aside.sidebar [data-test="app-logo"]')).toHaveCSS('color', INK_NIGHT)
  })

  test('登录页品牌位是 AppLogo，无底板形制下 light/night 计算色成对', async ({ page }) => {
    await page.goto('/login')
    const logo = page.locator('[data-test="app-logo"]')
    await expect(logo).toBeVisible()
    await expect(logo).toHaveCSS('color', BRAND_LIGHT)
    // 旧的 EP 图标会留下 .el-icon 包装
    await expect(page.locator('.logo-section .el-icon')).toHaveCount(0)

    await gotoPublicPageInNight(page, '/login')
    await expect(logo).toHaveCSS('color', BRAND_NIGHT)
  })

  test('连接页品牌位是 AppLogo，无底板形制下 light/night 计算色成对', async ({ page }) => {
    // 原先这里是 <el-icon :size="56"><Connection /></el-icon>（ConnectPage.vue:6）
    await page.goto('/connect')
    // 限定在页面容器内，避免与对话框那枚（同一 data-test）争 strict mode
    const logo = page.locator('[data-test="connect-page"] [data-test="app-logo"]')
    await expect(logo).toBeVisible()
    await expect(logo).toHaveCSS('color', BRAND_LIGHT)
    await expect(page.locator('.logo-section .el-icon')).toHaveCount(0)

    await gotoPublicPageInNight(page, '/connect')
    await expect(logo).toHaveCSS('color', BRAND_NIGHT)
  })

  test('关于对话框品牌位是 AppLogo，light/night 计算色成对且 emoji 已消失', async ({ page }) => {
    // 打开通路沿用 e2e/global/global.spec.ts:157-179（顶栏版本徽章 → 「关于」对话框）
    await loginAs(page, 'user')
    await gotoApp(page, '/dashboard')
    await page.locator('.version-badge').click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    // 登录后侧栏也有一枚 [data-test="app-logo"]，所以必须限定在对话框内定位
    const logo = dialog.locator('[data-test="app-logo"]')
    await expect(logo).toHaveCount(1)
    await expect(logo).toHaveCSS('color', BRAND_LIGHT)
    // 📊 曾经就住在这里（AppAboutDialog.vue:12 的 `<span class="about-logo">📊</span>`）；
    // 登录页从来没有过它，所以这条断言只有放在对话框里才可能失败。
    await expect(dialog.locator('.about-body')).not.toContainText('📊')

    // 换夜主题重开一次：UI 登录的 token 就在同一 context 的 localStorage 里，reload 后登录态保持
    await page.addInitScript(() => localStorage.setItem('theme', 'night'))
    await page.reload()
    await gotoApp(page, '/dashboard')
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'night')
    await page.locator('.version-badge').click()
    await expect(dialog).toBeVisible()
    // .about-logo 的 color: var(--brand)（AppAboutDialog.vue:78，本任务新引入的一条声明）
    await expect(logo).toHaveCSS('color', BRAND_NIGHT)
  })
})
