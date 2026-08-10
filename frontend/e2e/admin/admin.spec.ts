import { test, expect, type Page, type Locator } from '@playwright/test'
import { loginAs } from '../helpers/auth'
import { sidebarLink } from '../helpers/nav'

/**
 * 添加用户表单字段定位：el-form-item 的 label 在本应用不可靠地关联为可访问名
 * （沿用 sftp.spec.ts 的既有约定），故按 .el-form-item__label 文本过滤后取内部 input。
 * 限定在 .user-management 的 el-form 内，避免与表格列头「用户名」歧义。
 */
function addUserField(page: Page, label: string): Locator {
  return page
    .locator('.user-management .el-form .el-form-item')
    .filter({ has: page.locator('.el-form-item__label', { hasText: label }) })
    .locator('input')
    .first()
}

/**
 * 用户管理（/admin/users）端到端用例。
 *
 * 角色相关：应用启动/刷新不会用 token 重新拉取 profile，
 * 故 user/isAdmin 仅在“同会话内实时 UI 登录”后有效。
 * 因此本文件整体清空 storageState，统一用 loginAs(page, role) 实时登录，
 * 并尽量用侧边栏点击（不刷新页面）保持 Pinia user 存活。
 *
 * 路由实情（src/router/index.ts beforeEach）：
 *   守卫只判断 `to.meta.requiresAuth && !auth.isLoggedIn`，而 isLoggedIn = !!token。
 *   —— 没有任何基于角色/管理员的拦截。
 *   因此普通用户（持有 token）直接访问 /admin/users 不会被重定向，路由会渲染；
 *   仅靠侧边栏菜单项的 `.hidden`(display:none) CSS 隐藏入口（Sidebar.vue 第 23/79/179 行）。
 *   本测试按此“实情”断言：菜单入口隐藏 + 直达不被拦截（并 log 说明）。
 */
test.describe('用户管理 / 权限', { tag: ['@admin'] }, () => {
  // 清空注入的 storageState，强制走实时 UI 登录使 user/isAdmin 生效
  test.use({ storageState: { cookies: [], origins: [] } })

  test('@p1 普通用户：侧边栏无“用户管理”入口，且直达 /admin/users 不被路由拦截', async ({
    page,
  }) => {
    await loginAs(page, 'user')

    // 侧边栏菜单项存在于 DOM 但通过 .menu-item.hidden{display:none} 隐藏 → toBeHidden 成立
    await expect(sidebarLink(page, '用户管理')).toBeHidden()

    // 直达 /admin/users。注意：这是一次硬跳转/刷新，会使 Pinia user 变 null，
    // 但 isLoggedIn=!!token 仍为真，故路由守卫放行（无管理员拦截）。
    await page.goto('/admin/users')

    // 实情断言：未被重定向到 /login 或 /dashboard，路由确实可达并渲染主布局。
    await expect(page).toHaveURL(/\/admin\/users/)
    await expect(page.locator('.main-layout')).toBeVisible()
    // eslint-disable-next-line no-console
    console.log(
      '[router 实情] /admin/users 对普通用户无重定向：守卫仅校验 token(isLoggedIn)，' +
        '无角色拦截；入口仅靠侧边栏 .hidden(display:none) 隐藏。',
    )
  })

  test('@p1 管理员：经侧边栏进入 /admin/users，用户表格渲染并含 admin', async ({ page }) => {
    await loginAs(page, 'admin')

    // 通过侧边栏点击进入（不刷新，保持实时登录的 user/isAdmin）
    const link = sidebarLink(page, '用户管理')
    await expect(link).toBeVisible()
    await link.click()
    await expect(page).toHaveURL(/\/admin\/users/)

    // 表格渲染：UserManagement.vue 使用 <el-table :data="users"> → .el-table
    const table = page.locator('.el-table')
    await expect(table).toBeVisible()

    // 已知种子账号 admin 应出现在“用户名”列
    await expect(table.getByText('admin', { exact: true })).toBeVisible({ timeout: 15_000 })
  })

  test('@p2 新增并删除用户：唯一用户 → 出现 → 删除（确认框）→ 消失', async ({ page }) => {
    await loginAs(page, 'admin')

    // 经侧边栏进入，保持 admin 实时身份
    await sidebarLink(page, '用户管理').click()
    await expect(page).toHaveURL(/\/admin\/users/)

    const table = page.locator('.el-table')
    await expect(table).toBeVisible()

    // 唯一的一次性用户名，避免污染种子账号（admin/user/viewer）
    const uniqueName = `e2e_user_${Date.now()}`

    // 添加表单（UserManagement.vue「➕ 添加用户」区块，inline el-form）：
    //   用户名 el-input / 密码 el-input(type=password) / 角色 el-select / 「添加」按钮(submit)
    await addUserField(page, '用户名').fill(uniqueName)
    await addUserField(page, '密码').fill('e2ePass123')
    // 角色默认 user，无需更改。提交。
    await page.getByRole('button', { name: '添加', exact: true }).click()

    // 添加成功提示 + 表格刷新后出现该用户
    await expect(page.getByText('用户已添加')).toBeVisible({ timeout: 15_000 })
    const newRow = table.locator('tr').filter({ hasText: uniqueName })
    await expect(newRow.getByText(uniqueName, { exact: true })).toBeVisible({ timeout: 15_000 })

    // 删除：该行内「删除」按钮（type=danger）
    await newRow.getByRole('button', { name: '删除', exact: true }).click()

    // 确认框 teleport 到 body：ElMessageBox.confirm(`确定删除用户 ${name}？`, '确认')
    // 未配置 zh locale 时默认确认按钮文本可能是 OK 而非「确定」，故点击主按钮更稳。
    const dialog = page.locator('.el-message-box')
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText(`确定删除用户 ${uniqueName}`)
    await dialog.locator('.el-message-box__btns .el-button--primary').click()

    // 删除成功提示 + 表格刷新后该用户消失
    await expect(page.getByText('已删除')).toBeVisible({ timeout: 15_000 })
    await expect(table.getByText(uniqueName, { exact: true })).toHaveCount(0, { timeout: 15_000 })
  })

  /**
   * 2026-06-07 回归：PUT /auth/users/<id>/ {is_active:false} 之前 400，
   * 因为 DRF 默认 ModelViewSet.update() 不传 partial=True。
   * 修复在 UserManagementViewSet.update() 中强制 partial=True。
   * 该用例负责：点击「禁用」按钮 → 后端 200 → 状态文案变「已禁用」 → 再次点击 → 启用。
   */
  test('@p2 禁用 / 启用用户：单字段 PUT 200 后状态文案切换', async ({ page }) => {
    await loginAs(page, 'admin')
    await sidebarLink(page, '用户管理').click()
    await expect(page).toHaveURL(/\/admin\/users/)

    const table = page.locator('.el-table')
    await expect(table).toBeVisible()

    const uniqueName = `e2e_toggle_${Date.now()}`
    await addUserField(page, '用户名').fill(uniqueName)
    await addUserField(page, '密码').fill('e2ePass123')
    await page.getByRole('button', { name: '添加', exact: true }).click()
    await expect(page.getByText('用户已添加')).toBeVisible({ timeout: 15_000 })

    const row = table.locator('tr').filter({ hasText: uniqueName })
    await expect(row).toBeVisible({ timeout: 15_000 })

    // 1) 禁用：点该行的「禁用」按钮 → 后端 200 → 状态变 已禁用
    const toggleBtn = row.getByRole('button', { name: '禁用', exact: true })
    await expect(toggleBtn).toBeVisible()
    await toggleBtn.click()
    await expect(page.getByText('状态已更新')).toBeVisible({ timeout: 15_000 })
    // 表格刷新后状态文案变 已禁用，按钮文案变 启用
    await expect(row.getByText('已禁用', { exact: true })).toBeVisible({ timeout: 15_000 })
    await expect(row.getByRole('button', { name: '启用', exact: true })).toBeVisible()

    // 2) 启用：点「启用」按钮 → 状态回到 active
    await row.getByRole('button', { name: '启用', exact: true }).click()
    await expect(page.getByText('状态已更新')).toBeVisible({ timeout: 15_000 })
    await expect(row.getByRole('button', { name: '禁用', exact: true })).toBeVisible()

    // 清理：删除该用户
    await row.getByRole('button', { name: '删除', exact: true }).click()
    const dialog = page.locator('.el-message-box')
    await expect(dialog).toBeVisible()
    await dialog.locator('.el-message-box__btns .el-button--primary').click()
    await expect(page.getByText('已删除')).toBeVisible({ timeout: 15_000 })
  })
})
