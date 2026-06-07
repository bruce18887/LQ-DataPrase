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
 * - 已保存配置区：.saved-configs（仅 savedConfigs.length>0 时渲染，数据来自后端 GET /sftp/configs/）
 * - 连接后文件表：.file-table / el-table；断开按钮「断开」；行内下载按钮「下载」
 *
 * 注意：配置已改为后端持久化（GET /sftp/configs/、POST /sftp/save_config/、
 *       POST /sftp/delete_config/），密码加密存储且永不回传浏览器。@p2 用例
 *       通过 UI（保存配置对话框 + 已保存配置卡片 + 删除）走完整后端往返。
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

test.describe('@p2 SFTP 已保存配置（后端持久化）', { tag: ['@p2', '@sftp'] }, () => {
  // 唯一名称，避免与历史/并行数据冲突；测试自身负责清理。
  const CFG_NAME = `e2e-cfg-${Date.now()}`

  test('保存配置对话框 → 卡片含已保存密码标 → 删除', async ({ page }) => {
    await gotoApp(page, '/sftp')
    await expect(page.locator('.connect-card')).toBeVisible()

    // 1) 填写连接表单（host/username 必填，启用「保存配置」按钮）。
    await page.getByPlaceholder('例如: 192.168.1.1').fill('10.0.0.42')
    await fieldByLabel(page, '用户名').fill('tester')
    await fieldByLabel(page, '密码').fill('s3cret')

    const saveBtn = page.getByRole('button', { name: '保存配置' })
    await expect(saveBtn).toBeEnabled()

    // 2) 打开命名对话框，校验空名拦截，再填入自定义名称提交。
    await saveBtn.click()
    const dialog = page.locator('.el-dialog').filter({ hasText: '保存配置' })
    await expect(dialog).toBeVisible()

    const nameInput = dialog.locator('input').first()
    await nameInput.fill('')
    await dialog.getByRole('button', { name: '保存', exact: true }).click()
    // 名称为空时应有校验错误且对话框不关闭。
    await expect(dialog.locator('.el-form-item__error')).toBeVisible()
    await expect(dialog).toBeVisible()

    await nameInput.fill(CFG_NAME)
    await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes('/sftp/save_config/') && r.request().method() === 'POST',
        { timeout: 15_000 },
      ),
      dialog.getByRole('button', { name: '保存', exact: true }).click(),
    ])

    // 3) 已保存配置区出现该卡片，且带「已保存密码」标签（has_password=true）。
    const card = page
      .locator('.saved-configs .config-item')
      .filter({ has: page.locator('.config-name', { hasText: CFG_NAME }) })
    await expect(card).toBeVisible()
    await expect(card.locator('.pw-tag')).toHaveText(/已保存密码/)

    // 4) 删除（确认弹窗 → 删除按钮）→ 卡片消失。
    await card.getByRole('button', { name: '删除配置' }).click()
    const confirm = page.locator('.el-message-box')
    await expect(confirm).toBeVisible()
    await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes('/sftp/delete_config/') && r.request().method() === 'POST',
        { timeout: 15_000 },
      ),
      confirm.getByRole('button', { name: '删除', exact: true }).click(),
    ])
    await expect(
      page.locator('.saved-configs .config-name', { hasText: CFG_NAME }),
    ).toHaveCount(0)
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
