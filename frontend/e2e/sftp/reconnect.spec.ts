import { test, expect, type Locator } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { startSftpServer, type SftpTestServer } from '../helpers/sftpServer'

/**
 * SFTP 断线续连（记住上次路径）端到端用例。
 *
 * 前置：beforeAll 启动本地 paramiko SFTP 服务器（任意账号密码，root 临时目录，
 * 内含 sub1/sample.csv + root.csv）。用例以「断开」收尾，避免 SFTP 会话泄漏。
 *
 * 后端记录模型：UserSetting.sftp_last_*（per-user，跨登录保留）。
 * 分层重连：保存配置连接 → 自动重连；手动连接 → 预填表单 + 路径提示。
 */
const PASSWORD = 'e2e123'

let server: SftpTestServer

function fieldByLabel(page: Parameters<typeof gotoApp>[0], label: string): Locator {
  return page
    .locator('.connect-form .el-form-item')
    .filter({ has: page.locator('.el-form-item__label', { hasText: label }) })
    .locator('input')
    .first()
}

async function manualConnect(page: Parameters<typeof gotoApp>[0], srv: SftpTestServer) {
  await page.getByPlaceholder('例如: 192.168.1.1').fill(srv.host)
  await fieldByLabel(page, '端口').fill(String(srv.port))
  // el-input-number 需 blur 才发射 update:model-value（R4）
  await fieldByLabel(page, '端口').blur()
  await fieldByLabel(page, '用户名').fill('e2e')
  await fieldByLabel(page, '密码').fill(PASSWORD)
  await page.getByRole('button', { name: '连接' }).click()
  await expect(page.locator('.toolbar-card')).toBeVisible({ timeout: 15_000 })
}

async function enterSub1(page: Parameters<typeof gotoApp>[0]) {
  // 页面可能因上次运行残留的 last_path 直接落在 /sub1 内部（只有 sample.csv、
  // 无 sub1 目录行）——先点面包屑 Home 回到 root，再进入 sub1，对任意初始路径稳健
  const breadcrumb = page.locator('.toolbar-card .el-breadcrumb')
  await page.locator('.toolbar-card .el-breadcrumb__item').first().click()
  await expect(page.locator('.file-name', { hasText: 'sub1' })).toBeVisible({ timeout: 15_000 })
  await page.locator('.file-name', { hasText: 'sub1' }).first().click()
  await expect(breadcrumb).toContainText('sub1', { timeout: 15_000 })
}

async function disconnect(page: Parameters<typeof gotoApp>[0]) {
  await page.getByRole('button', { name: '断开' }).click()
  await expect(page.locator('.connect-card')).toBeVisible({ timeout: 15_000 })
}

test.beforeAll(async () => {
  server = await startSftpServer()
})

test.afterAll(async () => {
  server?.stop()
})

// 后端 SFTP 会话/断线续连记录按 user_id 存储，多 worker 并行会互相覆盖
// （R6：共享后端状态类测试必须串行）。统一 @p1 让该文件只由 P1 project
// 承接，serial 保证文件内用例顺序执行——全量运行时绝无第二个 worker 碰它。
test.describe.configure({ mode: 'serial' })

test.describe('@sftp SFTP 断线续连', { tag: ['@sftp'] }, () => {
  test('@p1 手动连接：断开后表单预填，重连自动跳回上次路径', async ({ page }) => {
    await gotoApp(page, '/sftp')

    // 手动连接 → 进入 sub1
    await manualConnect(page, server)
    await enterSub1(page)

    // 断开 → 表单出现且 host/port/username 已预填 + 路径提示
    await disconnect(page)
    await expect(page.getByPlaceholder('例如: 192.168.1.1')).toHaveValue(server.host)
    await expect(fieldByLabel(page, '端口')).toHaveValue(String(server.port))
    await expect(fieldByLabel(page, '用户名')).toHaveValue('e2e')
    await expect(page.locator('.path-hint')).toContainText('/sub1')

    // 只填密码重连 → 自动跳回 sub1
    await fieldByLabel(page, '密码').fill(PASSWORD)
    await page.getByRole('button', { name: '连接' }).click()
    await expect(page.locator('.toolbar-card')).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.toolbar-card .el-breadcrumb')).toContainText('sub1', { timeout: 15_000 })

    await disconnect(page)
  })

  test('@p1 保存配置：重新登录后自动重连并恢复路径', async ({ page }) => {
    const configName = `e2e_reconnect_${Date.now()}`
    await gotoApp(page, '/sftp')

    // 手动连接 → 进 sub1（记录 last_path）
    await manualConnect(page, server)
    await enterSub1(page)

    // 断开 → 表单预填（来自本次连接记录）；先填密码再保存配置——
    // 保存时密码为空会生成「无密码配置」，无法服务端自动重连（can_auto_connect 依赖 password_encrypted）
    await disconnect(page)
    await fieldByLabel(page, '密码').fill(PASSWORD)
    await page.getByRole('button', { name: '保存配置' }).click()
    await page.locator('.el-dialog').getByPlaceholder('请输入配置名称').fill(configName)
    await page.locator('.el-dialog').getByRole('button', { name: '保存' }).click()
    await expect(page.locator('.el-dialog')).toBeHidden({ timeout: 10_000 })

    // 加载保存的配置（密码留空，走后端解密分支）→ 连接 → 自动恢复 /sub1
    await page.locator('.config-item').filter({ hasText: configName }).getByRole('button', { name: '加载' }).click()
    await page.getByRole('button', { name: '连接' }).click()
    await expect(page.locator('.toolbar-card')).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.toolbar-card .el-breadcrumb')).toContainText('sub1', { timeout: 15_000 })

    // 模拟重新登录：刷新页面 → 自动重连并直接恢复 sub1
    await page.reload()
    await expect(page.locator('.toolbar-card')).toBeVisible({ timeout: 20_000 })
    await expect(page.locator('.connect-card')).toHaveCount(0)
    await expect(page.locator('.toolbar-card .el-breadcrumb')).toContainText('sub1', { timeout: 15_000 })

    // 收尾：断开 + 删除配置，避免污染后续用例
    await disconnect(page)
    await page.locator('.config-item').filter({ hasText: configName }).getByRole('button', { name: '删除配置' }).click()
    await page.locator('.el-message-box').getByRole('button', { name: '删除' }).click()
    await expect(page.locator('.config-item').filter({ hasText: configName })).toHaveCount(0, { timeout: 10_000 })
  })

  test('@p1 手动连接：重新登录后预填表单并提示上次路径', async ({ page }) => {
    await gotoApp(page, '/sftp')

    await manualConnect(page, server)
    await enterSub1(page)
    await disconnect(page)

    // 刷新 = 重新登录 → 手动连接场景不自动重连，预填表单 + 路径提示
    await page.reload()
    await expect(page.locator('.connect-card')).toBeVisible({ timeout: 20_000 })
    await expect(page.getByPlaceholder('例如: 192.168.1.1')).toHaveValue(server.host)
    await expect(fieldByLabel(page, '端口')).toHaveValue(String(server.port))
    await expect(fieldByLabel(page, '用户名')).toHaveValue('e2e')
    await expect(page.locator('.path-hint')).toContainText('/sub1')

    // 收尾：断开（此刻未连接，仅清状态）
    await expect(page.getByRole('button', { name: '断开' })).toHaveCount(0)
  })
})
