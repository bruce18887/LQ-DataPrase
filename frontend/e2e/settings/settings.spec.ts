import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'

/**
 * 系统设置页（/settings）。
 * 仅需登录态（项目级注入 admin storageState，不清空）。
 * 关键交互：加载设置（GET /auth/settings/）、保存（PUT /auth/settings/）、恢复默认（ElMessageBox 确认）。
 */

test.describe('@p1 系统设置页', { tag: ['@p1', '@settings'] }, () => {
  test('页面渲染：标题与关键设置区块可见', async ({ page }) => {
    await gotoApp(page, '/settings')

    // 页面标题（SettingsPage.vue:3 <h2>⚙️ 系统设置</h2>）
    await expect(page.getByRole('heading', { name: '系统设置' })).toBeVisible()

    // 各 el-card 区块标题（SettingsPage.vue:7/49/86/128）
    await expect(page.getByText('图表与显示')).toBeVisible()
    await expect(page.getByText('表格设置')).toBeVisible()
    await expect(page.getByText('CPK 阈值设置')).toBeVisible()
    await expect(page.getByText('最近文件列表')).toBeVisible()

    // 操作按钮（SettingsPage.vue:158/161）
    await expect(page.getByRole('button', { name: '💾 保存设置' })).toBeVisible()
    await expect(page.getByRole('button', { name: '🔄 恢复默认' })).toBeVisible()
  })

  test('修改设置项并保存 → PUT /auth/settings/ 且出现成功提示', async ({ page }) => {
    await gotoApp(page, '/settings')

    // 修改一个安全的数值字段：图表 DPI（el-input-number → role="spinbutton"，SettingsPage.vue:28-33）
    const dpiInput = page
      .getByText('图表 DPI')
      .locator('xpath=ancestor::*[contains(@class,"el-form-item")]')
      .getByRole('spinbutton')
    await expect(dpiInput).toBeVisible()
    await dpiInput.fill('200')
    // 触发 el-input-number 的 change（失焦提交值）
    await dpiInput.blur()

    // 点击保存并断言发生 PUT /auth/settings/（saveSettings → authApi.updateSettings，SettingsPage.vue:253-264 / auth.ts:19-21）
    const [response] = await Promise.all([
      page.waitForResponse(
        (resp) => /\/auth\/settings\//.test(resp.url()) && resp.request().method() === 'PUT'
      ),
      page.getByRole('button', { name: '💾 保存设置' }).click(),
    ])
    expect(response.request().method()).toBe('PUT')

    // 成功 ElMessage（SettingsPage.vue:260 '设置已保存'）— 限定 .el-message 避免命中标题/按钮文本
    await expect(page.locator('.el-message').filter({ hasText: /保存|成功/ })).toBeVisible()
  })
})

test.describe('@p2 恢复默认', { tag: ['@p2', '@settings'] }, () => {
  test('点击恢复默认 → 确认对话框 → 提示已恢复', async ({ page }) => {
    await gotoApp(page, '/settings')

    // 触发 ElMessageBox.confirm（SettingsPage.vue:266-279）
    await page.getByRole('button', { name: '🔄 恢复默认' }).click()

    // 确认框 teleport 到 body（.el-message-box），正文与按钮可见
    const messageBox = page.locator('.el-message-box')
    await expect(messageBox).toBeVisible()
    await expect(messageBox.getByText('确定恢复所有设置为默认值吗？')).toBeVisible()

    // 点击「确定」按钮（confirmButtonText: '确定'，SettingsPage.vue:271）
    await messageBox.getByRole('button', { name: '确定' }).click()

    // 成功 ElMessage（SettingsPage.vue:275 '已恢复默认设置（请点击保存以持久化）'）—限定 .el-message
    await expect(page.locator('.el-message').filter({ hasText: /已恢复默认|恢复/ })).toBeVisible()
  })
})
