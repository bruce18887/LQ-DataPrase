import { test, expect } from '@playwright/test'
import { gotoApp } from '../helpers/nav'

/**
 * 系统设置页（/settings）— 左侧竖排标签页布局（SettingsPage.vue）。
 * 仅需登录态（项目级注入 admin storageState，不清空）。
 * 关键交互：加载设置（GET /auth/settings/）、保存（PUT /auth/settings/）、恢复默认（ElMessageBox 确认）。
 */

const TABS = [
  { label: '📊 显示设置', content: '图表渲染引擎' },
  { label: '📋 表格设置', content: '默认每页行数' },
  { label: '📐 CPK 阈值', content: 'CPK A 级阈值' },
  { label: '📄 导出模板', content: '导出文件名' },
  { label: '📁 存储路径', content: '数据目录' },
  { label: '🕐 最近文件', content: '最多保留' },
]

async function clickTab(page: import('@playwright/test').Page, label: string) {
  await page.getByRole('tab', { name: label }).click()
}

test.describe('@p1 系统设置页', { tag: ['@p1', '@settings'] }, () => {
  test('页面渲染：6 个标签页与关键设置区块可见', async ({ page }) => {
    await gotoApp(page, '/settings')

    // 页面标题（SettingsPage.vue <h2>⚙️ 系统设置</h2>）
    await expect(page.getByRole('heading', { name: '系统设置' })).toBeVisible()

    // 6 个 tab 标签（SettingsPage.vue el-tab-pane）
    for (const tab of TABS) {
      await expect(page.getByRole('tab', { name: tab.label })).toBeVisible()
    }

    // 操作按钮（全局，不随 tab 切换）
    await expect(page.getByRole('button', { name: '💾 保存设置' })).toBeVisible()
    await expect(page.getByRole('button', { name: '🔄 恢复默认' })).toBeVisible()
  })

  test('切换各标签页 → 对应设置内容可见', async ({ page }) => {
    await gotoApp(page, '/settings')

    for (const tab of TABS) {
      await clickTab(page, tab.label)
      await expect(page.getByText(tab.content).first()).toBeVisible()
    }
  })

  test('修改设置项并保存 → PUT /auth/settings/ 且出现成功提示', async ({ page }) => {
    await gotoApp(page, '/settings')

    // 进入「显示设置」标签页，修改一个安全的数值字段：图表 DPI
    await clickTab(page, '📊 显示设置')
    const dpiInput = page
      .getByText('图表 DPI')
      .locator('xpath=ancestor::*[contains(@class,"el-form-item")]')
      .getByRole('spinbutton')
    await expect(dpiInput).toBeVisible()
    await dpiInput.fill('200')
    // 触发 el-input-number 的 change（失焦提交值）
    await dpiInput.blur()

    // 点击保存并断言发生 PUT /auth/settings/
    const [response] = await Promise.all([
      page.waitForResponse(
        (resp) => /\/auth\/settings\//.test(resp.url()) && resp.request().method() === 'PUT'
      ),
      page.getByRole('button', { name: '💾 保存设置' }).click(),
    ])
    expect(response.request().method()).toBe('PUT')

    // 成功 ElMessage — 限定 .el-message 避免命中标题/按钮文本
    await expect(page.locator('.el-message').filter({ hasText: /保存|成功/ })).toBeVisible()
  })
})

test.describe('@p2 恢复默认', { tag: ['@p2', '@settings'] }, () => {
  test('点击恢复默认 → 确认对话框 → 提示已恢复', async ({ page }) => {
    await gotoApp(page, '/settings')

    // 触发 ElMessageBox.confirm
    await page.getByRole('button', { name: '🔄 恢复默认' }).click()

    // 确认框 teleport 到 body（.el-message-box）
    const messageBox = page.locator('.el-message-box')
    await expect(messageBox).toBeVisible()
    await expect(messageBox.getByText('确定恢复所有设置为默认值吗？')).toBeVisible()

    // 点击「确定」
    await messageBox.getByRole('button', { name: '确定' }).click()

    // 成功 ElMessage
    await expect(page.locator('.el-message').filter({ hasText: /已恢复默认|恢复/ })).toBeVisible()
  })
})
