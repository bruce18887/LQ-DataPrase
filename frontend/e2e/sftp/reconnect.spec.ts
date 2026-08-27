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
  // 断线续连的 initial 是异步到达的：等待表单预填稳定后再 fill，
  // 否则 fill 与 applyInitial 竞争会把 host 写入两次（host 变
  // 127.0.0.1127.0.0.1，连接失败）。同款竞争是 sftp.spec.ts 已有的
  // 「等两次读取一致」模式（R4）。
  const host = page.getByPlaceholder('例如: 192.168.1.1')
  await expect.poll(async () => {
    const v1 = await host.inputValue()
    await page.waitForTimeout(300)
    const v2 = await host.inputValue()
    return v1 === v2
  }, { timeout: 10_000 }).toBe(true)
  await host.fill(srv.host)
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

test.describe('@sftp SFTP 浏览器增强：类型过滤 / 文件进度 / 下载超时', { tag: ['@sftp'] }, () => {
  /** 回根目录：点面包屑 Home（子目录内可能残留上次运行路径），等到 sub1 目录行可见 */
  async function goRoot(page: Parameters<typeof gotoApp>[0]) {
    await page.locator('.toolbar-card .el-breadcrumb__item').first().click()
    await expect(page.locator('.file-name', { hasText: 'sub1' })).toBeVisible({ timeout: 15_000 })
  }

  test('@p1 类型过滤：默认仅 CSV 隐藏非 CSV，切换全部文件后可见', async ({ page }) => {
    await gotoApp(page, '/sftp')
    await manualConnect(page, server)
    await goRoot(page)

    // 默认「仅 CSV」：CSV 可见、非 CSV（notes.txt）隐藏
    await expect(page.locator('.file-name', { hasText: 'root.csv' })).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.file-name', { hasText: 'notes.txt' })).toHaveCount(0)

    // 切到「全部文件」→ notes.txt 出现（带「仅支持 CSV」标签）
    await page.getByTestId('sftp-type-filter').click()
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item', { hasText: '全部文件' }).click()
    await expect(page.locator('.file-name', { hasText: 'notes.txt' })).toBeVisible({ timeout: 10_000 })
    await expect(page.locator('.file-table tr', { hasText: 'notes.txt' })).toContainText('仅支持 CSV')

    // 切回「仅 CSV」→ notes.txt 重新隐藏；目录/CSV 仍在
    await page.getByTestId('sftp-type-filter').click()
    await page.locator('.el-select-dropdown:visible .el-select-dropdown__item', { hasText: '仅 CSV' }).click()
    await expect(page.locator('.file-name', { hasText: 'notes.txt' })).toHaveCount(0)
    await expect(page.locator('.file-name', { hasText: 'root.csv' })).toBeVisible({ timeout: 10_000 })
    await expect(page.locator('.file-name', { hasText: 'sub1' })).toBeVisible({ timeout: 10_000 })

    await disconnect(page)
  })

  test('@p1 单文件下载：SSE 进度卡片（百分比+速率）出现并完成导入', async ({ page }) => {
    await gotoApp(page, '/sftp')
    await manualConnect(page, server)
    await goRoot(page)

    // 定位 big.csv 行的「下载」按钮
    const bigRow = page.locator('.file-table .el-table__row').filter({
      has: page.locator('.file-name', { hasText: 'big.csv' }),
    })
    await expect(bigRow).toBeVisible({ timeout: 15_000 })

    // SSE 进度卡片出现（下载开始即渲染），包含百分比与速率文案
    await bigRow.getByRole('button', { name: '下载' }).click()
    await expect(page.locator('.download-progress-card')).toBeVisible({ timeout: 10_000 })
    await expect(page.locator('.download-progress-card')).toContainText(/%|正在下载 big\.csv/)
    await expect(page.locator('.download-progress-card')).toContainText(/MB\/s/)

    // 完成：成功提示 + 文件注册出现（重名会带时间戳后缀，如 big_xxx.csv）
    await expect(page.getByText(/已导入: big/)).toBeVisible({ timeout: 60_000 })
    const token = await page.evaluate(() => localStorage.getItem('access_token'))
    await expect
      .poll(
        async () => {
          const resp = await page.request.get('/api/v1/files/?search=big.csv',
            { headers: { Authorization: `Bearer ${token}` } })
          if (!resp.ok()) return 0
          const data = (await resp.json()) as { count: number }
          return data.count
        },
        { timeout: 15_000 },
      )
      .toBeGreaterThan(0)

    await disconnect(page)
  })

  test('@p1 下载超时：工具栏自由设定并持久化到用户设置', async ({ page }) => {
    const restoreTimeout = () => page.evaluate(async () => {
      await fetch('/api/v1/auth/settings/', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('access_token')}`,
        },
        body: JSON.stringify({ sftp_download_timeout: 600 }),
      })
    })
    try {
      // 起点：恢复默认 600 再 reload（刷新后重新读取用户设置；同时保证上次
      // 运行残留的 900 不把断言污染）。reload 后必须先等预填稳定再手动连接
      // （断线续连的 initial 是异步到达的，与 manualConnect 的 fill 竞争会
      // 导致 host 被写入两次——见截图失败特征 host=127.0.0.1127.0.0.1）。
      await gotoApp(page, '/sftp')
      await restoreTimeout()
      await page.reload()
      const host = page.getByPlaceholder('例如: 192.168.1.1')
      await expect.poll(async () => {
        const v1 = await host.inputValue()
        await page.waitForTimeout(300)
        const v2 = await host.inputValue()
        return v1 === v2
      }, { timeout: 10_000 }).toBe(true)
      await manualConnect(page, server)

      const timeoutInput = page.getByTestId('sftp-timeout-input').locator('input')
      await expect(timeoutInput).toHaveValue('600', { timeout: 15_000 })

      // 修改为 900 → blur 触发保存 → 成功提示（el-input-number 输入+blur 可能
      // 各发一次，用 .first() 避免 strict mode 双元素冲突）
      await timeoutInput.fill('900')
      await timeoutInput.blur()
      await expect(page.getByText(/下载超时已设为 900 秒/).first()).toBeVisible({ timeout: 10_000 })

      // 持久化校验：GET /auth/settings/ 返回 900
      await expect
        .poll(async () => {
          const value = await page.evaluate(async () => {
            const resp = await fetch('/api/v1/auth/settings/', {
              headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
            })
            if (!resp.ok) return null
            return (await resp.json()).sftp_download_timeout
          })
          return value
        }, { timeout: 10_000 })
        .toBe(900)

      await disconnect(page)
    } finally {
      await restoreTimeout()
    }
  })
})
