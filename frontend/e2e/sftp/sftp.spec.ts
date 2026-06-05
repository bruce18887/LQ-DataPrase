import { test, expect, type Locator } from '@playwright/test'
import { gotoApp } from '../helpers/nav'
import { captureDownload } from '../helpers/download'

/**
 * SFTP 浏览器（/sftp）端到端用例。
 *
 * 设计要点：
 * - 渲染/UI 用例（连接表单字段、连接按钮、保存配置区）始终运行并通过，不依赖真实 SFTP 服务。
 * - 真实连接 / 下载用例通过环境变量 GATE：
 *     SFTP_HOST / SFTP_PORT / SFTP_USERNAME / SFTP_PASSWORD
 *   未设置 SFTP_HOST 时 `test.skip(...)` 并打印日志（CI/本地通常无 SFTP 凭据）。
 *
 * 选择器来源（src/pages/sftp/SftpBrowser.vue）：
 * - 主机输入：getByPlaceholder('例如: 192.168.1.1')            （行 36）
 * - 端口：el-input-number（无 placeholder），在「端口」el-form-item 内（行 42-44）
 * - 用户名/密码：无 placeholder，仅 el-form-item label「用户名」「密码」（行 47-54）
 *   → 通过 .el-form-item（含 label 文本）内的输入框定位
 * - 连接按钮：button「连接」（含图标，行 58-60）
 * - 保存配置按钮：button「保存配置」（行 61-63）
 * - 已保存配置区：.saved-configs（仅 savedConfigs.length>0 时渲染，数据来自 localStorage 'sftp_configs'，行 68-104）
 * - 连接后文件表：.file-table / el-table（行 152-157）；断开按钮「断开」（行 143-145）；行内下载按钮「下载」（行 192）
 *
 * 注意：组件的“已保存配置”读取 localStorage（loadSavedConfigs / 'sftp_configs'，行 278-287），
 *       并未调用 sftpApi.getConfigs()（GET /sftp/configs/）。因此 @p2 既验证组件的本地态行为，
 *       又直接打后端 GET /sftp/configs/ 断言 200（后端 SftpViewSet.configs 返回 {configs: []}）。
 */

const SFTP_HOST = process.env.SFTP_HOST
const SFTP_PORT = process.env.SFTP_PORT || '22'
const SFTP_USERNAME = process.env.SFTP_USERNAME
const SFTP_PASSWORD = process.env.SFTP_PASSWORD

/** 返回包含指定 label 文本的 el-form-item 内的输入框（用于无 placeholder 的字段） */
function fieldByLabel(page: Parameters<typeof gotoApp>[0], label: string): Locator {
  return page
    .locator('.connect-form .el-form-item')
    .filter({ has: page.locator('.el-form-item__label', { hasText: label }) })
    .locator('input')
    .first()
}

test.describe('@p1 SFTP 页面渲染', { tag: ['@p1', '@sftp'] }, () => {
  test('连接表单字段 + 连接按钮 + 保存配置区可见', async ({ page }) => {
    await gotoApp(page, '/sftp')

    // 头部标题
    await expect(page.getByRole('heading', { name: 'SFTP 浏览器' })).toBeVisible()

    // 连接配置卡片
    await expect(page.locator('.connect-card')).toBeVisible()

    // 主机（有 placeholder）
    const host = page.getByPlaceholder('例如: 192.168.1.1')
    await expect(host).toBeVisible()

    // 端口：el-input-number 在窄列(span=4)+90px label 下内部 input 宽度可能塌缩，
    // 故断言其 form-item 容器可见（而非内部 input）。
    const portItem = page
      .locator('.connect-form .el-form-item')
      .filter({ has: page.locator('.el-form-item__label', { hasText: '端口' }) })
    await expect(portItem).toBeVisible()
    await expect(portItem.locator('.el-input-number')).toBeVisible()

    // 用户名 / 密码（无 placeholder，按 label 定位）
    const username = fieldByLabel(page, '用户名')
    const password = fieldByLabel(page, '密码')
    await expect(username).toBeVisible()
    await expect(password).toBeVisible()
    // 密码字段类型为 password（show-password 切换前默认 password）
    await expect(password).toHaveAttribute('type', 'password')

    // 连接按钮（含图标，按可访问名匹配「连接」）
    await expect(page.getByRole('button', { name: '连接' })).toBeVisible()

    // 保存配置按钮（即“保存配置区”的入口，始终存在；未填 host 时 disabled）
    const saveBtn = page.getByRole('button', { name: '保存配置' })
    await expect(saveBtn).toBeVisible()
    await expect(saveBtn).toBeDisabled()
  })
})

test.describe('@p2 SFTP 已保存配置', { tag: ['@p2', '@sftp'] }, () => {
  test('GET /sftp/configs/ 返回 200，本地无配置时不渲染已保存配置区', async ({ page }) => {
    await gotoApp(page, '/sftp')

    // 1) 直接验证后端配置端点（带应用内 JWT，走 Vite /api 代理）返回 200。
    //    组件本身不调用该端点（其配置来自 localStorage），故用页内 fetch 主动验证后端契约。
    const status = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/sftp/configs/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      return res.status
    })
    expect(status).toBe(200)

    // 2) 组件态：localStorage 'sftp_configs' 为空 → .saved-configs 不渲染（v-if 守卫，行 68）。
    //    清空以确保确定态，然后重新进入页面断言空态（无已保存配置区）。
    await page.evaluate(() => localStorage.removeItem('sftp_configs'))
    await page.reload()
    await expect(page.locator('.main-layout')).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.connect-card')).toBeVisible()
    await expect(page.locator('.saved-configs')).toHaveCount(0)

    // 3) 写入一条本地配置 → 重新进入后已保存配置区出现且渲染该项（验证区域逻辑）。
    await page.evaluate(() => {
      localStorage.setItem(
        'sftp_configs',
        JSON.stringify([
          { name: 'e2e-cfg', host: '10.0.0.1', port: 22, username: 'tester', password: 'x' },
        ]),
      )
    })
    await page.reload()
    await expect(page.locator('.main-layout')).toBeVisible({ timeout: 15_000 })
    await expect(page.locator('.saved-configs')).toBeVisible()
    await expect(page.locator('.saved-configs .config-name')).toHaveText('e2e-cfg')

    // 清理本地态，避免污染其它用例
    await page.evaluate(() => localStorage.removeItem('sftp_configs'))
  })
})

test.describe('@p1 SFTP 真实连接（env-gated）', { tag: ['@p1', '@sftp'] }, () => {
  test('填表连接成功后出现文件列表/断开按钮', async ({ page }) => {
    test.skip(
      !SFTP_HOST,
      'set SFTP_HOST/PORT/USERNAME/PASSWORD to run real SFTP connect',
    )
    if (!SFTP_HOST) {
      // 兜底日志（理论上被上面的 skip 拦下，不会执行到这里）
      console.log('[sftp] SFTP_HOST 未设置，跳过真实连接用例')
      return
    }
    console.log(`[sftp] 真实连接：${SFTP_USERNAME}@${SFTP_HOST}:${SFTP_PORT}`)

    await gotoApp(page, '/sftp')

    await page.getByPlaceholder('例如: 192.168.1.1').fill(SFTP_HOST)

    // 端口：el-input-number，先清空再填
    const port = fieldByLabel(page, '端口')
    await port.fill('')
    await port.fill(SFTP_PORT)

    await fieldByLabel(page, '用户名').fill(SFTP_USERNAME ?? '')
    await fieldByLabel(page, '密码').fill(SFTP_PASSWORD ?? '')

    // 点击连接并等待 /sftp/connect/ 响应
    const [connectResp] = await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes('/sftp/connect/') && r.request().method() === 'POST',
        { timeout: 30_000 },
      ),
      page.getByRole('button', { name: '连接' }).click(),
    ])
    expect(connectResp.ok(), `connect 应返回 2xx，实际 ${connectResp.status()}`).toBeTruthy()

    // 连接后 UI：文件表与「断开」按钮出现（连接卡片消失）
    await expect(page.getByRole('button', { name: '断开' })).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('.file-table')).toBeVisible()
  })
})

test.describe('@p2 SFTP 真实下载（env-gated）', { tag: ['@p2', '@sftp'] }, () => {
  test('连接成功后下载首个文件', async ({ page }) => {
    test.skip(
      !SFTP_HOST,
      'set SFTP_HOST/PORT/USERNAME/PASSWORD to run real SFTP download',
    )
    if (!SFTP_HOST) {
      console.log('[sftp] SFTP_HOST 未设置，跳过真实下载用例')
      return
    }

    await gotoApp(page, '/sftp')

    await page.getByPlaceholder('例如: 192.168.1.1').fill(SFTP_HOST)
    const port = fieldByLabel(page, '端口')
    await port.fill('')
    await port.fill(SFTP_PORT)
    await fieldByLabel(page, '用户名').fill(SFTP_USERNAME ?? '')
    await fieldByLabel(page, '密码').fill(SFTP_PASSWORD ?? '')

    await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes('/sftp/connect/') && r.request().method() === 'POST',
        { timeout: 30_000 },
      ),
      page.getByRole('button', { name: '连接' }).click(),
    ])

    await expect(page.locator('.file-table')).toBeVisible({ timeout: 30_000 })

    // 等待文件列表加载（list_files 已在连接成功后触发）；定位首个“文件”行的下载按钮。
    const firstDownloadBtn = page
      .locator('.file-table')
      .getByRole('button', { name: '下载' })
      .first()

    // 当前目录可能全是文件夹（无可下载文件）时跳过，避免误判失败。
    if ((await firstDownloadBtn.count()) === 0) {
      test.skip(true, '已连接但当前目录无可下载文件')
      return
    }
    await expect(firstDownloadBtn).toBeVisible({ timeout: 30_000 })

    const { suggestedName, size } = await captureDownload(
      page,
      () => firstDownloadBtn.click(),
      'sftp',
    )
    console.log(`[sftp] 已下载文件 ${suggestedName}（${size} bytes）`)
    expect(size).toBeGreaterThan(0)
  })
})

test.describe('@p2 SFTP 下载解析（env-gated）', { tag: ['@p2', '@sftp'] }, () => {
  test('连接成功后下载并解析首个文件，/files/ 中出现该文件', async ({ page }) => {
    test.skip(
      !SFTP_HOST,
      'set SFTP_HOST/PORT/USERNAME/PASSWORD to run real SFTP download_and_parse',
    )
    if (!SFTP_HOST) {
      console.log('[sftp] SFTP_HOST 未设置，跳过下载解析用例')
      return
    }

    await gotoApp(page, '/sftp')

    await page.getByPlaceholder('例如: 192.168.1.1').fill(SFTP_HOST)
    const port = fieldByLabel(page, '端口')
    await port.fill('')
    await port.fill(SFTP_PORT)
    await fieldByLabel(page, '用户名').fill(SFTP_USERNAME ?? '')
    await fieldByLabel(page, '密码').fill(SFTP_PASSWORD ?? '')

    await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes('/sftp/connect/') && r.request().method() === 'POST',
        { timeout: 30_000 },
      ),
      page.getByRole('button', { name: '连接' }).click(),
    ])

    await expect(page.locator('.file-table')).toBeVisible({ timeout: 30_000 })

    // Find first file row's "解析" button
    const firstParseBtn = page
      .locator('.file-table')
      .getByRole('button', { name: '解析' })
      .first()

    if ((await firstParseBtn.count()) === 0) {
      test.skip(true, '已连接但当前目录无可解析文件')
      return
    }
    await expect(firstParseBtn).toBeVisible({ timeout: 30_000 })

    // Get the file name from the row
    const row = firstParseBtn.locator('xpath=ancestor::tr')
    const fileName = await row.locator('.file-name').textContent()

    // Click parse
    await firstParseBtn.click()

    // Wait for success message
    await expect(page.getByText(/已导入/).first()).toBeVisible({ timeout: 30_000 })

    // Verify the file appears in /files/ API
    const result = await page.evaluate(async () => {
      const token = localStorage.getItem('access_token')
      const res = await fetch('/api/v1/files/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      const data = await res.json()
      const files = Array.isArray(data) ? data : (data.results ?? [])
      return {
        status: res.status,
        files: files.map((f: any) => ({ id: f.id, filename: f.filename, file_type: f.file_type })),
      }
    })
    expect(result.status).toBe(200)
    expect(result.files.some((f: any) => f.filename === fileName)).toBe(true)
    console.log(`[sftp] 已下载解析文件 "${fileName}"，file_type: ${result.files.find((f: any) => f.filename === fileName)?.file_type}`)
  })
})

test.describe('@p2 SFTP 目录下载SSE（env-gated）', { tag: ['@p2', '@sftp'] }, () => {
  test('连接后点击目录下载，进度条出现并完成', async ({ page }) => {
    test.skip(
      !SFTP_HOST,
      'set SFTP_HOST/PORT/USERNAME/PASSWORD to run real SFTP directory download',
    )
    if (!SFTP_HOST) {
      console.log('[sftp] SFTP_HOST 未设置，跳过目录下载用例')
      return
    }

    await gotoApp(page, '/sftp')

    await page.getByPlaceholder('例如: 192.168.1.1').fill(SFTP_HOST)
    const port = fieldByLabel(page, '端口')
    await port.fill('')
    await port.fill(SFTP_PORT)
    await fieldByLabel(page, '用户名').fill(SFTP_USERNAME ?? '')
    await fieldByLabel(page, '密码').fill(SFTP_PASSWORD ?? '')

    await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes('/sftp/connect/') && r.request().method() === 'POST',
        { timeout: 30_000 },
      ),
      page.getByRole('button', { name: '连接' }).click(),
    ])

    await expect(page.locator('.file-table')).toBeVisible({ timeout: 30_000 })

    // Find first directory row's "下载" button (the one in the dir action group)
    const dirRows = page.locator('.file-table .is-dir')
    if ((await dirRows.count()) === 0) {
      test.skip(true, '已连接但当前目录无子目录')
      return
    }

    // Click the first directory row to open it, then go back and download
    const firstDirDownload = dirRows.first().locator('xpath=ancestor::tr').getByRole('button', { name: '下载' })
    if ((await firstDirDownload.count()) === 0) {
      test.skip(true, '目录行无下载按钮')
      return
    }

    await firstDirDownload.click()

    // Progress card should appear
    await expect(page.locator('.download-progress-card')).toBeVisible({ timeout: 5_000 })

    // Wait for download to complete (success message)
    await expect(page.getByText(/已保存/).first()).toBeVisible({ timeout: 60_000 })

    console.log('[sftp] 目录下载SSE完成')
  })
})
