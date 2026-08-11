import { test, expect } from '@playwright/test'
import path from 'node:path'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { execSync } from 'node:child_process'
import { SEEDED_FILES, DOWNLOAD_DIR } from '../fixtures/test-data'
import { gotoApp } from '../helpers/nav'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

function ensureDownloadDir() {
  if (!fs.existsSync(DOWNLOAD_DIR)) {
    fs.mkdirSync(DOWNLOAD_DIR, { recursive: true })
  }
}

function safeSheetName(name: string) {
  return name.replace(/[\/\\\s-]/g, '_').slice(0, 31)
}

/** 优先用项目 venv 里的 python，回退系统 python */
function findPython() {
  const candidates = [
    process.env.PYTHON_BIN,
    path.resolve(__dirname, '..', '..', '..', '.venv', 'Scripts', 'python.exe'),
    path.resolve(__dirname, '..', '..', '..', '.venv', 'bin', 'python'),
    'python',
    'python3',
  ].filter(Boolean) as string[]
  for (const py of candidates) {
    try {
      execSync(`"${py}" -c "import openpyxl"`, { stdio: 'pipe' })
      return py
    } catch {
      // try next
    }
  }
  return null
}

const PYTHON_WITH_OPENPYXL = findPython()

test.describe('数据管理 /data 导出工具原生图表', { tag: ['@data'] }, () => {
  test('@p2 UI：开启 Excel 原生图表后隐藏柱宽滑块', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '导出工具' }).click()
    await expect(page.locator('.tab-btn.active')).toContainText('导出工具')

    // 选择已植入的 GAGE_S1 文件
    const fileSelect = page.locator('.content-section:visible .banner-file-select').first()
    await fileSelect.locator('.el-select__wrapper').click()
    await page.locator('.el-select-dropdown__item:visible')
      .filter({ hasText: SEEDED_FILES.GAGE_S1 })
      .click()

    // 等待参数加载完成
    await expect(page.locator('.param-select')).toBeVisible({ timeout: 15_000 })

    // 默认状态下柱宽滑块应存在
    await expect(page.locator('.bar-width-group')).toBeVisible()

    // 勾选「Excel 原生图表」
    const nativeCheckbox = page.locator('.native-chart')
    await nativeCheckbox.click()
    await expect(nativeCheckbox).toHaveClass(/is-checked/)

    // 原生图表模式下 Excel 自身控制列间距，柱宽滑块应隐藏
    await expect(page.locator('.bar-width-group')).toHaveCount(0)

    // 取消勾选后滑块恢复
    await nativeCheckbox.click()
    await expect(nativeCheckbox).not.toHaveClass(/is-checked/)
    await expect(page.locator('.bar-width-group')).toBeVisible()
  })

  test('@p2 UI：Excel 原生图表旁有 helper 提示，悬停可查看说明且不误触勾选', async ({ page }) => {
    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '导出工具' }).click()
    await expect(page.locator('.tab-btn.active')).toContainText('导出工具')

    const fileSelect = page.locator('.content-section:visible .banner-file-select').first()
    await fileSelect.locator('.el-select__wrapper').click()
    await page.locator('.el-select-dropdown__item:visible')
      .filter({ hasText: SEEDED_FILES.GAGE_S1 })
      .click()
    await expect(page.locator('.param-select')).toBeVisible({ timeout: 15_000 })

    // helper 图标跟随「Excel 原生图表」选项出现
    const helpIcon = page.locator('.native-help-icon')
    await expect(helpIcon).toBeVisible()

    // 悬停弹出说明，包含关键词（getByRole 只匹配可访问树中可见的 tooltip，隐藏的 select popper 不参与）
    await helpIcon.hover()
    const tooltip = page.getByRole('tooltip').filter({ hasText: '文件体积更小' })
    await expect(tooltip).toBeVisible({ timeout: 5_000 })
    await expect(tooltip).toContainText('直接编辑图表样式')

    // 图标在 checkbox label 之外，悬停/点击不应改变勾选状态
    await expect(page.locator('.native-chart')).not.toHaveClass(/is-checked/)
  })

  test('@p2 导出原生图表 xlsx：请求带 native_chart=true、文件可解析且含图表', async ({ page }) => {
    ensureDownloadDir()

    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '导出工具' }).click()

    // 选择 GAGE_S1 并等待参数
    const fileSelect = page.locator('.content-section:visible .banner-file-select').first()
    await fileSelect.locator('.el-select__wrapper').click()
    await page.locator('.el-select-dropdown__item:visible')
      .filter({ hasText: SEEDED_FILES.GAGE_S1 })
      .click()
    await expect(page.locator('.param-select')).toBeVisible({ timeout: 15_000 })

    // 选择两个稳定的真正测试参数（避免 Serial_No / Part_No 等 ID 列）
    const TEST_PARAMS = ['R_Kelvin_VIN', 'R_Kelvin_VDRV']
    await page.locator('.param-select').click()
    for (const param of TEST_PARAMS) {
      await page.locator('.el-select-dropdown__item:visible')
        .filter({ hasText: new RegExp(`^${param}$`) })
        .click()
    }
    await page.keyboard.press('Escape')

    // 勾选原生图表
    const nativeCheckbox = page.locator('.native-chart')
    await nativeCheckbox.click()
    await expect(nativeCheckbox).toHaveClass(/is-checked/)

    // 导出并同时等待响应与下载（批量导出可能耗时较长，放宽等待）
    const exportBtn = page.locator('button').filter({ hasText: '批量导出 Excel' })
    const [resp, download] = await Promise.all([
      page.waitForResponse(
        (r) => r.url().includes('/export/batch_charts/')
          && r.request().method() === 'POST'
          && !!r.request().postData()?.includes('native_chart'),
        { timeout: 60_000 },
      ),
      page.waitForEvent('download'),
      exportBtn.click(),
    ])

    expect(resp.status()).toBe(200)
    expect(resp.headers()['content-type']).toContain(
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )

    const downloadPath = path.join(DOWNLOAD_DIR, `e2e-native-${Date.now()}.xlsx`)
    await download.saveAs(downloadPath)

    // 文件存在且非空
    expect(fs.existsSync(downloadPath)).toBe(true)
    const stat = fs.statSync(downloadPath)
    expect(stat.size).toBeGreaterThan(3 * 1024)

    // 验证 xlsx（zip）签名
    const buf = fs.readFileSync(downloadPath)
    expect(buf.subarray(0, 4).toString()).toBe('PK\x03\x04')

    // 用后端同款 openpyxl 校验：能打开、总览 sheet 行数正确、参数 sheet 含图表
    if (!PYTHON_WITH_OPENPYXL) {
      test.skip(true, '当前环境无带 openpyxl 的 Python，跳过文件内容解析')
    } else {
      const titles = TEST_PARAMS.map((t) => safeSheetName(t).replace(/'/g, "\\'"))
      const script = `import openpyxl; wb = openpyxl.load_workbook(r'${downloadPath.replace(/\\/g, '\\\\')}'); ws = wb['总览']; assert ws.max_row == 3, 'summary row count'; assert all(len(wb[title]._charts) > 0 for title in [r'${titles[0]}', r'${titles[1]}'])`
      // 用退出码判断：断言失败会抛异常，execSync 非零退出 → 测试失败
      execSync(`"${PYTHON_WITH_OPENPYXL}" -c "${script}"`, { stdio: 'pipe' })
    }
  })

  test('@p2 原生图表 xlsx 体积显著小于 PNG 嵌入版本', async ({ page }) => {
    ensureDownloadDir()

    await gotoApp(page, '/data')
    await page.locator('.tab-btn').filter({ hasText: '导出工具' }).click()

    const fileSelect = page.locator('.content-section:visible .banner-file-select').first()
    await fileSelect.locator('.el-select__wrapper').click()
    await page.locator('.el-select-dropdown__item:visible')
      .filter({ hasText: SEEDED_FILES.GAGE_S1 })
      .click()
    await expect(page.locator('.param-select')).toBeVisible({ timeout: 15_000 })

    // 选择两个稳定的真正测试参数
    const TEST_PARAMS = ['R_Kelvin_VIN', 'R_Kelvin_VDRV']
    await page.locator('.param-select').click()
    for (const param of TEST_PARAMS) {
      await page.locator('.el-select-dropdown__item:visible')
        .filter({ hasText: new RegExp(`^${param}$`) })
        .click()
    }
    await page.keyboard.press('Escape')

    // 先导出 PNG 版本并记录大小
    const [pngDownload] = await Promise.all([
      page.waitForEvent('download'),
      page.locator('button').filter({ hasText: '批量导出 Excel' }).click(),
    ])
    const pngPath = path.join(DOWNLOAD_DIR, `e2e-png-${Date.now()}.xlsx`)
    await pngDownload.saveAs(pngPath)
    const pngSize = fs.statSync(pngPath).size

    // 再勾选原生图表导出
    const nativeCheckbox = page.locator('.native-chart')
    await nativeCheckbox.click()
    await expect(nativeCheckbox).toHaveClass(/is-checked/)

    const [nativeDownload] = await Promise.all([
      page.waitForEvent('download'),
      page.locator('button').filter({ hasText: '批量导出 Excel' }).click(),
    ])
    const nativePath = path.join(DOWNLOAD_DIR, `e2e-native-compare-${Date.now()}.xlsx`)
    await nativeDownload.saveAs(nativePath)
    const nativeSize = fs.statSync(nativePath).size

    expect(nativeSize).toBeLessThan(pngSize * 0.5)
  })
})
