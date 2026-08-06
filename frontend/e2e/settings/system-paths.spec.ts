import { test, expect, type Page } from '@playwright/test'
import path from 'node:path'
import os from 'node:os'
import { gotoApp } from '../helpers/nav'
import { uiLogin } from '../helpers/auth'
import { ACCOUNTS } from '../fixtures/test-data'

/**
 * 系统存储路径（系统设置 → 📁 存储路径，GET/PUT /api/v1/system/paths/）。
 *
 * 注意：
 * - 路径修改不重启后端，e2e 只验证「写入配置 + restart_required 提示」链路，
 *   绝不 PUT 真实的 data_dir（并行 worker 共享 dev DB，迁移只发生在重启时）。
 * - 配置文件位置由 playwright.config.ts 注入 LQDP_SYSTEM_CONFIG_FILE 隔离到
 *   临时文件；本 spec 仍会在每个用例结束后把配置恢复为快照值，
 *   兼容 reuseExistingServer / PW_NO_WEBSERVER 手动起服务的场景。
 */

const PATHS_API = '/api/v1/system/paths/'

interface PathsSnapshot {
  data_dir: string | null
  temp_dir: string | null
}

async function getPaths(page: Page): Promise<PathsSnapshot> {
  const token = await page.evaluate(() => localStorage.getItem('access_token'))
  const resp = await page.request.get(PATHS_API, {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(resp.ok()).toBeTruthy()
  const data = (await resp.json()) as { configured: PathsSnapshot }
  return { ...data.configured }
}

async function restorePaths(page: Page, snapshot: PathsSnapshot): Promise<void> {
  const token = await page.evaluate(() => localStorage.getItem('access_token'))
  await page.request.put(PATHS_API, {
    headers: { Authorization: `Bearer ${token}` },
    data: { data_dir: snapshot.data_dir ?? null, temp_dir: snapshot.temp_dir ?? null },
  })
}

test.describe.configure({ mode: 'serial' })

test.describe('@p2 系统存储路径', { tag: ['@p2', '@settings'] }, () => {
  test('管理员：显示路径区块与可编辑控件', async ({ page }) => {
    await gotoApp(page, '/settings')
    await page.getByRole('tab', { name: '📁 存储路径' }).click()

    // 只读展示行
    await expect(page.getByText('数据库文件')).toBeVisible()
    await expect(page.getByText('配置文件')).toBeVisible()
    await expect(page.getByText('上传数据目录')).toBeVisible()
    // 管理员可编辑：两个目录输入框 + 保存按钮
    const rows = page.locator('tr').filter({ hasText: '临时文件目录' })
    await expect(rows.getByRole('textbox')).toBeVisible()
    await expect(page.getByRole('button', { name: '💾 保存路径' })).toBeVisible()
  })

  test('管理员：修改临时文件目录 → 保存 → 重启确认框（配置可恢复）', async ({ page }) => {
    await gotoApp(page, '/settings')
    const snapshot = await getPaths(page)

    try {
      await page.getByRole('tab', { name: '📁 存储路径' }).click()

      // 修改临时文件目录为系统临时目录下的子目录
      const newTempDir = path.join(os.tmpdir(), `lqdp-e2e-tmp-${Date.now()}`)
      const tempRow = page.locator('tr').filter({ hasText: '临时文件目录' })
      await tempRow.getByRole('textbox').fill(newTempDir)

      // 保存 → PUT /system/paths/ 发出
      const [response] = await Promise.all([
        page.waitForResponse(
          (resp) => resp.url().includes(PATHS_API) && resp.request().method() === 'PUT'
        ),
        page.getByRole('button', { name: '💾 保存路径' }).click(),
      ])
      expect(response.ok()).toBeTruthy()

      // 成功提示 + 重启确认框
      await expect(page.locator('.el-message').filter({ hasText: /已保存|保存/ })).toBeVisible()
      const restartBox = page.locator('.el-message-box')
      await expect(restartBox).toBeVisible()
      await expect(restartBox.getByText(/重启应用后生效/)).toBeVisible()
      await restartBox.getByRole('button', { name: '稍后再说' }).click()
    } finally {
      await restorePaths(page, snapshot)
    }
  })

  test('管理员：非法路径保存 → 400 错误提示且无重启框', async ({ page }) => {
    await gotoApp(page, '/settings')
    const snapshot = await getPaths(page)

    try {
      await page.getByRole('tab', { name: '📁 存储路径' }).click()

      const tempRow = page.locator('tr').filter({ hasText: '临时文件目录' })
      await tempRow.getByRole('textbox').fill('relative/path')

      const [response] = await Promise.all([
        page.waitForResponse(
          (resp) => resp.url().includes(PATHS_API) && resp.request().method() === 'PUT'
        ),
        page.getByRole('button', { name: '💾 保存路径' }).click(),
      ])
      expect(response.status()).toBe(400)

      // 错误 toast 出现，重启确认框不出现
      await expect(page.locator('.el-message').filter({ hasText: /绝对路径/ })).toBeVisible()
      await expect(page.locator('.el-message-box')).toHaveCount(0)
    } finally {
      await restorePaths(page, snapshot)
    }
  })

})

test.describe('@p2 系统存储路径（非管理员）', { tag: ['@p2', '@settings'] }, () => {
  // 清空项目级注入的 admin storageState，强制实时 UI 登录（admin.spec.ts 先例）
  test.use({ storageState: { cookies: [], origins: [] } })

  test('非管理员：路径只读、无编辑控件', async ({ page }) => {
    await uiLogin(page, ACCOUNTS.user.username, ACCOUNTS.user.password)
    // 等待登录 POST 完成并跳转（loginAs 先例），避免 goto 打断在途登录
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 })
    await gotoApp(page, '/settings')
    await page.getByRole('tab', { name: '📁 存储路径' }).click()

    await expect(page.getByText('数据库文件')).toBeVisible()
    // 无「保存路径」按钮、无输入框
    await expect(page.getByRole('button', { name: '💾 保存路径' })).toHaveCount(0)
    const tempRow = page.locator('tr').filter({ hasText: '临时文件目录' })
    await expect(tempRow.getByRole('textbox')).toHaveCount(0)
    await expect(page.getByText(/仅管理员可修改/)).toBeVisible()
  })
})
